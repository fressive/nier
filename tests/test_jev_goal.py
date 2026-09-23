from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nier import Device
from nier.errors import ModelError
from nier.jev_goal import JevGoal
from nier.models.base import BoundingBox, LlmToolCall, TextSpan
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
    Swipe,
    UiDump,
    UiSource,
)
from nier.session import DeviceSession


@dataclass
class FakeBackend:
    actions: list[Action] = field(default_factory=list)
    action_results: list[ActionResult] = field(default_factory=list)
    action_errors: list[Exception] = field(default_factory=list)
    opened_apps: list[str] = field(default_factory=list)
    dump_ui_requests: list[DumpUiRequest | None] = field(default_factory=list)

    def health(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("v1", "fake", "fake", 100, 200, False, False, True, False)

    def execute(self, action: Action) -> ActionResult:
        self.actions.append(action)
        if self.action_errors:
            raise self.action_errors.pop(0)
        if self.action_results:
            return self.action_results.pop(0)
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
    def __init__(
        self,
        guidance: str | list[str],
        *,
        tool_responses: list[list[LlmToolCall]] | None = None,
    ) -> None:
        self.responses = guidance if isinstance(guidance, list) else [guidance]
        self.prompts: list[str] = []
        self.tool_responses = list(tool_responses or [])
        self.tool_prompts: list[str] = []
        self.tool_history: list[object] = []

    def complete(self, prompt: str, *, image: bytes | None = None) -> str:
        self.prompts.append(prompt)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    def complete_with_tools(self, prompt: str, *, tools, image: bytes | None = None):
        self.tool_prompts.append(prompt)
        self.tool_history.append(tools)
        if self.tool_responses:
            return self.tool_responses.pop(0)
        return [tool("recovery_failed", reason="no recovery tool response configured")]


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


def tool(name: str, **arguments: object) -> LlmToolCall:
    return LlmToolCall(name=name, arguments=arguments)


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


def test_jev_goal_scrolls_within_observed_viewport() -> None:
    phone, backend = make_device()
    backend.dump_ui = lambda request=None: UiDump(  # type: ignore[method-assign]
        '<hierarchy><node class="android.widget.ScrollView" '
        'bounds="[10,20][90,180]" scrollable="true" /></hierarchy>',
        UiSource.UIAUTOMATOR,
    )
    jev = FakeJev([
        _response(done=0.1, choice="scroll_0"),
        _response(done=0.96, choice="blocked"),
    ])

    result = phone.run_jev_goal("查找关于本机", jev=jev, max_steps=2)

    assert result.termination == "needs_verification"
    assert isinstance(backend.actions[0], Swipe)
    assert [(point.x, point.y) for point in backend.actions[0].points] == [
        (50, 148), (50, 52)
    ]
    candidate = next(
        item for item in jev.calls[0][0]["candidates"]  # type: ignore[index]
        if item["source"] == "scroll"
    )
    assert candidate["label"] == "向下滚动当前列表"
    assert candidate["source"] == "scroll"
    assert candidate["metadata"] == {"direction": "down"}
    assert "points" not in candidate


def test_unavailable_ocr_falls_back_to_ui_candidates() -> None:
    phone, backend = make_device()
    jev = FakeJev([
        _response(done=0.1, choice="inspect_ocr"),
        _response(done=0.1, choice="ui_0"),
    ])

    class BrokenOcr:
        def recognize(self, image: bytes):
            raise ModelError("PaddleOCR is not installed")

    result = JevGoal(phone, jev, ocr=BrokenOcr()).run("点击登录", dry_run=True)

    assert result.termination == "next_action_preview"
    assert result.plan.steps[0].action == "tap"
    state, questions = jev.calls[1]
    assert state["ocr_available"] is False
    assert "PaddleOCR is not installed" in state["ocr_error"]
    assert "inspect_ocr" not in questions["next"].options
    assert backend.actions == []


def test_jev_goal_scroll_respects_control_allowlist() -> None:
    phone, backend = make_device()
    backend.dump_ui = lambda request=None: UiDump(  # type: ignore[method-assign]
        '<hierarchy><node bounds="[10,20][90,180]" scrollable="true" /></hierarchy>',
        UiSource.UIAUTOMATOR,
    )
    jev = FakeJev([_response(done=0.1, choice="blocked")])

    result = phone.run_jev_goal(
        "查找关于本机", jev=jev, dry_run=True, allowed_controls=("关于本机",)
    )

    assert result.termination == "blocked"
    assert not any(
        candidate["source"] == "scroll"
        for candidate in jev.calls[0][0]["candidates"]  # type: ignore[index]
    )


def test_jev_goal_prefers_visible_goal_target_and_ignores_tiny_nodes() -> None:
    phone, backend = make_device()
    backend.dump_ui = lambda request=None: UiDump(  # type: ignore[method-assign]
        '<hierarchy><node bounds="[0,0][100,200]" scrollable="true">'
        '<node text="设置" bounds="[10,20][60,70]" clickable="true" />'
        '<node text="搜索设置项" bounds="[0,100][100,102]" clickable="true" />'
        '</node></hierarchy>',
        UiSource.UIAUTOMATOR,
    )
    jev = FakeJev([_response(done=0.1, choice="ui_0")])

    result = phone.run_jev_goal("打开设置", jev=jev, dry_run=True)

    assert result.termination == "next_action_preview"
    assert [item["label"] for item in jev.calls[0][0]["candidates"]] == [  # type: ignore[index]
        "设置", "返回上一页"
    ]


def test_device_run_lets_llm_execute_safe_recovery_actions() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="call_llm"),
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[
            [tool("recovery_action", candidate_id="back")],
            [tool("recovery_complete", reason="已回到稳定页面")],
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.success is True
    assert result.termination == "needs_verification"
    assert len(backend.actions) == 2
    assert backend.actions[0].key_code == KeyCode.BACK  # type: ignore[union-attr]
    assert isinstance(backend.actions[1], Click)
    assert len(llm.prompts) == 1
    assert "Return exactly one concise imperative subgoal" in llm.prompts[0]
    assert "Original main goal" in llm.prompts[0]
    assert "[10,20]" not in llm.prompts[0]
    first_state, first_questions = jev.calls[0]
    assert first_state["goal"] == "进入登录页面"
    assert "call_llm" in first_questions["next"].options  # type: ignore[index,operator]
    resumed_state, _ = jev.calls[1]
    assert resumed_state["goal"] == "进入登录页面"
    assert "llm_guidance" not in resumed_state
    assert resumed_state["history"][-1]["decision"] == "recovery_subgoal"  # type: ignore[index]
    assert result.plan.jev["recovery_subgoals"][0]["outcome"] == "completed"  # type: ignore[index]
    assert len(jev.calls) == 3
    assert len(llm.tool_prompts) == 2
    action_tool = llm.tool_history[0][0]["function"]  # type: ignore[index]
    assert action_tool["name"] == "recovery_action"
    assert action_tool["parameters"]["properties"]["candidate_id"]["enum"] == ["back"]
    assert "Never request or perform text entry" in llm.tool_prompts[0]


def test_jev_goal_removes_call_llm_after_assist_limit() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="call_llm"),
            _response(done=0.10, choice="call_llm"),
        ]
    )
    llm = FakeLlm("换一个页面入口继续查找。")

    result = phone.run_jev_goal(
        "进入登录页面",
        jev=jev,
        llm=llm,
        max_llm_assists=1,
    )

    assert result.success is False
    assert result.termination == "recovery_failed"
    assert len(llm.prompts) == 1
    assert "call_llm" in jev.calls[0][1]["next"].options  # type: ignore[index,operator]
    assert len(jev.calls) == 1
    assert backend.actions == []


