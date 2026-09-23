"""TypeSafe Jev provider and the OCR-to-decision adapter.

Jev is a structured decision API rather than a free-form text generator.  The
client intentionally uses the Python standard library so enabling Jev does not
make the optional ``models`` dependencies mandatory.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as distribution_version
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..errors import ConfigurationError, ModelError
from ..logging_utils import block as log_block
from ..logging_utils import request as log_request
from ..logging_utils import response as log_response
from ..logging_utils import step as log_step
from ..logging_utils import verbosity as log_verbosity
from .base import Decision, TextSpan

JevOptions = Sequence[str] | Mapping[str, Any]
JevCriteria = Sequence[Any] | Mapping[str, Any]


def _nier_user_agent() -> str:
    try:
        return f"Nier/{distribution_version('nier')}"
    except PackageNotFoundError:
        return "Nier"


@dataclass(frozen=True)
class JevQuestion:
    """A typed Jev question.

    ``options`` is a script-friendly alias for the Choice ``criteria`` map;
    each string option is sent with itself as its description. ``criteria`` is
    used by Score questions. The raw mapping form accepted by
    :meth:`JevProvider.ask` is available when a newer Jev question type needs
    fields not represented here.
    """

    type: str
    instructions: Any
    options: tuple[str, ...] | Mapping[str, Any] = ()
    criteria: JevCriteria = ()

    @classmethod
    def choice(
        cls,
        instructions: Any,
        options: JevOptions | None = None,
        *,
        criteria: JevOptions | None = None,
    ) -> JevQuestion:
        if options is None:
            options = criteria
        elif criteria is not None:
            raise ValueError("pass either Jev choice options or criteria, not both")
        if options is None:
            raise ValueError("a Jev choice question needs options or criteria")
        normalized = _normalize_options(options)
        if not normalized:
            raise ValueError("a Jev choice question needs at least one option")
        return cls(type="choice", instructions=instructions, options=normalized)

    @classmethod
    def score(cls, instructions: Any, criteria: Sequence[Any]) -> JevQuestion:
        if isinstance(criteria, (str, bytes, bytearray, Mapping)):
            raise TypeError("a Jev score question needs a sequence of criteria")
        normalized = tuple(criteria)
        if not normalized:
            raise ValueError("a Jev score question needs at least one criterion")
        return cls(type="score", instructions=instructions, criteria=normalized)

    @classmethod
    def noul(cls, instructions: Any, criteria: Any = ()) -> JevQuestion:
        return cls(type="noul", instructions=instructions, criteria=criteria)

    def to_payload(self) -> dict[str, Any]:
        question_type = self.type.strip().lower()
        if not question_type:
            raise ValueError("Jev question type must not be empty")
        payload: dict[str, Any] = {
            "type": question_type,
            "instructions": _serialize_structured(self.instructions, "instructions"),
        }
        if question_type == "choice":
            criteria: JevCriteria = self.criteria or self.options
            if isinstance(criteria, Mapping):
                payload["criteria"] = _serialize_structured(criteria, "criteria")
            else:
                payload["criteria"] = {
                    str(item): str(item) for item in criteria
                }
            if not payload["criteria"]:
                raise ValueError("a Jev choice question needs at least one option")
        elif question_type == "score":
            criteria = self.criteria
            if isinstance(criteria, Mapping):
                raise ValueError("a Jev score question needs an ordered sequence of criteria")
            payload["criteria"] = _serialize_structured(criteria, "criteria")
            if not payload["criteria"]:
                raise ValueError("a Jev score question needs at least one criterion")
        elif question_type == "noul" and self.criteria:
            payload["criteria"] = _serialize_structured(self.criteria, "criteria")
        return payload


@dataclass(frozen=True)
class JevAnswer:
    """One typed answer returned by Jev."""

    type: str
    confidence: float | None = None
    choice: str | None = None
    score: float | None = None
    noul: float | None = None
    legend: Mapping[str, Any] = field(default_factory=dict)
    probabilities: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> JevAnswer:
        answer_type = str(payload.get("type", "")).strip().lower()
        if not answer_type:
            raise ModelError("Jev answer is missing its type")
        confidence = _optional_float(payload.get("confidence"), "confidence")
        score = _optional_float(payload.get("score"), "score")
        noul = _optional_float(payload.get("noul"), "noul")
        legend_value = payload.get("legend", {})
        if legend_value is None:
            legend_value = {}
        if not isinstance(legend_value, Mapping):
            raise ModelError("Jev answer legend must be a mapping")
        choice_value = payload.get("choice")
        choice = None if choice_value is None else str(choice_value)
        probabilities_value = payload.get("probabilities", {})
        if probabilities_value is None:
            probabilities_value = {}
        if not isinstance(probabilities_value, Mapping):
            raise ModelError("Jev answer probabilities must be a mapping")
        try:
            probabilities = {
                str(key): float(value) for key, value in probabilities_value.items()
            }
        except (TypeError, ValueError) as exc:
            raise ModelError("Jev answer probabilities must be numeric") from exc
        return cls(
            type=answer_type,
            confidence=confidence,
            choice=choice,
            score=score,
            noul=noul,
            legend=dict(legend_value),
            probabilities=probabilities,
            raw=dict(payload),
        )

    @property
    def selected_probability(self) -> float | None:
        if self.choice is None:
            return None
        return self.probabilities.get(self.choice)


@dataclass(frozen=True)
class JevResponse:
    """The complete response from one Jev request."""

    answers: Mapping[str, JevAnswer]
    model: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def answer(self, question_id: str) -> JevAnswer:
        try:
            return self.answers[question_id]
        except KeyError as exc:
            available = ", ".join(sorted(self.answers))
            raise ModelError(
                f"Jev response did not contain answer {question_id!r}; available: {available}"
            ) from exc


class JevProvider:
    """Small synchronous client for the TypeSafe Jev HTTP API.

    ``base_url`` is the complete request endpoint.  By default it is the
    TypeSafe System One endpoint.  API keys are read from ``api_key_env`` and
    are never included in errors or serialized request data.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.typesafe.ai/v1/systemone",
        api_key: str | None = None,
        api_key_env: str = "TYPESAFE_API_KEY",
        model: str = "jev-latest",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        if not self.base_url:
            raise ConfigurationError("Jev API base_url must not be empty")
        if timeout <= 0:
            raise ConfigurationError("Jev API timeout must be positive")
        if not model.strip():
            raise ConfigurationError("Jev model must not be empty")
        resolved_key = api_key or os.getenv(api_key_env)
        if not resolved_key and api_key_env == "TYPESAFE_API_KEY":
            # Keep the earlier Nier examples working while using TypeSafe's
            # current official environment variable as the default.
            resolved_key = os.getenv("JEV_API_KEY")
        if not resolved_key:
            raise ConfigurationError(
                f"Jev API key is missing from the configured environment variable {api_key_env!r}"
            )
        self._api_key = resolved_key

    def ask(
        self,
        state: Any,
        questions: Mapping[str, JevQuestion | Mapping[str, Any]],
    ) -> JevResponse:
        """Ask one or more typed questions about ``state``."""
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("Jev questions must be a non-empty mapping")
        payload_questions: dict[str, dict[str, Any]] = {}
        for question_id, question in questions.items():
            key = str(question_id).strip()
            if not key:
                raise ValueError("Jev question ids must not be empty")
            if isinstance(question, JevQuestion):
                payload_questions[key] = question.to_payload()
            elif isinstance(question, Mapping):
                payload_questions[key] = dict(question)
            else:
                raise TypeError("Jev questions must be JevQuestion or mapping values")

        request_body = {
            "model": self.model,
            "state": state,
            "questions": payload_questions,
        }
        log_step("jev", model=self.model, question_count=len(payload_questions))
        try:
            encoded = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ModelError(f"Jev request is not JSON serializable: {exc}") from exc

        request = urllib_request.Request(
            self.base_url,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": _nier_user_agent(),
            },
            method="POST",
        )
        log_request(
            "http",
            "POST",
            self.base_url,
            headers=request.headers,
            model=self.model,
            question_count=len(payload_questions),
        )
        if log_verbosity() >= 3:
            log_block(
                3,
                "JEV CONTEXT",
                "outgoing",
                _format_jev_context(state, payload_questions),
                model=self.model,
                question_count=len(payload_questions),
            )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout) as response:
                response_bytes = response.read()
                log_response(
                    "http",
                    getattr(response, "status", None),
                    target=self.base_url,
                    headers=getattr(response, "headers", None),
                    body_bytes=len(response_bytes),
                )
        except urllib_error.HTTPError as exc:
            detail = _response_error(exc)
            log_response(
                "http", exc.code, target=self.base_url, error_bytes=len(detail)
            )
            raise ModelError(f"Jev API request failed with HTTP {exc.code}: {detail}") from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise ModelError(f"Jev API request failed: {exc}") from exc

        try:
            decoded = json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelError("Jev API returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ModelError("Jev API response must be a JSON object")
        parsed = _parse_response(decoded)
        if log_verbosity() >= 2:
            log_block(
                2,
                "JEV RESULT",
                "returned",
                _format_jev_result(parsed),
                model=parsed.model or self.model,
                answer_count=len(parsed.answers),
            )
        return parsed

    # ``decide`` is a convenient alias for callers that use all model
    # providers through a decision-oriented vocabulary.
    decide = ask
    # Match the naming used by the TypeSafe SDK while keeping ``ask`` as the
    # shorter Nier spelling.
    system_one = ask

    def choice(
        self,
        state: Any,
        options: JevOptions | None = None,
        *,
        instructions: Any,
        question_id: str = "choice",
        criteria: JevOptions | None = None,
    ) -> JevAnswer:
        if options is None:
            options = criteria
        elif criteria is not None:
            raise ValueError("pass either Jev choice options or criteria, not both")
        if options is None:
            raise ValueError("a Jev choice question needs options or criteria")
        response = self.ask(
            state,
            {question_id: JevQuestion.choice(instructions, options)},
        )
        return response.answer(question_id)

    def score(
        self,
        state: Any,
        criteria: Sequence[str],
        *,
        instructions: Any,
        question_id: str = "score",
    ) -> JevAnswer:
        response = self.ask(
            state,
            {question_id: JevQuestion.score(instructions, criteria)},
        )
        return response.answer(question_id)

    def noul(
        self,
        state: Any,
        *,
        instructions: Any,
        question_id: str = "noul",
        criteria: Any = (),
    ) -> JevAnswer:
        response = self.ask(
            state,
            {question_id: JevQuestion.noul(instructions, criteria)},
        )
        return response.answer(question_id)


class JevDecisionProvider:
    """Select an OCR span with Jev and keep its coordinates host-side."""

    def __init__(self, client: JevProvider, *, confidence_threshold: float = 0.75) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.client = client
        self.confidence_threshold = confidence_threshold

    def decide(self, text: Sequence[TextSpan], instruction: str) -> Decision:
        spans = list(text)
        if not spans:
            return Decision(action="noop", confidence=0.0, rationale="OCR returned no text")

        # Keep the question bounded. Jev sees labels only; screen coordinates
        # remain host-side and are recovered from the selected span id.
        candidates = spans[:64]
        span_ids = [f"span_{index}" for index in range(len(candidates))]
        state = {
            "instruction": instruction,
            "spans": [
                {
                    "id": span_id,
                    "text": span.text[:240],
                    "confidence": span.confidence,
                }
                for span_id, span in zip(span_ids, candidates)
            ],
        }
        answer = self.client.choice(
            state,
            ["noop", *span_ids],
            instructions=(
                "Choose the OCR span that best satisfies the instruction. "
                "Return noop when no span is a suitable actionable target."
            ),
            question_id="target",
        )
        confidence = answer.confidence
        if confidence is None:
            confidence = answer.selected_probability or 0.0
        if answer.choice not in span_ids or confidence < self.confidence_threshold:
            return Decision(
                action="noop",
                confidence=confidence,
                rationale="Jev did not select a sufficiently confident OCR target",
            )

        index = span_ids.index(answer.choice)
        span = candidates[index]
        return Decision(
            action="tap",
            confidence=confidence,
            rationale=f"Jev selected OCR target: {span.text}",
            point=(
                (span.box.left + span.box.right) / 2,
                (span.box.top + span.box.bottom) / 2,
            ),
        )


def _normalize_options(options: JevOptions) -> tuple[str, ...] | Mapping[str, Any]:
    if isinstance(options, (str, bytes, bytearray)):
        raise TypeError("Jev choice options must be a sequence or mapping")
    if isinstance(options, Mapping):
        return {str(key): value for key, value in options.items()}
    return tuple(str(item) for item in options)


def _serialize_structured(value: Any, field_name: str) -> Any:
    """Validate the structured string/object/array fields accepted by Jev."""
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"Jev question {field_name} must not be empty")
        return normalized
    if isinstance(value, Mapping):
        if not value:
            raise ValueError(f"Jev question {field_name} must not be empty")
        return {
            str(key): _serialize_structured(item, field_name)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if not value:
            raise ValueError(f"Jev question {field_name} must not be empty")
        return [_serialize_structured(item, field_name) for item in value]
    if isinstance(value, (bool, int, float)):
        return value
    raise TypeError(
        f"Jev question {field_name} must be a string, mapping, or sequence"
    )


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ModelError(f"Jev answer {field_name} must be numeric") from exc


def _response_error(error: urllib_error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except OSError:
        body = ""
    return body[:500] or "empty response"


def _format_jev_context(
    state: Any, questions: Mapping[str, Mapping[str, Any]]
) -> str:
    lines: list[str] = []

    if not isinstance(state, Mapping):
        lines.append(f"State: {state!r}"[:300])
    else:
        goal = state.get("goal")
        if isinstance(goal, str) and goal:
            lines.extend((f"Goal: {goal[:300]}", ""))

        ui = state.get("ui")
        ui_summary = state.get("ui_summary")
        if ui is not None or ui_summary is not None:
            lines.append("UI:")
            if isinstance(ui, Mapping):
                source = ui.get("source")
                complete = ui.get("complete")
                if source is not None or complete is not None:
                    lines.append(f"  source={source!r} complete={complete!r}")
            if isinstance(ui_summary, str) and ui_summary:
                ui_lines = [f"  {line}" for line in ui_summary.splitlines()]
            else:
                ui_lines = _format_ui_tree(ui)
            lines.extend(_bounded_log_lines(ui_lines, 1_800))
            lines.append("")

        if "ocr" in state:
            lines.append("OCR:")
            lines.extend(
                _bounded_log_lines(_format_ocr_spans(state.get("ocr")), 1_800)
            )
            lines.append("")

    lines.append("Questions:")
    questions_list = list(questions.items())
    for question_id, question in questions_list[:20]:
        lines.append(f"- {question_id} ({question.get('type', 'unknown')})")
    if len(questions_list) > 20:
        lines.append(f"... {len(questions_list) - 20} more questions")

    return "\n".join(lines)


def _format_ui_tree(ui: Any) -> list[str]:
    if not isinstance(ui, Mapping):
        return ["  (unavailable)"]
    root = ui.get("root")
    if not isinstance(root, Mapping):
        warning = ui.get("warning")
        return [f"  {warning}" if warning else "  (no labelled nodes)"]

    lines: list[str] = []

    def visit(node: Mapping[str, Any], depth: int) -> None:
        if len(lines) >= 100:
            return
        values = [str(node.get("tag", "node"))]
        for key, label in (
            ("text", "text"),
            ("text_content", "content"),
            ("resource_id", "id"),
            ("content_desc", "description"),
            ("class_name", "class"),
            ("bounds", "bounds"),
            ("clickable", "clickable"),
        ):
            value = node.get(key)
            if value not in (None, "", []):
                values.append(f"{label}={value!r}")
        lines.append(f"{'  ' * (depth + 1)}<{' '.join(values)}>")
        children = node.get("children")
        if isinstance(children, Sequence) and not isinstance(
            children, (str, bytes, bytearray)
        ):
            for child in children:
                if len(lines) >= 100:
                    break
                if isinstance(child, Mapping):
                    visit(child, depth + 1)

    visit(root, 0)
    return lines or ["  (no labelled nodes)"]


def _format_ocr_spans(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        value = [value]
    elif isinstance(value, (str, bytes, bytearray)):
        return [f"  - {value!r}"]
    elif not isinstance(value, Sequence):
        return [f"  {value!r}" if value is not None else "  (none)"]

    lines: list[str] = []
    for index, item in enumerate(value[:100]):
        if isinstance(item, Mapping):
            span_id = item.get("id", f"span_{index}")
            text = item.get("text", "")
            confidence = item.get("confidence")
            box = item.get("box")
            details = [f"{span_id}: {text!r}"]
            if confidence is not None:
                details.append(f"confidence={confidence}")
            if isinstance(box, Mapping):
                coordinates = ("left", "top", "right", "bottom")
                if all(key in box for key in coordinates):
                    bounds = ", ".join(str(box[key]) for key in coordinates)
                    details.append(f"box=({bounds})")
            elif isinstance(box, Sequence) and not isinstance(
                box, (str, bytes, bytearray)
            ):
                details.append(f"box={tuple(box)!r}")
            lines.append("  - " + "; ".join(details))
        else:
            lines.append(f"  - {item!r}")
    if len(value) > 100:
        lines.append(f"  ... {len(value) - 100} more spans")
    if not lines:
        lines.append("  (no text recognized)")
    return lines


def _bounded_log_lines(lines: Sequence[str], max_chars: int) -> list[str]:
    bounded: list[str] = []
    used = 0
    for line in lines:
        remaining = max_chars - used
        if remaining <= 0:
            bounded.append("  ... (section truncated)")
            break
        if len(line) > remaining:
            bounded.append(line[:remaining] + "…")
            break
        bounded.append(line)
        used += len(line) + 1
    return bounded


def _format_jev_result(response: JevResponse) -> str:
    lines: list[str] = []
    for question_id, answer in response.answers.items():
        values = [f"{question_id} ({answer.type})"]
        if answer.choice is not None:
            values.append(f"choice={answer.choice!r}")
        if answer.score is not None:
            values.append(f"score={answer.score:g}")
        if answer.noul is not None:
            values.append(f"noul={answer.noul:g}")
        if answer.confidence is not None:
            values.append(f"confidence={answer.confidence:g}")
        lines.append("- " + "; ".join(values))
        if answer.probabilities:
            probabilities = ", ".join(
                f"{key}={value:g}"
                for key, value in answer.probabilities.items()
            )
            lines.append(f"    probabilities: {probabilities}")
    if response.usage:
        usage = ", ".join(
            f"{key}={value}" for key, value in response.usage.items()
        )
        lines.append(f"Usage: {usage}")
    return "\n".join(lines) or "(no answers)"


def _parse_response(decoded: Mapping[str, Any]) -> JevResponse:
    body = decoded.get("data", decoded)
    if not isinstance(body, Mapping):
        raise ModelError("Jev API response data must be an object")
    answers_value = body.get("answers", body.get("results"))
    if not isinstance(answers_value, Mapping) or not answers_value:
        raise ModelError("Jev API response is missing a non-empty answers object")
    answers: dict[str, JevAnswer] = {}
    for question_id, value in answers_value.items():
        if not isinstance(value, Mapping):
            raise ModelError(f"Jev answer {question_id!r} must be an object")
        answers[str(question_id)] = JevAnswer.from_payload(value)
    usage = body.get("usage", {})
    if not isinstance(usage, Mapping):
        usage = {}
    model = body.get("model")
    return JevResponse(
        answers=answers,
        model=None if model is None else str(model),
        usage=dict(usage),
        raw=dict(decoded),
    )


__all__ = [
    "JevAnswer",
    "JevCriteria",
    "JevDecisionProvider",
    "JevOptions",
    "JevProvider",
    "JevQuestion",
    "JevResponse",
]
