from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nier import Device
from nier.jev_goal import JevGoal
from nier.models.base import BoundingBox, TextSpan
from nier.models.jev import JevAnswer, JevResponse
from nier.protocol import (
    Action,
    ActionResult,
    ActivityInfo,
    Capabilities,
    Click,
    DumpUiRequest,
    ImageFormat,
    KeyCode,
    Screenshot,
    UiDump,
    UiSource,
)
from nier.session import DeviceSession


@dataclass
class FakeBackend:
    actions: list[Action] = field(default_factory=list)
    opened_apps: list[str] = field(default_factory=list)
    dump_ui_requests: list[DumpUiRequest | None] = field(default_factory=list)

    def health(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("v1", "fake", "fake", 100, 200, False, False, True, False)

    def execute(self, action: Action) -> ActionResult:
        self.actions.append(action)
        return ActionResult(True, "ok")

    def open_app(self, package: str) -> ActionResult:
        self.opened_apps.append(package)
        return ActionResult(True, "opened")

    def screenshot(self, request=None) -> Screenshot:
        return Screenshot(b"image", ImageFormat.PNG, 100, 200, "digest")

    def dump_ui(self, request=None) -> UiDump:
        self.dump_ui_requests.append(request)
        return UiDump(
            '<hierarchy><node text="登录" resource-id="app:id/login" '
            'bounds="[10,20][30,40]" clickable="true" /></hierarchy>',
            UiSource.UIAUTOMATOR,
        )

    def current_activity(self) -> ActivityInfo:
        return ActivityInfo(
            package="com.android.settings",
            activity="com.android.settings.Settings",
            component="com.android.settings/com.android.settings.Settings",
            source="resumed_activity",
        )

    def close(self) -> None:
        pass


class FakeJev:
    def __init__(self, responses: list[JevResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[object, object]] = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        return self.responses.pop(0)


class FakeLlm:
    def __init__(self, guidance: str) -> None:
        self.guidance = guidance
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, image: bytes | None = None) -> str:
        self.prompts.append(prompt)
        return self.guidance


class FakeOcr:
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: bytes) -> list[TextSpan]:
        self.calls += 1
        return [
            TextSpan(
                text="OCR-only",
                confidence=0.99,
                box=BoundingBox(left=20, top=30, right=60, bottom=90),
            )
        ]


def _response(*, done: float, choice: str, confidence: float = 0.95, progress=None) -> JevResponse:
    answers = {
        "done": JevAnswer(type="noul", noul=done),
        "next": JevAnswer(
            type="choice",
            choice=choice,
            confidence=confidence,
            probabilities={choice: confidence, "none": 1.0 - confidence},
        ),
    }
    if progress is not None:
        answers["progress"] = JevAnswer(type="score", score=progress)
    return JevResponse(answers=answers, model="jev-test")


def make_device() -> tuple[Device, FakeBackend]:
    backend = FakeBackend()
    return Device(DeviceSession(backend)), backend


def test_jev_goal_selects_host_validated_ui_candidate_and_reobserves() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="none", confidence=0.10),
        ]
    )

    result = phone.run_jev_goal("点击登录", jev=jev, max_steps=2)

    assert result.success is True
    assert result.termination == "needs_verification"
    assert result.completed_steps == 1
    assert len(jev.calls) == 2
    first_state, first_questions = jev.calls[0]
    assert first_state["goal"] == "点击登录"
    assert first_state["activity"]["component"] == "com.android.settings/com.android.settings.Settings"  # type: ignore[index]
    assert first_state["candidates"][0]["id"] == "ui_0"  # type: ignore[index]
    assert first_state["candidates"][0]["source"] == "ui"  # type: ignore[index]
    assert "action" not in first_state["candidates"][0]  # type: ignore[index]
    assert not {"bounds", "center", "box", "x", "y", "width", "height"} & set(
        first_state["candidates"][0]["metadata"]  # type: ignore[index]
    )
    assert set(first_questions) == {"done", "next"}
    assert "inspect_ocr" not in first_questions["next"].options  # type: ignore[index,operator]
    assert result.plan.jev["done"] == 0.96  # type: ignore[index]
    assert len(backend.actions) == 1
    assert len(backend.dump_ui_requests) == 3


def test_device_run_uses_jev_and_llm_only_for_directional_assistance() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="call_llm"),
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )
    llm = FakeLlm("先检查当前页面中的登录入口，再判断是否需要打开设置。")

    result = phone.run("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.success is True
    assert result.termination == "needs_verification"
    assert len(backend.actions) == 1
    assert len(llm.prompts) == 1
    assert "Do not return an action, tool call" in llm.prompts[0]
    assert "[10,20]" not in llm.prompts[0]
    first_state, first_questions = jev.calls[0]
    assert "call_llm" in first_questions["next"].options  # type: ignore[index,operator]
    second_state, _ = jev.calls[1]
    assert second_state["llm_guidance"] == llm.guidance
    assert second_state["llm_assists_used"] == 1
    assert result.plan.jev["llm_assists"] == [  # type: ignore[index]
        {
            "iteration": 1,
            "provider": "custom",
            "guidance": llm.guidance,
        }
    ]


def test_jev_goal_removes_call_llm_after_assist_limit() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="call_llm"),
            _response(done=0.10, choice="call_llm"),
        ]
    )
    llm = FakeLlm("换一个页面入口继续查找。")

    result = phone.run(
        "进入登录页面",
        jev=jev,
        llm=llm,
        max_llm_assists=1,
    )

    assert result.success is False
    assert result.termination == "blocked"
    assert len(llm.prompts) == 1
    assert "call_llm" in jev.calls[0][1]["next"].options  # type: ignore[index,operator]
    assert "call_llm" not in jev.calls[1][1]["next"].options  # type: ignore[index,operator]
    assert backend.actions == []


