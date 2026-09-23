"""Stable model interfaces used by the testing runtime."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Protocol


@dataclass(frozen=True)
class BoundingBox:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class TextSpan:
    text: str
    confidence: float
    box: BoundingBox


def select_provider_name(
    providers: Mapping[str, object], provider: str | None = None
) -> str:
    """Select an explicitly named provider or the first configured one."""
    if provider is not None:
        return provider
    try:
        return next(iter(providers))
    except StopIteration as exc:
        raise KeyError("no providers are configured") from exc


class OcrProvider(Protocol):
    def recognize(self, image: bytes) -> Sequence[TextSpan]:
        ...


@dataclass(frozen=True)
class Decision:
    action: str
    confidence: float
    rationale: str = ""
    point: tuple[float, float] | None = None


class DecisionProvider(Protocol):
    def decide(self, text: Sequence[TextSpan], instruction: str) -> Decision:
        ...


@dataclass(frozen=True)
class LlmToolCall:
    """One function/tool call returned by an LLM provider."""

    name: str
    arguments: Mapping[str, object]
    id: str = ""


class LlmProvider(Protocol):
    def complete(self, prompt: str, *, image: bytes | None = None) -> str:
        ...

    def complete_with_tools(
        self,
        prompt: str,
        *,
        tools: Sequence[Mapping[str, object]],
        image: bytes | None = None,
    ) -> Sequence[LlmToolCall]:
        ...
