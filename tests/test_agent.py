from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nier import Device
from nier.agent import Agent
from nier.errors import ModelError
from nier.models.base import BoundingBox, LlmToolCall, TextSpan
from nier.models.jev import JevAnswer, JevResponse
from nier.protocol import (
    Action,
    ActionResult,
    ActivityInfo,
    Capabilities,
    Click,
    ImageFormat,
    InputText,
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
    started_activities: list[tuple[str, str]] = field(default_factory=list)

    def health(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("v1", "fake", "fake", 100, 200, False, False, True, False)

    def execute(self, action: Action) -> ActionResult:
        self.actions.append(action)
        return ActionResult(True, "ok")

    def screenshot(self, request=None) -> Screenshot:
        return Screenshot(b"image", ImageFormat.PNG, 100, 200, "digest")

    def dump_ui(self, request=None) -> UiDump:
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

    def list_apps(self) -> list[str]:
        return ["com.example.app", "com.android.settings"]

    def list_app_activities(self, package: str) -> list[str]:
        return [f"{package}.MainActivity", f"{package}.SettingsActivity"]

    def open_app(self, package: str) -> ActionResult:
        self.opened_apps.append(package)
        return ActionResult(True, f"opened {package}")

    def start_activity(self, package: str, activity: str) -> ActionResult:
        self.started_activities.append((package, activity))
        return ActionResult(True, f"started {package}/{activity}")

    def close(self) -> None:
        pass


class FakeLlm:
    def __init__(
        self,
        tool_calls: list[LlmToolCall],
        *,
        responses: list[list[LlmToolCall]] | None = None,
    ) -> None:
        self.responses = [tuple(item) for item in (responses or [tool_calls])]
        self.tool_calls = tuple(tool_calls)
        self.prompt = ""
        self.prompts: list[str] = []
        self.image = None
        self.tools = ()
        self.tool_history = []

    def complete_with_tools(self, prompt: str, *, tools, image: bytes | None = None):
        self.prompt = prompt
        self.prompts.append(prompt)
        self.image = image
        self.tools = tools
        self.tool_history.append(tools)
        self.tool_calls = self.responses.pop(0)
        return self.tool_calls


class FakeOcr:
    def recognize(self, image: bytes) -> list[TextSpan]:
        return [
            TextSpan(
                text="登录",
                confidence=0.98,
                box=BoundingBox(left=10, top=20, right=50, bottom=60),
            )
        ]


class FakeJev:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        answers = {
            "ready": JevAnswer(type="noul", noul=0.96),
        }
        if "target" in questions:
            answers["target"] = JevAnswer(
                type="choice",
                choice="span_0",
                confidence=0.91,
                probabilities={"span_0": 0.91, "none": 0.09},
            )
        return JevResponse(answers=answers, model="jev-test")


def make_device() -> tuple[Device, FakeBackend]:
    backend = FakeBackend()
    return Device(DeviceSession(backend)), backend


def tool(name: str, **arguments: object) -> LlmToolCall:
    return LlmToolCall(name=name, arguments=arguments)


def test_agent_compiles_natural_language_to_recorded_actions() -> None:
    phone, backend = make_device()
    llm = FakeLlm(
        [],
        responses=[
            [tool("tap", x=20, y=30, reason="login button")],
            [tool("text", text="rina")],
            [tool("key", key="enter")],
            [tool("goal_complete", reason="login complete")],
        ],
    )

    result = phone.run("登录并输入 rina", llm=llm)

    assert result.success is True
    assert result.completed_steps == 3
    assert isinstance(backend.actions[0], Click)
    assert backend.actions[0].point.x == 20  # type: ignore[union-attr]
    assert backend.actions[1] == InputText("rina")
    assert llm.image == b"image"
    assert "登录并输入 rina" in llm.prompt
    assert "Return exactly ONE tool call" in llm.prompt
    assert "com.android.settings/com.android.settings.Settings" in llm.prompt
    assert {item["function"]["name"] for item in llm.tools} >= {
        "tap",
        "text",
        "key",
        "goal_complete",
        "goal_failed",
    }
    assert "no_action" not in {item["function"]["name"] for item in llm.tools}
    assert "Structured UI elements" in llm.prompt
    assert "app:id/login" in llm.prompt
    assert any(record.operation == "agent" and record.success for record in phone.session.recorder.records)


def test_agent_can_query_apps_and_start_an_activity() -> None:
    phone, backend = make_device()
    llm = FakeLlm(
        [],
        responses=[
            [tool("list_apps")],
            [tool("list_app_activities", package="com.example.app")],
            [tool("start_activity", package="com.example.app", activity=".MainActivity")],
            [tool("goal_complete", reason="目标 Activity 已打开")],
        ],
    )

    result = phone.run("打开示例应用的主页面", llm=llm, max_steps=4)

    assert result.success is True
    assert [step.action for step in result.plan.steps] == [
        "list_apps",
        "list_app_activities",
        "start_activity",
    ]
    assert "com.example.app" in llm.prompts[1]
    assert "MainActivity" in llm.prompts[2]
    assert backend.started_activities == [
        ("com.example.app", "com.example.app/com.example.app.MainActivity")
    ]
    tool_names = {item["function"]["name"] for item in llm.tools}
    assert {
        "list_apps",
        "list_app_activities",
        "open_app",
        "start_activity",
    } <= tool_names


def test_agent_dry_run_previews_the_next_goal_action() -> None:
    phone, backend = make_device()
    llm = FakeLlm([tool("tap", x=0.5, y=0.5, normalized=True)])

    result = phone.run("点击中心", llm=llm, dry_run=True)

    assert result.plan.steps[0].action == "tap"
    assert result.dry_run is True
    assert result.success is True
    assert result.termination == "next_action_preview"
    assert backend.actions == []


def test_agent_can_call_jev_for_typed_planning_context() -> None:
    phone, _ = make_device()
    llm = FakeLlm([tool("tap", x=30, y=40)])
    jev = FakeJev()

    result = Agent(phone, llm, ocr=FakeOcr(), jev=jev).run("点击登录", dry_run=True)
    plan = result.plan

    assert len(jev.calls) == 1
    state, questions = jev.calls[0]
    assert state["goal"] == "点击登录"
    assert state["activity"]["component"] == "com.android.settings/com.android.settings.Settings"  # type: ignore[index]
    assert state["ui"]["root"]["children"][0]["resource_id"] == "app:id/login"  # type: ignore[index]
    ui_node = state["ui"]["root"]["children"][0]  # type: ignore[index]
    assert not {"bounds", "center", "box", "x", "y", "width", "height"} & set(ui_node)
    assert "screen" not in state
    assert set(state["ocr"][0]) == {"id", "text", "confidence"}  # type: ignore[index]
    assert state["ui_summary"]
    assert set(questions) == {"ready", "target"}
    assert plan.jev == {
        "ready": 0.96,
        "target": "span_0",
        "target_confidence": 0.91,
        "target_probabilities": {"span_0": 0.91, "none": 0.09},
    }
    assert '"target": "span_0"' in llm.prompt


def test_agent_exposes_explicit_jev_call() -> None:
    phone, _ = make_device()
    jev = FakeJev()
    agent = phone.agent(llm=FakeLlm([]), jev=jev)

    response = agent.ask_jev("state", {"ready": {"type": "noul", "instructions": "ready?"}})

    assert response.answer("ready").noul == 0.96


def test_explicit_agent_keeps_direct_jev_as_advisory_context() -> None:
    phone, backend = make_device()
    jev = FakeJev()

    result = phone.agent(
        llm=FakeLlm([tool("goal_complete", reason="当前页面无需操作")]),
        jev=jev,
    ).run(
        "检查当前页面",
        dry_run=True,
    )

    assert result.plan.jev == {"ready": 0.96}
    assert len(jev.calls) == 1
    assert backend.actions == []


def test_agent_rejects_actions_outside_the_allowlist() -> None:
    phone, _ = make_device()
    llm = FakeLlm([tool("shell", command="rm -rf /")])

    with pytest.raises(ModelError, match="unsupported agent action"):
        phone.run("执行命令", llm=llm)


def test_agent_goal_mode_reobserves_after_each_action() -> None:
    phone, backend = make_device()
    llm = FakeLlm(
        [],
        responses=[
            [tool("home", reason="先回到主屏幕")],
            [tool("tap", x=20, y=30, reason="打开设置")],
            [tool("goal_complete", reason="已完成")],
        ],
    )

    result = phone.run(
        "打开设置",
        llm=llm,
        max_steps=3,
    )

    assert result.success is True
    assert result.termination == "goal_complete"
    assert "mode" not in result.to_dict()
    assert [step.action for step in result.plan.steps] == ["home", "tap"]
    assert len(result.results) == 2
    assert len(llm.prompts) == 3
    assert "Completed actions:\n- 1. home" in llm.prompts[1]
    assert "Last action result:" in llm.prompts[1]
    assert len(backend.actions) == 2
    assert any(record.operation == "screenshot" for record in phone.session.recorder.records)
