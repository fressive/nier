"""Provider selection and the OCR-then-decide flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .base import (
    Decision,
    DecisionProvider,
    LlmProvider,
    LlmToolCall,
    OcrProvider,
    TextSpan,
    select_provider_name,
)
from .jev import JevProvider


@dataclass
class ModelRouter:
    ocr_providers: Mapping[str, OcrProvider]
    decision_providers: Mapping[str, DecisionProvider]
    llm_providers: Mapping[str, LlmProvider]
    jev_providers: Mapping[str, JevProvider] = field(default_factory=dict)

    def ocr(self, image: bytes, *, provider: str | None = None) -> Sequence[TextSpan]:
        name = select_provider_name(self.ocr_providers, provider)
        return self.ocr_providers[name].recognize(image)

    def decide(
        self,
        text: Sequence[TextSpan],
        instruction: str,
        *,
        provider: str | None = None,
    ) -> Decision:
        # The decision layer receives OCR coordinates so an action can be
        # mapped back to the device screen without asking an LLM to localize it.
        name = select_provider_name(self.decision_providers, provider)
        return self.decision_providers[name].decide(text, instruction)

    def complete(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        image: bytes | None = None,
    ) -> str:
        name = select_provider_name(self.llm_providers, provider)
        return self.llm_providers[name].complete(prompt, image=image)

    def complete_with_tools(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        tools: Sequence[Mapping[str, object]],
        image: bytes | None = None,
    ) -> Sequence[LlmToolCall]:
        name = select_provider_name(self.llm_providers, provider)
        return self.llm_providers[name].complete_with_tools(
            prompt,
            tools=tools,
            image=image,
        )

    def jev(self, *, provider: str | None = None) -> JevProvider:
        """Return a configured TypeSafe Jev client."""
        name = select_provider_name(self.jev_providers, provider)
        return self.jev_providers[name]
