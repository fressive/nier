"""Optional local and hosted PaddleOCR providers."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping, Sequence
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from ..errors import ModelError
from ..logging_utils import request as log_request
from ..logging_utils import result as log_result
from ..logging_utils import response as log_response
from ..logging_utils import step as log_step
from .base import BoundingBox, TextSpan


class PaddleOcrProvider:
    def __init__(self, *, lang: str = "ch", **kwargs: Any) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise ModelError("PaddleOCR is not installed; install the models extra") from exc
        try:
            engine_options = dict(kwargs)
            # PaddleOCR 3.x defaults to the oneDNN CPU path, which currently
            # hits a PIR conversion error with some PaddlePaddle 3.3 wheels.
            # Its modern pipeline also exposes orientation/unwarping switches
            # that are unnecessary for a phone screenshot OCR pass.
            engine_options.setdefault("enable_mkldnn", False)
            engine_options.setdefault("use_doc_orientation_classify", False)
            engine_options.setdefault("use_doc_unwarping", False)
            engine_options.setdefault("use_textline_orientation", False)
            try:
                self._engine = PaddleOCR(lang=lang, **engine_options)
            except TypeError as exc:
                # PaddleOCR 2.x does not understand the 3.x-only options.
                # Retry with the caller's original arguments for that API.
                if not any(name in str(exc) for name in engine_options if name not in kwargs):
                    raise
                self._engine = PaddleOCR(lang=lang, **kwargs)
        except Exception as exc:  # library errors are version/platform-specific
            raise ModelError(f"failed to initialize PaddleOCR: {exc}") from exc

    def recognize(self, image: bytes) -> Sequence[TextSpan]:
        log_step("ocr", provider="paddleocr", image_bytes=len(image))
        try:
            if callable(getattr(self._engine, "predict", None)):
                result = self._engine.predict(_paddleocr_input(image))
                spans = _parse_modern_paddleocr_result(result)
                return _log_ocr_result(spans, provider="paddleocr")
            result = self._engine.ocr(image, cls=True)
        except Exception as exc:
            raise ModelError(f"PaddleOCR failed: {exc}") from exc
        spans: list[TextSpan] = []
        for line in _flatten_result(result):
            try:
                polygon, (text, confidence) = line
                xs = [float(point[0]) for point in polygon]
                ys = [float(point[1]) for point in polygon]
                spans.append(
                    TextSpan(
                        text=str(text),
                        confidence=float(confidence),
                        box=BoundingBox(min(xs), min(ys), max(xs), max(ys)),
                    )
                )
            except (TypeError, ValueError, IndexError) as exc:
                raise ModelError(f"unexpected PaddleOCR result shape: {line!r}") from exc
        return _log_ocr_result(spans, provider="paddleocr")


class PaddleOcrApiProvider:
    """Use the hosted PaddleOCR API and return normalised OCR spans.

    The official client accepts a local file path rather than raw bytes, so a
    screenshot is written to a short-lived temporary file for each request.
    The client and its optional dependency are loaded lazily to keep local
    OCR and the rest of Nier usable without the online API package.
    """

    def __init__(
        self,
        *,
        lang: str = "ch",
        api_key: str | None = None,
        api_key_env: str = "PADDLEOCR_ACCESS_TOKEN",
        base_url: str | None = None,
        model: str = "PP-OCRv6",
        request_timeout: float = 300.0,
        poll_timeout: float = 600.0,
        client: Any | None = None,
    ) -> None:
        if not lang.strip():
            raise ValueError("PaddleOCR language must not be empty")
        if not model.strip():
            raise ValueError("PaddleOCR API model must not be empty")
        if request_timeout <= 0 or poll_timeout <= 0:
            raise ValueError("PaddleOCR API timeouts must be positive")
        self.lang = lang
        self.model = model
        self._base_url = base_url or "paddleocr-api"
        self._client = client
        self._document_options: Any | None = None
        if self._client is not None:
            return

        try:
            from paddleocr import (
                PaddleOCRClient,
                PaddleOCRVLOptions,
                PPStructureV3Options,
            )
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ModelError(
                "PaddleOCRClient is not available; install paddleocr>=3.0"
            ) from exc

        token = api_key or os.getenv(api_key_env)
        if not token:
            raise ModelError(
                f"PaddleOCR API token is missing from environment variable {api_key_env!r}"
            )
        options: dict[str, Any] = {
            "token": token,
            "request_timeout": request_timeout,
            "poll_timeout": poll_timeout,
        }
        if base_url is not None:
            # The official SDK expects the service root and appends
            # ``/api/v2/ocr/jobs`` itself. Accepting the complete jobs URL is
            # useful because that is the endpoint shown by some deployments.
            options["base_url"] = _normalize_paddleocr_base_url(base_url)
        try:
            self._client = PaddleOCRClient(**options)
            if self.model == "PP-StructureV3":
                self._document_options = PPStructureV3Options(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_chart_recognition=False,
                )
            else:
                self._document_options = PaddleOCRVLOptions(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_chart_recognition=False,
                )
        except Exception as exc:  # SDK errors vary by installed PaddleOCR version
            raise ModelError(f"failed to initialize PaddleOCR API client: {exc}") from exc

    def recognize(self, image: bytes) -> Sequence[TextSpan]:
        if not isinstance(image, bytes) or not image:
            raise ModelError("PaddleOCR API input image must be non-empty bytes")
        log_step("ocr", provider="paddleocr-api", model=self.model, image_bytes=len(image))
        suffix = _image_suffix(image)
        with NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(image)
            temporary.flush()
            log_request(
                "paddleocr",
                "POST",
                self._base_url,
                model=self.model,
                file_bytes=len(image),
                file_suffix=suffix,
            )
            try:
                if _is_document_parsing_model(self.model):
                    options: dict[str, Any] = {
                        "file_path": temporary.name,
                        "model": self.model,
                    }
                    if self._document_options is not None:
                        options["options"] = self._document_options
                    result = self._client.parse_document(  # type: ignore[union-attr]
                        **options,
                    )
                else:
                    result = self._client.ocr(  # type: ignore[union-attr]
                        file_path=temporary.name,
                        model=self.model,
                    )
                log_response(
                    "paddleocr",
                    target=self._base_url,
                    body=getattr(result, "json", repr(result)),
                )
            except Exception as exc:
                raise ModelError(f"PaddleOCR API request failed: {exc}") from exc
        spans = _parse_api_result(result)
        return _log_ocr_result(
            spans,
            provider="paddleocr-api",
            model=self.model,
        )

    def close(self) -> None:
        """Close the underlying SDK client when it exposes ``close()``."""
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


class PaddleOcrCompatibleApiProvider:
    """Call a local FastAPI service exposing the PaddleOCR-compatible schema."""

    def __init__(
        self,
        *,
        base_url: str,
        request_timeout: float = 60.0,
    ) -> None:
        if not base_url.strip():
            raise ModelError("PaddleOCR compatible API base_url is missing")
        if request_timeout <= 0:
            raise ValueError("PaddleOCR compatible API timeout must be positive")
        self._endpoint = _compatible_ocr_endpoint(base_url)
        self._request_timeout = request_timeout

    def recognize(self, image: bytes) -> Sequence[TextSpan]:
        if not image:
            raise ModelError("PaddleOCR compatible API input image must be non-empty")
        log_step("ocr", provider="paddleocr-compatible", image_bytes=len(image))
        payload = {
            "file": (
                f"data:{_image_mime(image)};base64,"
                f"{base64.b64encode(image).decode('ascii')}"
            ),
            "fileType": 1,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": False,
        }
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        log_request(
            "http",
            "POST",
            self._endpoint,
            headers=request.headers,
            body=payload,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
                raw = response.read()
                log_response(
                    "http",
                    getattr(response, "status", None),
                    target=self._endpoint,
                    headers=getattr(response, "headers", None),
                    body=raw,
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            log_response("http", exc.code, target=self._endpoint, body=detail)
            raise ModelError(
                f"PaddleOCR compatible API returned HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError(f"PaddleOCR compatible API request failed: {exc}") from exc

        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelError("PaddleOCR compatible API returned invalid JSON") from exc
        if not isinstance(response, Mapping):
            raise ModelError("PaddleOCR compatible API returned a non-object response")
        error_code = response.get("errorCode", 0)
        if error_code not in (0, "0", None):
            raise ModelError(
                f"PaddleOCR compatible API failed ({error_code}): "
                f"{response.get('errorMsg', 'unknown error')}"
            )
        spans = _parse_api_result(response)
        return _log_ocr_result(spans, provider="paddleocr-compatible")

    def close(self) -> None:
        """Keep the provider lifecycle compatible with the hosted client."""
        return None


def _image_suffix(image: bytes) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def _log_ocr_result(
    spans: Sequence[TextSpan], *, provider: str, model: str | None = None
) -> Sequence[TextSpan]:
    values = [
        {
            "text": span.text,
            "confidence": span.confidence,
            "box": {
                "left": span.box.left,
                "top": span.box.top,
                "right": span.box.right,
                "bottom": span.box.bottom,
            },
        }
        for span in spans
    ]
    fields: dict[str, Any] = {"provider": provider, "count": len(values)}
    if model is not None:
        fields["model"] = model
    log_result("ocr", values, **fields)
    return spans


def _image_mime(image: bytes) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _compatible_ocr_endpoint(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/")
    for suffix in ("/docs", "/openapi.json"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    if not path.endswith("/ocr"):
        path += "/ocr"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _normalize_paddleocr_base_url(value: str) -> str:
    """Normalize either the SDK base URL or its complete jobs endpoint."""
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/")
    jobs_path = "/api/v2/ocr/jobs"
    if path.endswith(jobs_path):
        path = path[: -len(jobs_path)] or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), parsed.query, ""))


def _is_document_parsing_model(model: str) -> bool:
    return model in {
        "PP-StructureV3",
        "PaddleOCR-VL",
        "PaddleOCR-VL-1.5",
        "PaddleOCR-VL-1.6",
    }


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        result = getattr(value, name, None)
        if result is not None:
            return result
    return None


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def _api_pages(result: Any) -> list[Any]:
    pages = _field(result, "pages")
    if pages is not None:
        return _items(pages)
    wrapped = _field(result, "result")
    if wrapped is not None:
        pages = _field(wrapped, "ocrResults", "ocr_results", "pages")
        if pages is not None:
            return _items(pages)
    if isinstance(result, list):
        return [result]
    return [result]


def _page_payload(page: Any) -> Any:
    payload = _field(page, "pruned_result", "prunedResult")
    if payload is not None:
        return payload
    raw = _field(page, "raw")
    payload = _field(raw, "pruned_result", "prunedResult")
    return payload if payload is not None else page


def _parse_api_result(result: Any) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for page in _api_pages(result):
        payload = _page_payload(page)
        if isinstance(payload, list):
            spans.extend(_parse_legacy_lines(payload))
            continue
        if _field(payload, "res") is not None:
            payload = _field(payload, "res")
        parsing_blocks = _items(_field(payload, "parsing_res_list", "parsingResList"))
        if parsing_blocks:
            spans.extend(_parse_document_blocks(parsing_blocks))
            continue
        texts = _items(_field(payload, "rec_texts", "recTexts", "texts"))
        if not texts:
            continue
        scores = _items(_field(payload, "rec_scores", "recScores", "scores"))
        boxes = _items(
            _field(
                payload,
                "rec_boxes",
                "recBoxes",
                "rec_polys",
                "recPolys",
                "dt_polys",
                "dtPolys",
            )
        )
        if len(boxes) != len(texts):
            raise ModelError(
                "PaddleOCR API returned text and bounding-box counts that do not match"
            )
        for index, text in enumerate(texts):
            label = str(text).strip()
            if not label:
                continue
            try:
                confidence = float(scores[index]) if index < len(scores) else 0.0
                box = _bounding_box(boxes[index])
            except (TypeError, ValueError, IndexError) as exc:
                raise ModelError(
                    f"invalid PaddleOCR API result at span {index}: {text!r}"
                ) from exc
            spans.append(TextSpan(text=label, confidence=confidence, box=box))
    return spans


def _parse_document_blocks(blocks: list[Any]) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for index, block in enumerate(blocks):
        text = _field(block, "block_content", "blockContent", "text", "content")
        box_value = _field(block, "block_bbox", "blockBbox", "bbox", "box")
        if text is None or box_value is None:
            raise ModelError(
                f"invalid PaddleOCR document block at index {index}: missing text or box"
            )
        label = str(text).strip()
        if not label:
            continue
        confidence_value = _field(block, "confidence", "score")
        try:
            confidence = 1.0 if confidence_value is None else float(confidence_value)
            box = _bounding_box(box_value)
        except (TypeError, ValueError, IndexError) as exc:
            raise ModelError(
                f"invalid PaddleOCR document block at index {index}: {block!r}"
            ) from exc
        spans.append(TextSpan(text=label, confidence=confidence, box=box))
    return spans


def _parse_legacy_lines(value: list[Any]) -> list[TextSpan]:
    lines = value[0] if len(value) == 1 and isinstance(value[0], list) else value
    spans: list[TextSpan] = []
    for index, line in enumerate(lines):
        try:
            polygon, recognition = line
            text, confidence = recognition
            spans.append(
                TextSpan(
                    text=str(text),
                    confidence=float(confidence),
                    box=_bounding_box(polygon),
                )
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise ModelError(f"invalid PaddleOCR API legacy result at line {index}") from exc
    return spans


def _bounding_box(value: Any) -> BoundingBox:
    if isinstance(value, Mapping):
        left = _number(value, "left", "x_min", "xmin")
        top = _number(value, "top", "y_min", "ymin")
        right = _number(value, "right", "x_max", "xmax")
        bottom = _number(value, "bottom", "y_max", "ymax")
        return BoundingBox(left, top, right, bottom)

    points = _items(value)
    if len(points) == 4 and all(_is_number(item) for item in points):
        left, top, right, bottom = (float(item) for item in points)
        return BoundingBox(left, top, right, bottom)
    coordinates = []
    for point in points:
        if isinstance(point, Mapping):
            coordinates.append(
                (
                    _number(point, "x", "left", "x_min"),
                    _number(point, "y", "top", "y_min"),
                )
            )
        else:
            pair = _items(point)
            if len(pair) < 2 or not _is_number(pair[0]) or not _is_number(pair[1]):
                raise ValueError("a PaddleOCR polygon point must contain x and y")
            coordinates.append((float(pair[0]), float(pair[1])))
    if not coordinates:
        raise ValueError("a PaddleOCR bounding box must not be empty")
    xs, ys = zip(*coordinates)
    return BoundingBox(min(xs), min(ys), max(xs), max(ys))


def _number(value: Mapping[str, Any], *names: str) -> float:
    for name in names:
        if name in value:
            return float(value[name])
    raise ValueError(f"missing coordinate {names[0]}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _paddleocr_input(image: bytes) -> Any:
    """Decode screenshot bytes into the ndarray required by PaddleOCR 3.x."""
    if not image:
        raise ValueError("PaddleOCR input image must not be empty")
    try:
        import numpy as np
        from PIL import Image

        with Image.open(BytesIO(image)) as decoded:
            return np.asarray(decoded.convert("RGB"))
    except Exception as exc:
        raise ValueError(f"PaddleOCR could not decode the input image: {exc}") from exc


def _parse_modern_paddleocr_result(result: Any) -> list[TextSpan]:
    """Convert PaddleOCR 3.x ``OCRResult`` objects to the shared span model."""
    if isinstance(result, Mapping) or hasattr(result, "json"):
        items = [result]
    else:
        items = _items(result)
    pages: list[dict[str, Any]] = []
    for item in items:
        payload = _field(item, "json")
        if callable(payload):
            payload = payload()
        pages.append({"pruned_result": item if payload is None else payload})
    return _parse_api_result({"pages": pages})


def _flatten_result(result: Any) -> list[Any]:
    """Accept PaddleOCR 2.x nested output without hiding malformed entries."""
    if result is None:
        return []
    if isinstance(result, dict):
        text = result.get("rec_texts")
        scores = result.get("rec_scores")
        boxes = result.get("dt_polys") or result.get("rec_polys")
        if text is not None and scores is not None and boxes is not None:
            return [[box, (value, score)] for box, value, score in zip(boxes, text, scores)]
        return []
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list):
        return result[0]
    return list(result) if isinstance(result, list) else []
