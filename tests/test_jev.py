from __future__ import annotations

import json
from typing import Any

import pytest

from nier.config import from_mapping
from nier.errors import ConfigurationError
from nier.models import jev as jev_module
from nier.models.base import BoundingBox, TextSpan
from nier.models.jev import JevAnswer, JevDecisionProvider, JevProvider


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_jev_choice_posts_typed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "model": "jev-latest",
                "answers": {
                    "target": {
                        "type": "choice",
                        "choice": "settings",
                        "confidence": 0.92,
                        "probabilities": {"settings": 0.92, "help": 0.08},
                    }
                },
            }
        )

    monkeypatch.setattr(jev_module.urllib_request, "urlopen", fake_urlopen)
    client = JevProvider(api_key="secret", timeout=12)

    answer = client.choice(
        {"screen": "settings"},
        ["settings", "help"],
        instructions="Choose the settings target",
        question_id="target",
    )

    request = captured["request"]
    body = json.loads(request.data)
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == "Bearer secret"
    assert captured["timeout"] == 12
    assert body["model"] == "jev-latest"
    assert body["questions"]["target"] == {
        "type": "choice",
        "instructions": "Choose the settings target",
        "criteria": {"settings": "settings", "help": "help"},
    }
    assert answer.choice == "settings"
    assert answer.selected_probability == 0.92


def test_jev_supports_score_and_noul_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "answers": {
                    "severity": {"type": "score", "score": 2, "confidence": 0.8},
                    "urgent": {"type": "noul", "noul": 1.0},
                }
            }
        )

    monkeypatch.setattr(jev_module.urllib_request, "urlopen", fake_urlopen)
    client = JevProvider(api_key="secret")

    response = client.ask(
        "an error message",
        {
            "severity": {
                "type": "score",
                "instructions": "Rate severity",
                "criteria": ["low", "high"],
            },
            "urgent": {
                "type": "noul",
                "instructions": "Is this urgent?",
            },
        },
    )

    assert response.answer("severity").score == 2.0
    assert response.answer("urgent").noul == 1.0


def test_missing_jev_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_NIER_JEV_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="TEST_NIER_JEV_KEY"):
        JevProvider(api_key_env="TEST_NIER_JEV_KEY")


def test_jev_decision_provider_maps_selected_span_to_coordinates() -> None:
    class FakeJev:
        def choice(self, state, options, *, instructions, question_id):
            assert state["spans"][0]["text"] == "Settings"
            assert options == ["noop", "span_0"]
            return JevAnswer(type="choice", choice="span_0", confidence=0.91)

    decision = JevDecisionProvider(FakeJev(), confidence_threshold=0.8).decide(
        [
            TextSpan(
                text="Settings",
                confidence=0.98,
                box=BoundingBox(left=10, top=20, right=110, bottom=60),
            )
        ],
        "open Settings",
    )

    assert decision.action == "tap"
    assert decision.point == (60, 40)
    assert decision.confidence == 0.91


def test_jev_config_is_optional_but_explicit_singular_config_is_named_default() -> None:
    assert from_mapping({}).models.jev_providers == {}
    config = from_mapping({"models": {"jev": {"model": "test-model"}}})
    assert config.models.jev.model == "test-model"
    assert config.models.jev_providers["default"].model == "test-model"
