from __future__ import annotations

from types import SimpleNamespace

from nier.models.llm import OpenAICompatibleProvider


def test_openai_compatible_provider_returns_native_tool_calls() -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="planner-test",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="tap",
                                        arguments='{"x": 10, "y": 20}',
                                    ),
                                )
                            ],
                        )
                    )
                ],
            )

    provider = object.__new__(OpenAICompatibleProvider)
    provider.base_url = "http://llm.example.test/v1"
    provider.model = "planner"
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    calls = provider.complete_with_tools(
        "tap the login button",
        tools=[{"type": "function", "function": {"name": "tap"}}],
        image=b"image",
    )

    assert len(calls) == 1
    assert calls[0].name == "tap"
    assert calls[0].id == "call_1"
    assert calls[0].arguments == {"x": 10, "y": 20}
    assert captured["tool_choice"] == "required"
    assert captured["tools"] == [{"type": "function", "function": {"name": "tap"}}]
    assert captured["messages"][0]["content"][1]["type"] == "image_url"  # type: ignore[index]