def test_llm_recovery_action_cannot_select_a_non_allowlisted_control() -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.10, choice="call_llm")])
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[
            [tool("recovery_action", candidate_id="ui_0")],
            [tool("recovery_action", candidate_id="ui_0")],
            [tool("recovery_action", candidate_id="ui_0")],
        ],
    )

    result = phone.run_jev_goal(
        "进入登录页面",
        jev=jev,
        llm=llm,
        max_llm_assists=1,
    )

    assert result.termination == "recovery_failed"
    assert backend.actions == []
    assert len(llm.tool_prompts) == 3
    allowed_ids = llm.tool_history[0][0]["function"]["parameters"]["properties"]["candidate_id"]["enum"]  # type: ignore[index]
    assert allowed_ids == ["back"]
    assert result.plan.jev["recovery_subgoals"][0]["failed_control"] is None  # type: ignore[index]


def test_failed_llm_recovery_action_is_not_retried() -> None:
    phone, backend = make_device()
    backend.action_results = [ActionResult(False, "back failed")]
    jev = FakeJev([_response(done=0.10, choice="call_llm")])
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[[tool("recovery_action", candidate_id="back")]],
    )

    result = phone.run_jev_goal(
        "进入登录页面",
        jev=jev,
        llm=llm,
        max_llm_assists=1,
    )

    assert result.termination == "recovery_failed"
    assert len(backend.actions) == 1
    assert backend.actions[0].key_code == KeyCode.BACK  # type: ignore[union-attr]
    attempt = result.plan.jev["recovery_subgoals"][0]  # type: ignore[index]
    assert attempt["failed_control"] == "返回上一页"
    assert attempt["error"] == "back failed"


def test_jev_goal_default_allows_more_than_two_llm_assists() -> None:
    phone, _ = make_device()
    responses = []
    for _ in range(3):
        responses.append(_response(done=0.10, choice="call_llm"))
    responses.append(_response(done=0.96, choice="blocked"))
    jev = FakeJev(responses)
    llm = FakeLlm(
        ["返回上一页"] * 3,
        tool_responses=[
            [tool("recovery_complete", reason="无需额外操作")],
            [tool("recovery_complete", reason="无需额外操作")],
            [tool("recovery_complete", reason="无需额外操作")],
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.success is True
    assert result.termination == "needs_verification"
    assert len(llm.prompts) == 3
    for index in (0, 1, 2):
        _, questions = jev.calls[index]
        assert "call_llm" in questions["next"].options  # type: ignore[index,operator]


def test_repeated_completed_recovery_on_same_screen_stops() -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.1, choice="call_llm")] * 4)
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[[tool("recovery_complete", reason="完成")] for _ in range(3)],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.termination == "recovery_failed"
    assert len(llm.prompts) == 3
    assert backend.actions == []


