"""OpenAI-compatible LLM provider, loaded only when configured."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import ConfigurationError, ModelError
from ..logging_utils import request as log_request
from ..logging_utils import result as log_result
from ..logging_utils import response as log_response
from ..logging_utils import step as log_step
from .base import LlmToolCall


class OpenAICompatibleProvider:
    def __init__(self, *, base_url: str, api_key: str | None, model: str, timeout: float = 60.0) -> None:
        if not api_key:
            raise ConfigurationError("LLM API key is missing from the configured environment variable")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ModelError("openai is not installed; install the models extra") from exc
        self.base_url = base_url.rstrip("/")
        self.model = model
        try:
            self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        except Exception as exc:
            raise ModelError(f"failed to initialize LLM client: {exc}") from exc

    def complete(self, prompt: str, *, image: bytes | None = None) -> str:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )
        log_step(
            "llm",
            model=self.model,
            prompt_chars=len(prompt),
            image_bytes=0 if image is None else len(image),
        )
        log_request(
            "http",
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": "Bearer <configured>",
                "Content-Type": "application/json",
            },
            body={"model": self.model, "messages": [{"role": "user", "content": content}]},
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
            )
            message = response.choices[0].message.content
            log_response(
                "http",
                target=f"{self.base_url}/chat/completions",
                body={"model": getattr(response, "model", self.model), "content": message},
            )
            log_result(
                "llm",
                {"model": getattr(response, "model", self.model), "content": message},
            )
        except Exception as exc:
            raise ModelError(f"LLM request failed: {exc}") from exc
        if not message:
            raise ModelError("LLM returned an empty response")
        return message

    def complete_with_tools(
        self,
        prompt: str,
        *,
        tools: Sequence[Mapping[str, object]],
        image: bytes | None = None,
    ) -> tuple[LlmToolCall, ...]:
        """Return native function/tool calls from an OpenAI-compatible API."""
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )
        request_body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "tools": list(tools),
            "tool_choice": "required",
        }
        log_step(
            "llm",
            model=self.model,
            mode="tool_call",
            tool_count=len(tools),
            prompt_chars=len(prompt),
            image_bytes=0 if image is None else len(image),
        )
        log_request(
            "http",
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": "Bearer <configured>",
                "Content-Type": "application/json",
            },
            body=request_body,
        )
        try:
            response = self._client.chat.completions.create(**request_body)
        except Exception as exc:
            raise ModelError(f"LLM tool-call request failed: {exc}") from exc

        try:
            message = response.choices[0].message
            raw_calls = _field(message, "tool_calls", ()) or ()
            calls = tuple(_parse_tool_call(call) for call in raw_calls)
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError(f"LLM returned invalid tool calls: {exc}") from exc

        log_response(
            "http",
            target=f"{self.base_url}/chat/completions",
            body={
                "model": _field(response, "model", self.model),
                "content": _field(message, "content"),
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "argument_keys": sorted(call.arguments),
                    }
                    for call in calls
                ],
            },
        )
        log_result(
            "llm",
            {
                "model": _field(response, "model", self.model),
                "content": _field(message, "content"),
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in calls
                ],
            },
        )
        if not calls:
            raise ModelError("LLM returned no tool calls")
        return calls


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _parse_tool_call(value: Any) -> LlmToolCall:
    call_id = _field(value, "id", "") or ""
    function = _field(value, "function")
    name = _field(function, "name")
    arguments = _field(function, "arguments", {})
    if not isinstance(name, str) or not name.strip():
        raise ModelError("LLM returned a tool call without a function name")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ModelError(f"LLM returned invalid arguments for tool {name!r}: {exc}") from exc
    if not isinstance(arguments, Mapping):
        raise ModelError(f"LLM tool {name!r} arguments must be a JSON object")
    return LlmToolCall(
        name=name.strip(),
        arguments=dict(arguments),
        id=str(call_id),
    )
