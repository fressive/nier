from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nier.models.ocr import (
    PaddleOcrApiProvider,
    PaddleOcrCompatibleApiProvider,
    _flatten_result,
    _normalize_paddleocr_base_url,
    _parse_modern_paddleocr_result,
)


def test_paddle_ocr_legacy_result_is_flattened() -> None:
    result = [[[[0, 0], [10, 0], [10, 10], [0, 10]], ("hello", 0.98)]]
    assert _flatten_result(result) == result[0]


def test_paddle_ocr_empty_result() -> None:
    assert _flatten_result(None) == []


def test_paddle_ocr_modern_result_is_normalized_to_text_spans() -> None:
    result = [
        SimpleNamespace(
            json={
                "res": {
                    "rec_texts": ["登录", "设置"],
                    "rec_scores": [0.98, 0.87],
                    "rec_boxes": [[10, 20, 50, 60], [70, 80, 100, 110]],
                }
            }
        )
    ]

    spans = _parse_modern_paddleocr_result(result)

    assert [(span.text, span.confidence) for span in spans] == [
        ("登录", 0.98),
        ("设置", 0.87),
    ]
    assert spans[0].box.left == 10
    assert spans[1].box.right == 100


def test_paddle_ocr_compatible_api_posts_data_uri_and_parses_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def read(self) -> bytes:
            return json.dumps(
                {
                    "errorCode": 0,
                    "result": {
                        "ocrResults": [
                            {
                                "prunedResult": {
                                    "rec_texts": ["设置"],
                                    "rec_scores": [0.97],
                                    "rec_boxes": [[10, 20, 90, 60]],
                                }
                            }
                        ]
                    },
                }
            ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = PaddleOcrCompatibleApiProvider(
        base_url="http://ocr.example.test/docs",
        request_timeout=12,
    )

    spans = provider.recognize(b"\x89PNG\r\n\x1a\nimage")

    assert captured["request"].full_url == "http://ocr.example.test/ocr"
    body = json.loads(captured["request"].data.decode("utf-8"))
    assert body["file"].startswith("data:image/png;base64,")
    assert body["useTextlineOrientation"] is False
    assert captured["timeout"] == 12
    assert [(span.text, span.confidence) for span in spans] == [("设置", 0.97)]
    assert spans[0].box.right == 90


def test_paddle_ocr_api_result_is_normalized_to_text_spans() -> None:
    class FakeApiClient:
        def __init__(self) -> None:
            self.file_path = ""
            self.model = ""

        def ocr(self, *, file_path: str, model: str):
            self.file_path = file_path
            self.model = model
            assert Path(file_path).read_bytes() == b"\x89PNG\r\n\x1a\nimage"
            return SimpleNamespace(
                pages=[
                    SimpleNamespace(
                        pruned_result={
                            "rec_texts": ["登录", "设置"],
                            "rec_scores": [0.98, 0.87],
                            "rec_boxes": [
                                [10, 20, 50, 60],
                                [[70, 80], [100, 80], [100, 110], [70, 110]],
                            ],
                        }
                    )
                ]
            )

    client = FakeApiClient()
    provider = PaddleOcrApiProvider(client=client, model="PP-OCRv6")

    spans = provider.recognize(b"\x89PNG\r\n\x1a\nimage")

    assert client.model == "PP-OCRv6"
    assert client.file_path.endswith(".png")
    assert [(span.text, span.confidence) for span in spans] == [
        ("登录", 0.98),
        ("设置", 0.87),
    ]
    assert spans[0].box.left == 10
    assert spans[1].box.right == 100


def test_paddle_ocr_vl_document_result_is_normalized_to_text_spans() -> None:
    class FakeApiClient:
        def __init__(self) -> None:
            self.model = ""

        def parse_document(self, *, file_path: str, model: str):
            self.model = model
            assert Path(file_path).read_bytes().startswith(b"\x89PNG")
            return SimpleNamespace(
                pages=[
                    SimpleNamespace(
                        pruned_result={
                            "parsing_res_list": [
                                {
                                    "block_content": "设置",
                                    "block_bbox": [10, 20, 110, 60],
                                }
                            ]
                        }
                    )
                ]
            )

    client = FakeApiClient()
    provider = PaddleOcrApiProvider(client=client, model="PaddleOCR-VL-1.6")

    spans = provider.recognize(b"\x89PNG\r\n\x1a\nimage")

    assert client.model == "PaddleOCR-VL-1.6"
    assert [(span.text, span.confidence) for span in spans] == [("设置", 1.0)]
    assert spans[0].box.right == 110


def test_paddle_ocr_base_url_accepts_complete_jobs_endpoint() -> None:
    assert _normalize_paddleocr_base_url(
        "https://paddleocr.example/api/v2/ocr/jobs"
    ) == "https://paddleocr.example"
    assert _normalize_paddleocr_base_url(
        "https://paddleocr.example/prefix/api/v2/ocr/jobs/"
    ) == "https://paddleocr.example/prefix"