def test_repeated_failed_recovery_on_same_screen_stops() -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.1, choice="call_llm")])
    llm = FakeLlm(
        ["关闭弹窗", "返回上一页", "等待界面恢复"],
        tool_responses=[
            [tool("recovery_failed", reason="没有合适控件")]
            for _ in range(3)
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.termination == "recovery_failed"
    assert len(llm.prompts) == 3
    assert backend.actions == []


def test_failed_recovery_subgoal_causes_llm_to_generate_return_subgoal() -> None:
    phone, backend = make_device()
    jev = FakeJev(
        [
            _response(done=0.10, choice="call_llm"),
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )
    llm = FakeLlm(
        ["关闭弹窗", "返回上一页"],
        tool_responses=[
            [tool("recovery_failed", reason="没有可用的关闭控件")],
            [tool("recovery_action", candidate_id="back")],
            [tool("recovery_complete", reason="已恢复")],
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=1)

    assert result.success is True
    assert len(llm.prompts) == 2
    assert "关闭弹窗" in llm.prompts[1]
    assert "from which the original main goal can resume" in llm.prompts[1]
    assert len(jev.calls) == 3
    assert jev.calls[1][0]["goal"] == "进入登录页面"
    assert [action.key_code for action in backend.actions if hasattr(action, "key_code")] == [
        KeyCode.BACK
    ]
    assert len(backend.actions) == 2
    attempts = result.plan.jev["recovery_subgoals"]  # type: ignore[index]
    assert [item["outcome"] for item in attempts] == ["failed", "completed"]  # type: ignore[index]


def test_failed_main_action_is_not_retried_after_recovery() -> None:
    phone, backend = make_device()
    backend.action_results = [ActionResult(False, "device rejected click")]
    jev = FakeJev(
        [
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[
            [tool("recovery_action", candidate_id="back")],
            [tool("recovery_complete", reason="已恢复")],
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=2)

    assert result.success is True
    assert len(llm.prompts) == 1
    assert "device rejected click" in llm.prompts[0]
    assert len(backend.actions) == 2
    assert sum(isinstance(action, Click) for action in backend.actions) == 1
    assert backend.actions[-1].key_code == KeyCode.BACK  # type: ignore[union-attr]
    resumed_state, _ = jev.calls[-1]
    assert resumed_state["goal"] == "进入登录页面"
    assert [item["label"] for item in resumed_state["candidates"]] == [  # type: ignore[index]
        "返回上一页"
    ]


def test_action_exception_uses_recovery_subgoal_before_resuming_main_goal() -> None:
    phone, backend = make_device()
    backend.action_errors = [RuntimeError("dispatch connection dropped")]
    jev = FakeJev(
        [
            _response(done=0.10, choice="ui_0"),
            _response(done=0.96, choice="blocked"),
        ]
    )
    llm = FakeLlm(
        "返回上一页",
        tool_responses=[
            [tool("recovery_action", candidate_id="back")],
            [tool("recovery_complete", reason="已恢复")],
        ],
    )

    result = phone.run_jev_goal("进入登录页面", jev=jev, llm=llm, max_steps=2)

    assert result.success is True
    assert len(backend.actions) == 2
    assert isinstance(backend.actions[0], Click)
    assert backend.actions[1].key_code == KeyCode.BACK  # type: ignore[union-attr]
    assert "dispatch connection dropped" in llm.prompts[0]
    assert result.plan.jev["recovery_subgoals"][0]["outcome"] == "completed"  # type: ignore[index]


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


@pytest.mark.parametrize("entry_point", ("run", "run_jev_goal"))
def test_goal_entry_points_have_no_main_deadline_by_default(
    monkeypatch,
    entry_point: str,
) -> None:
    phone, backend = make_device()
    jev = FakeJev([_response(done=0.10, choice="ui_0")])
    calls = 0

    def expired_clock() -> float:
        nonlocal calls
        calls += 1
        return 0.0 if calls == 1 else 100.0

    monkeypatch.setattr("nier.jev_goal.monotonic", expired_clock)

    result = getattr(phone, entry_point)("点击登录", jev=jev, dry_run=True)

    assert result.termination == "next_action_preview"
    assert backend.actions == []


def test_device_run_accepts_an_explicit_sixty_second_deadline(monkeypatch) -> None:
    phone, backend = make_device()
    jev = FakeJev([])
    clock_values = iter((0.0, 60.0))
    monkeypatch.setattr("nier.jev_goal.monotonic", lambda: next(clock_values))

    result = phone.run(
        "点击登录",
        jev=jev,
        dry_run=True,
        max_seconds=60,
    )

    assert result.termination == "time_limit"
    assert jev.calls == []
    assert backend.actions == []


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
