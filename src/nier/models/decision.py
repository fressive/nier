"""Small deterministic decision provider useful before a learned model is configured."""

from __future__ import annotations

import re
from typing import Sequence

from .base import Decision, DecisionProvider, TextSpan


class TextMatchDecisionProvider:
    """Match an instruction against OCR text while preserving screen coordinates.

    This is intentionally conservative: it returns ``noop`` when no OCR span
    appears in the instruction instead of guessing a location. Learned
    providers such as jev/laya can implement the same interface later.
    """

    def decide(self, text: Sequence[TextSpan], instruction: str) -> Decision:
        normalized_instruction = _normalize(instruction)
        candidates = sorted(text, key=lambda item: item.confidence, reverse=True)
        for span in candidates:
            label = _normalize(span.text)
            if label and label in normalized_instruction:
                return Decision(
                    action="tap",
                    confidence=span.confidence,
                    rationale=f"OCR text matched instruction: {span.text}",
                    point=(
                        (span.box.left + span.box.right) / 2,
                        (span.box.top + span.box.bottom) / 2,
                    ),
                )
        return Decision(action="noop", confidence=0.0, rationale="no OCR span matched the instruction")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())