def test_jev_goal_runs_ocr_only_after_jev_requests_it() -> None:
    phone, backend = make_device()
    ocr = FakeOcr()
    jev = FakeJev(
        [
            _response(done=0.10, choice="inspect_ocr"),
            _response(done=0.10, choice="ocr_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )

    result = JevGoal(
        phone,
        jev,
        ocr=ocr,
        allowed_controls=("OCR-only",),
        max_steps=1,
    ).run("点击图像文字")

    assert result.success is True
    assert result.termination == "needs_verification"
    assert ocr.calls == 1
    assert len(jev.calls) == 3
    initial_state, initial_questions = jev.calls[0]
    assert initial_state["ocr_available"] is True
    assert initial_state["ocr_inspected"] is False
    assert initial_state["ocr"] == []
    assert "inspect_ocr" in initial_questions["next"].options  # type: ignore[index,operator]
    ocr_state, ocr_questions = jev.calls[1]
    assert ocr_state["ocr_inspected"] is True
    assert ocr_state["ocr"][0]["text"] == "OCR-only"  # type: ignore[index]
    assert "inspect_ocr" not in ocr_questions["next"].options  # type: ignore[index,operator]
    assert isinstance(backend.actions[0], Click)
    assert backend.actions[0].point.x == 40  # type: ignore[union-attr]


def test_jev_goal_skips_ocr_when_ui_candidate_is_sufficient() -> None:
    phone, _ = make_device()
    ocr = FakeOcr()
    jev = FakeJev(
        [
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )

    JevGoal(phone, jev, ocr=ocr, max_steps=1).run("点击登录")

    assert ocr.calls == 0
    initial_state, initial_questions = jev.calls[0]
    assert initial_state["ocr"] == []
    assert initial_state["ocr_inspected"] is False
    assert "inspect_ocr" in initial_questions["next"].options  # type: ignore[index,operator]


def test_jev_goal_preview_uses_one_dump_and_can_skip_webview() -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.10, choice="ui_0")])

    result = phone.run_jev_goal(
        "点击登录",
        jev=jev,
        prefer_webview=False,
        dry_run=True,
    )

    assert result.success is True
    assert result.termination == "next_action_preview"
    assert backend.dump_ui_requests == [DumpUiRequest(prefer_webview=False)]


def test_jev_goal_dispatches_fixed_back_candidate_as_key() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="back"),
            _response(done=0.96, choice="blocked", confidence=0.95),
        ]
    )

    result = phone.run_jev_goal(
        "返回上一页",
        jev=jev,
        allowed_controls=("返回上一页",),
        max_steps=1,
    )

    assert result.success is True
    assert result.termination == "needs_verification"
    assert len(backend.actions) == 1
    assert backend.actions[0].key_code == KeyCode.BACK  # type: ignore[union-attr]


def test_jev_goal_launches_only_an_explicitly_allowlisted_app() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="app_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )

    result = phone.run_jev_goal(
        "打开阅读器",
        jev=jev,
        allowed_apps={"阅读器": "com.example.reader"},
        max_steps=1,
    )

    assert result.success is True
    assert backend.opened_apps == ["com.example.reader"]
    state, questions = jev.calls[0]
    app_candidate = next(
        item for item in state["candidates"] if item["source"] == "app"  # type: ignore[index]
    )
    assert app_candidate == {
        "id": "app_0",
        "label": "打开应用：阅读器",
        "source": "app",
        "metadata": {"kind": "app"},
    }
    assert "com.example.reader" not in repr(state)
    assert "action" not in app_candidate
    assert questions["next"].options["app_0"] == "打开应用：阅读器"  # type: ignore[index]


def test_jev_goal_rejects_invalid_allowlisted_app_package() -> None:
    phone, _backend = make_device()
    jev = FakeJev([])

    with pytest.raises(ValueError, match="invalid package in allowed_apps"):
        JevGoal(phone, jev, allowed_apps={"阅读器": "not a package"})


def test_jev_goal_score_is_optional_progress_telemetry() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.96, choice="none", confidence=0.10, progress=3.0),
        ]
    )

    result = phone.run_jev_goal("检查当前页面", jev=jev, use_score=True, dry_run=True)

    assert result.success is True
    assert result.plan.jev["progress"] == 3.0  # type: ignore[index]
    assert set(jev.calls[0][1]) == {"done", "next", "progress"}
    assert len(backend.dump_ui_requests) == 1


def test_jev_goal_does_not_dispatch_low_confidence_or_unknown_choice() -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.10, choice="unknown", confidence=0.99)])

    result = phone.run_jev_goal("点击登录", jev=jev, dry_run=True)

    assert result.success is False
    assert result.termination == "blocked"
    assert backend.actions == []
    assert len(backend.dump_ui_requests) == 1
