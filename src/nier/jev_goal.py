"""Bounded device goals driven by typed Jev decisions.

Jev is deliberately used as a selector here, not as a free-form action
generator. The host builds a finite set of validated candidate actions from
the current UI observation, and Jev returns the id of one candidate. If the
accessibility tree is insufficient, Jev can request one OCR read for that
observation. When it needs a strategy change, Jev may ask an optional LLM for
directional guidance; Jev remains responsible for selecting every action.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic, sleep

from .agent import (
    AgentDevice,
    AgentPlan,
    AgentRun,
    AgentStep,
    _JEV_MAX_OCR_SPANS,
    _JEV_MAX_TEXT_LENGTH,
    _JEV_MAX_UI_NODES,
    _JEV_MAX_UI_SUMMARY_CHARS,
    _activity_context,
    _jsonable,
    _semantic_ui,
    _structured_ui,
    _ui_summary,
)
from .errors import BackendError, ModelError
from .logging_utils import step as log_step
from .models.base import LlmProvider, OcrProvider, TextSpan
from .models.jev import JevAnswer, JevProvider, JevQuestion
from .protocol import ActionResult, ActivityInfo, validate_package_name
from .results import ExecutionRecord
from .ui import UiDocument, UiNode, parse_uidump


_WAIT_INTERVAL_SECONDS = 0.75
_MAX_CONSECUTIVE_WAITS = 3
_MAX_STALE_DECISIONS = 3
_MAX_LLM_GUIDANCE_CHARS = 1_200


@dataclass(frozen=True)
class JevGoalCandidate:
    """One host-validated action offered to a Jev goal.

    ``id`` is stable only for the current observation.  A new observation may
    produce a different candidate list, so callers must never cache ids
    across actions.
    """

    id: str
    label: str
    action: AgentStep
    source: str
    metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "action": self.action.to_dict(),
            "source": self.source,
            "metadata": _jsonable(self.metadata),
        }

    def to_decision_payload(self) -> dict[str, object]:
        """Describe an option without sending its executable action or geometry."""
        spatial = {
            "bounds",
            "center",
            "box",
            "x",
            "y",
            "left",
            "top",
            "right",
            "bottom",
            "width",
            "height",
        }
        metadata = {
            key: value[:_JEV_MAX_TEXT_LENGTH] if isinstance(value, str) else value
            for key, value in self.metadata.items()
            if key.casefold() not in spatial
        }
        return {
            "id": self.id,
            "label": self.label,
            "source": self.source,
            "metadata": _jsonable(metadata),
        }


@dataclass(frozen=True)
class _JevObservation:
    candidates: tuple[JevGoalCandidate, ...]
    state: Mapping[str, object]
    freshness_fingerprint: object
    screenshot_digest: str | None
    ocr_inspected: bool


class JevGoal:
    """Execute a bounded Android goal using Jev for typed decisions.

    Each observation asks Jev two questions in one request:

    * ``done`` is a Noul predicate for whether the user goal is satisfied;
    * ``next`` is a Choice over host-generated, validated candidate actions,
      plus bounded ``inspect_ocr``, ``call_llm``, ``wait``, and ``blocked``
      options.

    Jev is the primary decision-maker. If configured, the LLM is called only
    when Jev selects ``call_llm``; it returns a short strategic adjustment,
    never a device action. Jev then chooses the next host-validated candidate.

    Optional ``progress`` is a Score question intended for telemetry and
    stuck detection.  It is disabled by default because a score is less
    reliable as a success gate than an explicit Noul predicate.

    Decisions are checked against a fresh host observation before an action is
    dispatched. Non-action decisions and dry-run previews reuse the initial
    observation. The loop is bounded by ``max_steps`` and ``max_seconds``; OCR
    runs only after Jev requests it and at most once per observation.
    Completion returns ``needs_verification`` for the caller to review.
    Set ``prefer_webview=False`` for native screens to skip the WebView probe.
    """

    def __init__(
        self,
        device: AgentDevice,
        jev: JevProvider,
        *,
        provider: str = "jev",
        ocr: OcrProvider | None = None,
        max_steps: int = 8,
        max_seconds: float = 45.0,
        done_threshold: float = 0.85,
        action_threshold: float = 0.65,
        max_candidates: int = 32,
        allowed_apps: Mapping[str, str] | None = None,
        allowed_controls: Sequence[str] | None = None,
        denied_controls: Sequence[str] = (),
        use_score: bool = False,
        prefer_webview: bool = True,
        llm: LlmProvider | None = None,
        llm_provider: str | None = None,
        max_llm_assists: int = 2,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if not 0.0 < max_seconds <= 45.0:
            raise ValueError("max_seconds must be greater than 0 and at most 45")
        if not 0.0 <= done_threshold <= 1.0:
            raise ValueError("done_threshold must be between 0 and 1")
        if not 0.0 <= action_threshold <= 1.0:
            raise ValueError("action_threshold must be between 0 and 1")
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if (
            isinstance(max_llm_assists, bool)
            or not isinstance(max_llm_assists, int)
            or max_llm_assists < 0
        ):
            raise ValueError("max_llm_assists must be a non-negative integer")
        if allowed_apps is not None and not isinstance(allowed_apps, Mapping):
            raise TypeError("allowed_apps must map display labels to Android package names")
        if isinstance(allowed_controls, (str, bytes, bytearray)):
            raise TypeError("allowed_controls must be a sequence of control labels")
        if isinstance(denied_controls, (str, bytes, bytearray)):
            raise TypeError("denied_controls must be a sequence of control labels")
        if allowed_controls is not None and any(
            not isinstance(item, str) or not item.strip() for item in allowed_controls
        ):
            raise ValueError("allowed_controls must contain non-empty strings")
        if any(not isinstance(item, str) or not item.strip() for item in denied_controls):
            raise ValueError("denied_controls must contain non-empty strings")
        self.device = device
        self.jev = jev
        self.provider = provider
        self.ocr = ocr
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        self.done_threshold = done_threshold
        self.action_threshold = action_threshold
        self.max_candidates = max_candidates
        normalized_apps: list[tuple[str, str]] = []
        seen_app_labels: set[str] = set()
        seen_candidate_labels: set[str] = set()
        for label, package in (allowed_apps or {}).items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError("allowed_apps labels must be non-empty strings")
            normalized_label = _normalize_label(label)
            if normalized_label in seen_app_labels:
                raise ValueError("allowed_apps labels must be unique after normalization")
            try:
                package = validate_package_name(package)
            except ValueError as exc:
                raise ValueError(f"invalid package in allowed_apps for {label!r}: {exc}") from exc
            candidate_label = f"打开应用：{label.strip()}"[:160]
            normalized_candidate_label = _normalize_label(candidate_label)
            if normalized_candidate_label in seen_candidate_labels:
                raise ValueError("allowed_apps labels must be unique after candidate clipping")
            seen_app_labels.add(normalized_label)
            seen_candidate_labels.add(normalized_candidate_label)
            normalized_apps.append((label.strip(), package))
        self.allowed_apps = tuple(normalized_apps)
        self.allowed_controls = (
            None
            if allowed_controls is None
            else frozenset(_normalize_label(item) for item in allowed_controls)
        )
        self.denied_controls = frozenset(
            _normalize_label(item) for item in denied_controls
        )
        self.use_score = use_score
        self.prefer_webview = prefer_webview
        self.llm = llm
        self.llm_provider = llm_provider or ("custom" if llm is not None else "")
        self.max_llm_assists = max_llm_assists

    def run(
        self,
        instruction: str,
        *,
        dry_run: bool = False,
        max_steps: int | None = None,
    ) -> AgentRun:
        """Run a Jev goal, or preview its next candidate with ``dry_run``."""
        record = self._start_record(
            "jev-goal",
            instruction=instruction,
            dry_run=dry_run,
            done_threshold=self.done_threshold,
            action_threshold=self.action_threshold,
            max_candidates=self.max_candidates,
            max_seconds=self.max_seconds,
            prefer_webview=self.prefer_webview,
            llm_assist_provider=self.llm_provider or None,
            max_llm_assists=self.max_llm_assists,
            allowed_apps=[
                {"label": label, "package": package}
                for label, package in self.allowed_apps
            ],
            allowed_controls=(
                None if self.allowed_controls is None else sorted(self.allowed_controls)
            ),
            denied_controls=sorted(self.denied_controls),
            use_score=self.use_score,
        )
        return self._run_goal(
            instruction,
            dry_run=dry_run,
            max_steps=max_steps,
            record=record,
        )

    def _run_goal(
        self,
        instruction: str,
        *,
        dry_run: bool,
        max_steps: int | None,
        record: ExecutionRecord,
    ) -> AgentRun:
        started_at = monotonic()
        step_limit = self.max_steps if max_steps is None else max_steps
        if step_limit <= 0:
            record.error = "max_steps must be positive"
            record.finish(False, phase="planning")
            raise ValueError("max_steps must be positive")
        if not isinstance(instruction, str) or not instruction.strip():
            record.error = "instruction must not be empty"
            record.finish(False, phase="planning")
            raise ValueError("instruction must not be empty")
        instruction = instruction.strip()

        steps: list[AgentStep] = []
        results: list[ActionResult] = []
        history: list[dict[str, object]] = []
        jev_data: dict[str, object] | None = None
        llm_guidance = ""
        llm_assists = 0
        llm_assist_history: list[dict[str, object]] = []

        def finish(success: bool, termination: str, *, error: str = "") -> AgentRun:
            plan_jev = None if jev_data is None else dict(jev_data)
            if plan_jev is not None and llm_assist_history:
                plan_jev["llm_assists"] = [dict(item) for item in llm_assist_history]
            plan = AgentPlan(
                goal=instruction,
                steps=tuple(steps),
                provider=self.provider,
                jev=plan_jev,
            )
            record.details["plan"] = plan.to_dict()
            if error:
                record.error = error
            record.finish(
                success,
                completed_steps=len(results),
                planned_steps=len(steps),
                termination=termination,
            )
            return AgentRun(
                instruction,
                plan,
                tuple(results),
                success,
                dry_run=dry_run,
                termination=termination,
            )

        pending_observation: _JevObservation | None = None
        pending_recognize_ocr = False
        stale_decisions = 0
        consecutive_waits = 0
        iteration = 0
        while True:
            if monotonic() - started_at >= self.max_seconds:
                return finish(
                    False,
                    "time_limit",
                    error=f"goal exceeded the {self.max_seconds:g}-second time limit",
                )
            iteration += 1
            try:
                if pending_observation is None:
                    observation = self._observe(
                        instruction,
                        history,
                        recognize_ocr=pending_recognize_ocr,
                        llm_guidance=llm_guidance,
                        llm_assists_used=llm_assists,
                    )
                else:
                    observation = pending_observation
                pending_observation = None
                pending_recognize_ocr = False
                jev_data, candidate, done, decision = self._decide(
                    observation,
                    instruction,
                    can_call_llm=(
                        self.llm is not None and llm_assists < self.max_llm_assists
                    ),
                )
                verify_fresh_state = (
                    not dry_run
                    and decision == "action"
                    and candidate is not None
                    and len(steps) < step_limit
                    and monotonic() - started_at < self.max_seconds
                )
                verify_ocr_target = (
                    verify_fresh_state
                    and candidate is not None
                    and candidate.source == "ocr"
                )
                fresh = (
                    self._observe(
                        instruction,
                        history,
                        capture_screenshot=verify_ocr_target,
                    )
                    if verify_fresh_state
                    else None
                )
            except Exception as exc:
                record.error = str(exc)
                record.finish(
                    False,
                    completed_steps=len(results),
                    planned_steps=len(steps),
                    phase="planning",
                )
                raise

            if monotonic() - started_at >= self.max_seconds:
                return finish(
                    False,
                    "time_limit",
                    error=f"goal exceeded the {self.max_seconds:g}-second time limit",
                )

            if fresh is None:
                stale_decisions = 0
            else:
                same_observation = (
                    fresh.freshness_fingerprint
                    == observation.freshness_fingerprint
                )
                if verify_ocr_target:
                    same_observation = same_observation and (
                        fresh.screenshot_digest == observation.screenshot_digest
                    )
                if not same_observation:
                    stale_decisions += 1
                    log_step(
                        "jev-goal-stale-decision",
                        iteration=iteration,
                        stale_decisions=stale_decisions,
                        max_stale_decisions=_MAX_STALE_DECISIONS,
                    )
                    if stale_decisions >= _MAX_STALE_DECISIONS:
                        return finish(
                            False,
                            "stale_state",
                            error="device state kept changing while Jev was deciding",
                        )
                    pending_observation = fresh
                    continue
                stale_decisions = 0

            if done:
                jev_data["verification_required"] = True
                return finish(True, "needs_verification")

            if decision == "inspect_ocr":
                consecutive_waits = 0
                history.append(
                    {
                        "decision": "inspect_ocr",
                        "executed": True,
                        "reason": "Jev requested OCR for this observation",
                    }
                )
                del history[:-8]
                pending_recognize_ocr = True
                continue

            if decision == "wait":
                if dry_run:
                    return finish(
                        False,
                        "wait_required",
                        error="Jev requested a fresh observation after waiting",
                    )
                consecutive_waits += 1
                history.append(
                    {
                        "decision": "wait",
                        "executed": False,
                        "reason": "Jev requested a bounded loading wait",
                    }
                )
                del history[:-8]
                if consecutive_waits >= _MAX_CONSECUTIVE_WAITS:
                    return finish(
                        False,
                        "loading_timeout",
                        error="device remained in a loading state after bounded waits",
                    )
                remaining_seconds = self.max_seconds - (monotonic() - started_at)
                sleep(min(_WAIT_INTERVAL_SECONDS, max(0.0, remaining_seconds)))
                continue

            if decision == "call_llm":
                try:
                    llm_guidance = self._request_direction(instruction, observation.state)
                except Exception as exc:
                    record.error = str(exc)
                    record.finish(
                        False,
                        completed_steps=len(results),
                        planned_steps=len(steps),
                        phase="planning",
                    )
                    raise
                llm_assists += 1
                assist = {
                    "iteration": iteration,
                    "provider": self.llm_provider or "llm",
                    "guidance": llm_guidance,
                }
                llm_assist_history.append(assist)
                history.append({"decision": "call_llm", "guidance": llm_guidance})
                del history[:-8]
                log_step(
                    "jev-goal-llm-assist",
                    iteration=iteration,
                    assist=llm_assists,
                    max_assists=self.max_llm_assists,
                )
                if monotonic() - started_at >= self.max_seconds:
                    return finish(
                        False,
                        "time_limit",
                        error=f"goal exceeded the {self.max_seconds:g}-second time limit",
                    )
                continue

            consecutive_waits = 0
            if decision == "low_confidence":
                return finish(
                    False,
                    "low_confidence",
                    error="Jev confidence was below the action threshold",
                )
            if decision == "blocked" or candidate is None:
                return finish(
                    False,
                    "blocked",
                    error="Jev found no safe candidate action that advances the goal",
                )

            if not dry_run and len(steps) >= step_limit:
                return finish(
                    False,
                    "max_steps",
                    error=f"goal exceeded the {step_limit}-step action limit",
                )

            if dry_run:
                steps.append(candidate.action)
                return finish(True, "next_action_preview")

            remaining = step_limit - len(steps)
            steps.append(candidate.action)
            log_step(
                "jev-goal",
                iteration=iteration,
                candidate=candidate.id,
                source=candidate.source,
                action=candidate.action.action,
                confidence=jev_data.get("next_confidence"),
                remaining_steps=max(0, remaining - 1),
            )
            try:
                result = self._dispatch(candidate.action)
            except Exception as exc:
                record.error = str(exc)
                record.finish(
                    False,
                    completed_steps=len(results),
                    failed_step=len(results),
                    termination="action_error",
                )
                raise
            results.append(result)
            history.append(
                {
                    "decision": "action",
                    "candidate": candidate.id,
                    "label": candidate.label,
                    "source": candidate.source,
                    "confidence": jev_data.get("next_confidence"),
                    "action": candidate.action.action,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code,
                }
            )
            del history[:-8]
            if not result.success:
                return finish(False, "action_failed", error=result.message or result.error_code)

    def _observe(
        self,
        instruction: str,
        history: Sequence[Mapping[str, object]],
        *,
        recognize_ocr: bool = False,
        capture_screenshot: bool = False,
    ) -> _JevObservation:
        screenshot = (
            self.device.screenshot()
            if recognize_ocr or capture_screenshot
            else None
        )
        if recognize_ocr and self.ocr is None:
            raise ModelError("Jev requested OCR, but no OCR provider is configured")
        try:
            dump = self.device.dump_ui(prefer_webview=self.prefer_webview)
        except BackendError as exc:
            dump = None
            dump_error = str(exc)
        else:
            dump_error = ""

        document: UiDocument | None = None
        if dump is not None:
            try:
                document = parse_uidump(dump)
            except (BackendError, ValueError):
                document = None

        activity: ActivityInfo | None = None
        activity_error = ""
        read_activity = getattr(self.device, "current_activity", None)
        if callable(read_activity):
            try:
                activity = read_activity()
            except (BackendError, TimeoutError) as exc:
                activity_error = str(exc)

        spans: tuple[TextSpan, ...] = ()
        if recognize_ocr and self.ocr is not None and screenshot is not None:
            spans = tuple(self.ocr.recognize(screenshot.data)[:_JEV_MAX_OCR_SPANS])
        candidates = self._candidates(
            instruction,
            document,
            spans,
            allowed_apps=self.allowed_apps,
            allowed_controls=self.allowed_controls,
            denied_controls=self.denied_controls,
        )
        state: dict[str, object] = {
            "goal": instruction,
            "activity": _activity_context(activity, activity_error),
            "ui": _semantic_ui(
                _structured_ui(
                    document,
                    dump,
                    dump_error,
                    max_nodes=_JEV_MAX_UI_NODES,
                    max_text_length=_JEV_MAX_TEXT_LENGTH,
                )
            ),
            "ui_summary": (
                _ui_summary(
                    document,
                    limit=64,
                    max_chars=_JEV_MAX_UI_SUMMARY_CHARS,
                    include_geometry=False,
                )
                if document is not None
                else (dump_error or "Structured UI is unavailable")[:_JEV_MAX_TEXT_LENGTH]
            ),
            "ocr_available": self.ocr is not None,
            "ocr_inspected": recognize_ocr,
            "ocr": [self._span_payload(index, span) for index, span in enumerate(spans)],
            "candidates": [candidate.to_decision_payload() for candidate in candidates],
            "history": [
                {
                    key: value[:_JEV_MAX_TEXT_LENGTH] if isinstance(value, str) else value
                    for key, value in item.items()
                }
                for item in history[-8:]
            ],
        }
        stable_state = {
            key: value
            for key, value in state.items()
            if key not in {"ocr", "ocr_inspected", "candidates"}
        }
        freshness_fingerprint = {
            "state": stable_state,
            "ui_candidates": [
                candidate.to_dict()
                for candidate in candidates
                if candidate.source != "ocr"
            ],
        }
        screenshot_digest = (
            sha256(screenshot.data).hexdigest() if screenshot is not None else None
        )
        return _JevObservation(
            tuple(candidates),
            state,
            freshness_fingerprint,
            screenshot_digest,
            recognize_ocr,
        )

    def _decide(
        self,
        observation: _JevObservation,
        instruction: str,
    ) -> tuple[dict[str, object], JevGoalCandidate | None, bool, str]:
        criteria = {candidate.id: candidate.label for candidate in observation.candidates}
        can_inspect_ocr = (
            self.ocr is not None
            and not observation.ocr_inspected
        )
        if can_inspect_ocr:
            criteria["inspect_ocr"] = (
                "Read visible text with OCR because the accessibility tree and current "
                "candidates do not provide enough information"
            )
        criteria["blocked"] = "No permitted candidate action can safely advance the goal"
        criteria["wait"] = "The screen is loading or transitioning; wait and observe again"
        questions: dict[str, JevQuestion] = {
            "done": JevQuestion.noul(
                "Is the user's goal already satisfied by the current Android state?"
            ),
            "next": JevQuestion.choice(
                "Choose one allowed candidate action that most safely advances the goal. "
                "Choose inspect_ocr only when the accessibility tree does not expose "
                "enough visible text to decide. OCR is read-only and is available at most "
                "once for this observation. "
                "Choose wait only for a visible loading or transition state. Choose blocked "
                "when no permitted candidate is safe or useful. An app candidate launches "
                "only an app from the caller's explicit allowlist.",
                criteria=criteria,
            ),
        }
        if self.use_score:
            questions["progress"] = JevQuestion.score(
                "How far has the current state progressed toward the user's goal?",
                ("not_started", "in_progress", "near_complete", "complete"),
            )

        response = self.jev.ask(observation.state, questions)
        done_answer = response.answer("done")
        next_answer = response.answer("next")
        done_probability = _noul_probability(done_answer)
        next_confidence = _answer_confidence(next_answer)
        selected = next_answer.choice
        candidate_by_id = {candidate.id: candidate for candidate in observation.candidates}
        candidate = candidate_by_id.get(selected or "")
        if done_probability >= self.done_threshold:
            decision = "complete"
            candidate = None
        elif next_confidence < self.action_threshold:
            decision = "low_confidence"
            candidate = None
        elif selected == "inspect_ocr" and can_inspect_ocr:
            decision = "inspect_ocr"
            candidate = None
        elif selected == "wait":
            decision = "wait"
            candidate = None
        elif selected in {"blocked", "none"} or candidate is None:
            decision = "blocked"
            candidate = None
        else:
            decision = "action"

        jev_data: dict[str, object] = {
            "done": done_answer.noul,
            "done_confidence": done_answer.confidence,
            "done_probability": done_probability,
            "next": selected,
            "next_confidence": next_confidence,
            "next_probabilities": dict(next_answer.probabilities),
            "decision": decision,
        }
        if self.use_score:
            jev_data["progress"] = response.answer("progress").score
        if candidate is not None:
            jev_data["candidate"] = candidate.to_dict()
        log_step(
            "jev-goal-decision",
            goal=instruction,
            done_probability=done_probability,
            next=selected,
            next_confidence=next_confidence,
        )
        return jev_data, candidate, done_probability >= self.done_threshold, decision

    def _candidates(
        self,
        instruction: str,
        document: UiDocument | None,
        spans: Sequence[TextSpan],
        *,
        allowed_apps: Sequence[tuple[str, str]],
        allowed_controls: frozenset[str] | None,
        denied_controls: frozenset[str],
    ) -> tuple[JevGoalCandidate, ...]:
        raw: list[tuple[str, str, AgentStep, dict[str, object], tuple[float, float] | None]] = []
        seen_labels: set[str] = set()

        def permitted(label: str) -> bool:
            normalized = _normalize_label(label)
            return normalized not in denied_controls and (
                allowed_controls is None or normalized in allowed_controls
            )

        if document is not None:
            ui_nodes = [
                (node, _node_label(node), node.center)
                for node in document.walk()
                if node.visible is not False and node.clickable is True and node.center is not None
            ]
            ui_counts = Counter(_normalize_label(label) for _node, label, _center in ui_nodes if label)
            for node, label, center in ui_nodes:
                if center is None or not label or node.visible is False or not permitted(label):
                    continue
                normalized_label = _normalize_label(label)
                if ui_counts[normalized_label] != 1 or normalized_label in seen_labels:
                    continue
                seen_labels.add(normalized_label)
                step = AgentStep.from_mapping(
                    {
                        "action": "tap",
                        "x": center[0],
                        "y": center[1],
                        "reason": f"Jev UI candidate: {label[:80]}",
                    }
                )
                metadata: dict[str, object] = {
                    "text": node.text,
                    "text_content": node.text_content,
                    "content_desc": node.content_desc,
                    "resource_id": node.resource_id,
                    "class_name": node.class_name,
                    "bounds": list(node.bounds or ()),
                    "center": list(center),
                    "clickable": node.clickable,
                }
                raw.append(("ui", label, step, metadata, center))

        ocr_counts = Counter(_normalize_label(item.text.strip()) for item in spans)
        for index, span in enumerate(spans):
            label = span.text.strip()
            normalized_label = _normalize_label(label)
            if not label or normalized_label in seen_labels or not permitted(label):
                continue
            if ocr_counts[normalized_label] != 1:
                continue
            center = (
                (span.box.left + span.box.right) / 2,
                (span.box.top + span.box.bottom) / 2,
            )
            seen_labels.add(normalized_label)
            step = AgentStep.from_mapping(
                {
                    "action": "tap",
                    "x": center[0],
                    "y": center[1],
                    "reason": f"Jev OCR candidate: {label[:80]}",
                }
            )
            raw.append(
                (
                    "ocr",
                    label,
                    step,
                    {
                        "text": label,
                        "confidence": span.confidence,
                        "kind": "ocr_text",
                    },
                    center,
                )
            )

        # App launches are offered only from the caller's explicit allowlist.
        # The package stays in the host-side AgentStep; Jev sees only this label.
        for label, package in allowed_apps:
            candidate_label = f"打开应用：{label}"[:160]
            step = AgentStep.from_mapping(
                {
                    "action": "open_app",
                    "package": package,
                    "reason": f"Jev app candidate: {label[:80]}",
                }
            )
            raw.append(("app", candidate_label, step, {"kind": "app"}, None))

        # System actions are deliberately small and fixed.  They are offered
        # only after UI/OCR targets so an accidental Back/Home is less likely
        # to win a crowded choice question.
        if permitted("返回上一页"):
            raw.append(
                (
                    "system",
                    "返回上一页",
                    AgentStep.from_mapping({"action": "back", "reason": "Jev system candidate"}),
                    {"key": "BACK"},
                    None,
                )
            )
        lowered = instruction.casefold()
        if permitted("返回主屏幕") and any(
            token in lowered for token in ("主屏", "桌面", "home", "launcher")
        ):
            raw.append(
                (
                    "system",
                    "返回主屏幕",
                    AgentStep.from_mapping({"action": "home", "reason": "Jev system candidate"}),
                    {"key": "HOME"},
                    None,
                )
            )
        if (
            self.allowed_controls is not None
            and permitted("提交当前输入")
            and document is not None
            and any(
                node.visible is not False and _is_input_node(node)
                for node in document.walk()
            )
        ):
            raw.append(
                (
                    "system",
                    "提交当前输入",
                    AgentStep.from_mapping({"action": "enter", "reason": "Jev system candidate"}),
                    {"key": "ENTER"},
                    None,
                )
            )

        unique_labels: set[str] = set()
        unique_raw = []
        for item in raw:
            display_label = _normalize_label(item[1][:160])
            if display_label and display_label not in unique_labels:
                unique_labels.add(display_label)
                unique_raw.append(item)
        raw = unique_raw

        app_candidates = [item for item in raw if item[0] == "app"]
        system = [item for item in raw if item[0] == "system"]
        visual = [item for item in raw if item[0] not in {"app", "system"}]
        # Keep explicit app choices and fixed recovery actions available when
        # the screen has many labels. UI targets still outrank OCR duplicates.
        reserved = app_candidates + system
        raw = visual[: max(0, self.max_candidates - len(reserved))]
        raw.extend(reserved[: max(0, self.max_candidates - len(raw))])
        source_indexes: dict[str, int] = {}
        candidates: list[JevGoalCandidate] = []
        for source, label, action, metadata, _center in raw:
            if source == "system":
                candidate_id = str(metadata.get("key", "system")).casefold()
            else:
                source_index = source_indexes.get(source, 0)
                source_indexes[source] = source_index + 1
                candidate_id = f"{source}_{source_index}"
            candidates.append(
                JevGoalCandidate(
                    id=candidate_id,
                    label=label[:160],
                    action=action,
                    source=source,
                    metadata=metadata,
                )
            )
        return tuple(candidates)

    @staticmethod
    def _span_payload(index: int, span: TextSpan) -> dict[str, object]:
        return {
            "id": f"span_{index}",
            "text": span.text[:_JEV_MAX_TEXT_LENGTH],
            "confidence": span.confidence,
        }

    def _dispatch(self, step: AgentStep) -> ActionResult:
        params = step.params
        if step.action == "tap":
            return self.device.tap(
                params["x"],
                params["y"],
                normalized=params["normalized"],
                duration_ms=params["duration_ms"],
            )  # type: ignore[arg-type]
        if step.action == "open_app":
            return self.device.open_app(params["package"])  # type: ignore[arg-type]
        if step.action in {"key", "back", "home", "enter"}:
            return self.device.key(params["key"])  # type: ignore[arg-type]
        raise ModelError(f"unsupported Jev goal candidate action: {step.action}")

    def _start_record(self, operation: str, **details: object) -> ExecutionRecord:
        record = self.device.session.recorder.start(operation)
        record.details.update({name: _jsonable(value) for name, value in details.items()})
        return record


def _node_label(node: UiNode) -> str:
    return (
        node.text.strip()
        or node.content_desc.strip()
        or node.text_content.strip()
        or node.resource_id.strip()
        or node.class_name.strip()
    )


def _normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())


def _is_input_node(node: UiNode) -> bool:
    value = f"{node.tag} {node.class_name}".casefold()
    return any(token in value for token in ("edittext", "input", "textarea"))


def _noul_probability(answer: JevAnswer) -> float:
    value = answer.noul
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _answer_confidence(answer: JevAnswer) -> float:
    value = answer.confidence
    if value is None:
        value = answer.selected_probability
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))
