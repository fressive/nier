from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest

from nier import Device, Widget, WidgetList, connect
from nier.config import from_mapping
from nier.errors import ConfigurationError, ModelError, ProtocolError, UiElementNotFound
from nier.models.base import BoundingBox, LlmToolCall, TextSpan
from nier.models.sysone import SysOneAnswer, SysOneResponse
from nier.protocol import (
    Action,
    ActionResult,
    Capabilities,
    Click,
    DumpUiRequest,
    ImageFormat,
    InputText,
    Key,
    KeyCode,
    Point,
    Screenshot,
    ScreenshotRequest,
    Swipe,
    UiDump,
    UiSource,
)
from nier.session import DeviceSession


@dataclass
class FakeBackend:
    actions: list[Action] = field(default_factory=list)
    screenshot_request: ScreenshotRequest | None = None
    dump_request: DumpUiRequest | None = None
    ui_xml: str = "<hierarchy />"
    closed: bool = False

    def health(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities(
            "v1", "device", "model", 100, 200, False, False, True, False
        )

    def execute(self, action: Action) -> ActionResult:
        self.actions.append(action)
        return ActionResult(True, "ok")

    def screenshot(self, request: ScreenshotRequest | None = None) -> Screenshot:
        self.screenshot_request = request
        image_format = ImageFormat.PNG if request is None else request.format
        return Screenshot(b"image", image_format, 100, 200, "digest")

    def dump_ui(self, request: DumpUiRequest | None = None) -> UiDump:
        self.dump_request = request
        return UiDump(self.ui_xml, UiSource.UIAUTOMATOR)

    def list_apps(self) -> list[str]:
        return ["com.example.one", "com.example.two"]

    def list_app_activities(self, package: str) -> list[str]:
        return [f"{package}.MainActivity"]

    def open_app(self, package: str) -> ActionResult:
        return ActionResult(True, f"opened {package}")

    def start_activity(self, package: str, activity: str) -> ActionResult:
        return ActionResult(True, f"started {package}/{activity}")

    def close(self) -> None:
        self.closed = True


def make_device(backend: FakeBackend | None = None) -> tuple[Device, FakeBackend]:
    backend = backend or FakeBackend()
    return Device(DeviceSession(backend)), backend


def test_public_goal_entry_points_use_llm_and_sysone_names() -> None:
    phone, _ = make_device()

    assert callable(phone.llm)
    assert callable(phone.sysone)
    assert callable(phone.choice)
    assert callable(phone.noul)
    assert callable(phone.score)
    assert callable(phone.widgets)
    widgets = phone.widgets()
    assert isinstance(widgets, WidgetList)
    assert isinstance(widgets[0], Widget)
    assert not hasattr(phone, "run")
    assert not hasattr(phone, "run_jev_goal")
    assert not hasattr(phone, "sysone_provider")


def test_script_actions_build_protocol_actions() -> None:
    phone, backend = make_device()

    phone.click(0.5, 0.25, normalized=True)
    phone.swipe(10, 20, 30, 40, duration_ms=500)
    phone.swipe((0.1, 0.2), (0.8, 0.9), normalized=True)
    phone.text("hello")
    phone.key("back")

    click = backend.actions[0]
    assert isinstance(click, Click)
    assert click.point.normalized is True
    assert backend.actions[1] == Swipe((Point(10, 20), Point(30, 40)), 500)
    swipe = backend.actions[2]
    assert isinstance(swipe, Swipe)
    assert all(point.normalized for point in swipe.points)
    assert backend.actions[3] == InputText("hello")
    assert backend.actions[4] == Key(KeyCode.BACK)


@pytest.mark.parametrize("label", ["登录", re.compile(r"登.*")])
def test_tap_label_supports_exact_text_and_regex(label: str | re.Pattern[str]) -> None:
    backend = FakeBackend(
        ui_xml=(
            '<hierarchy><node text="登录" bounds="[10,20][30,40]" '
            'clickable="true" /></hierarchy>'
        )
    )
    phone, _ = make_device(backend)

    result = phone.tap_label(label)

    assert result.success is True
    assert backend.actions == [Click(Point(20, 30), 80)]
    assert backend.dump_request == DumpUiRequest(prefer_webview=False)


def test_tap_label_regex_matches_a_search_label_with_suffix() -> None:
    backend = FakeBackend(
        ui_xml=(
            '<hierarchy><node text="搜索设置项" bounds="[10,20][30,40]" '
            'clickable="true" /></hierarchy>'
        )
    )
    phone, _ = make_device(backend)

    result = phone.tap_label(re.compile(r"^搜索.*$"))

    assert result.success is True
    assert backend.actions == [Click(Point(20, 30), 80)]


def test_tap_label_raises_when_no_matching_label_exists() -> None:
    phone, backend = make_device()

    with pytest.raises(UiElementNotFound, match="no UI label matches"):
        phone.tap_label("登录")

    assert backend.actions == []


def test_tap_label_can_match_content_description() -> None:
    backend = FakeBackend(
        ui_xml=(
            '<hierarchy><node content-desc="Search button" '
            'bounds="[10,20][30,40]" clickable="true" /></hierarchy>'
        )
    )
    phone, _ = make_device(backend)

    phone.tap_label(re.compile("search", re.IGNORECASE))

    assert backend.actions == [Click(Point(20, 30), 80)]


def test_tap_label_raises_when_matching_node_has_no_bounds() -> None:
    backend = FakeBackend(ui_xml='<hierarchy><node text="登录" /></hierarchy>')
    phone, _ = make_device(backend)

    with pytest.raises(UiElementNotFound, match="no node with screen bounds"):
        phone.tap_label("登录")

    assert backend.actions == []


def test_format_tree_shows_text_and_only_true_boolean_attributes() -> None:
    backend = FakeBackend(
        ui_xml=(
            '<hierarchy><node class="android.widget.Button" text="搜索" '
            'resource-id="com.example:id/search" clickable="true" '
            'enabled="1" selected="false" content-desc="true" /></hierarchy>'
        )
    )
    phone, _ = make_device(backend)
    document = phone.parse_uidump()

    tree = phone.format_tree(document, color=False)

    assert tree == ("hierarchy\n└── node [text='搜索', clickable, enabled]")
    assert "resource-id" not in tree
    assert "selected" not in tree
    assert "content-desc" not in tree
    assert "android.widget.Button" not in tree


def test_format_tree_adds_ansi_color_by_default() -> None:
    phone, _ = make_device(
        FakeBackend(
            ui_xml='<hierarchy><node text="搜索" clickable="true" /></hierarchy>'
        )
    )
    document = phone.parse_uidump()

    colored = phone.format_tree(document.root)
    plain = phone.format_tree(document.root, color=False)

    assert "\x1b[" in colored
    assert "\x1b[" not in plain
    assert "text='搜索'" in plain


def test_device_lists_apps_and_app_activities() -> None:
    phone, _ = make_device()

    assert phone.list_apps() == ["com.example.one", "com.example.two"]
    assert phone.list_app() == ["com.example.one", "com.example.two"]
    assert phone.list_app_activities("com.example.one") == [
        "com.example.one.MainActivity"
    ]
    assert phone.list_app_activity("com.example.one") == [
        "com.example.one.MainActivity"
    ]


def test_device_can_open_apps_and_start_activities() -> None:
    phone, _ = make_device()

    assert phone.open_app("com.example.one").success is True
    assert phone.launch_app("com.example.one").success is True
    assert phone.start_activity("com.example.one", ".MainActivity").success is True
    assert phone.open_activity(
        "com.example.one", "com.example.one.MainActivity"
    ).success is True


def test_screenshot_infers_format_and_writes_file(tmp_path) -> None:
    phone, backend = make_device()
    target = tmp_path / "nested" / "screen.jpg"

    result = phone.screenshot(target, quality=75)

    assert target.read_bytes() == b"image"
    assert result.format is ImageFormat.JPEG
    assert backend.screenshot_request == ScreenshotRequest(
        format=ImageFormat.JPEG,
        quality=75,
    )


def test_screenshot_ocr_is_created_from_configuration_and_cached(monkeypatch) -> None:
    phone, _ = make_device()

    class FakeOcr:
        def __init__(self) -> None:
            self.images: list[bytes] = []
            self.closed = False

        def recognize(self, image: bytes):
            self.images.append(image)
            return [TextSpan("设置", 0.99, BoundingBox(10, 20, 90, 60))]

        def close(self) -> None:
            self.closed = True

    fake = FakeOcr()

    def create(provider: str):
        assert provider == "default"
        return fake

    monkeypatch.setattr(phone, "_configured_ocr", create)

    first = phone.screenshot().ocr()
    second = phone.screenshot().ocr()

    assert first[0].text == "设置"
    assert second[0].box.right == 90
    assert fake.images == [b"image", b"image"]
    assert phone._ocr_cache == {"default": fake}

    phone.close()

    assert fake.closed is True


def test_sysone_is_created_from_configuration_and_cached(monkeypatch) -> None:
    phone, _ = make_device()

    class FakeSysOne:
        def __init__(self) -> None:
            self.closed = False
            self.calls: list[tuple[str, tuple, dict]] = []

        def choice(self, *args, **kwargs):
            self.calls.append(("choice", args, kwargs))
            return SysOneAnswer(type="choice", choice="option_1")

        def noul(self, *args, **kwargs):
            self.calls.append(("noul", args, kwargs))
            return SysOneAnswer(type="noul", noul=0.75)

        def score(self, *args, **kwargs):
            self.calls.append(("score", args, kwargs))
            return SysOneAnswer(type="score", score=0.5)

        def close(self) -> None:
            self.closed = True

    fake = FakeSysOne()

    def create(provider: str):
        assert provider == "default"
        return fake

    monkeypatch.setattr(phone, "_configured_sysone", create)

    choice = phone.choice(
        {"screen": "settings"}, ["option_1"], instructions="pick"
    )
    noul = phone.noul({"screen": "settings"}, instructions="done?")
    score = phone.score(
        {"screen": "settings"}, ["low", "high"], instructions="rate"
    )

    assert choice.choice == "option_1"
    assert noul.noul == 0.75
    assert score.score == 0.5
    assert phone._sysone_cache == {"default": fake}
    assert [call[0] for call in fake.calls] == ["choice", "noul", "score"]
    assert fake.calls[0][2]["instructions"] == "pick"
    assert fake.calls[1][2]["question_id"] == "noul"
    assert fake.calls[2][1][1] == ["low", "high"]

    phone.close()

    assert fake.closed is True


def test_sysone_configuration_builds_a_typesafe_provider(monkeypatch) -> None:
    monkeypatch.setenv("SYS_ONE_API_KEY", "typesafe-secret")
    config = from_mapping(
        {
            "models": {
                "sysone": {
                    "provider": "typesafe",
                    "model": "jev-latest",
                }
            }
        }
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)

    provider = phone._configured_sysone("default")

    assert provider.base_url == "https://api.typesafe.ai/v1/systemone"
    assert provider.model == "jev-latest"


def test_first_llm_ocr_and_explicit_sysone_providers_are_selected(monkeypatch) -> None:
    config = from_mapping(
        {
            "models": {
                "ocr_providers": {
                    "cloud": {"provider": "paddleocr"},
                    "local": {"provider": "paddleocr"},
                },
                "llm_providers": {
                    "primary": {"model": "primary-model"},
                    "backup": {"model": "backup-model"},
                },
                "sysone_providers": {
                    "typed": {"model": "typed-model"},
                    "backup": {"model": "backup-model"},
                },
            }
        }
    )
    backend = FakeBackend()
    phone = Device(DeviceSession(backend), app_config=config)
    selected: dict[str, list[str]] = {"ocr": [], "llm": [], "sysone": []}

    class FakeOcr:
        def recognize(self, image: bytes):
            return []

    class FakeSysOne:
        def choice(self, state, options, **kwargs):
            return SysOneAnswer(type="choice", choice=next(iter(options)))

    monkeypatch.setattr(
        phone,
        "_configured_ocr",
        lambda provider: selected["ocr"].append(provider) or FakeOcr(),
    )
    monkeypatch.setattr(
        phone,
        "_configured_llm",
        lambda provider: selected["llm"].append(provider) or object(),
    )
    monkeypatch.setattr(
        phone,
        "_configured_sysone",
        lambda provider: selected["sysone"].append(provider) or FakeSysOne(),
    )

    phone.screenshot().ocr()
    phone.choice({}, ["one"], instructions="choose")
    selected["sysone"].clear()
    agent = phone.agent()

    assert selected == {
        "ocr": ["cloud"],
        "llm": ["primary"],
        "sysone": [],
    }
    assert agent.provider == "primary"

    phone.agent(sysone_provider="backup")
    assert selected["sysone"] == ["backup"]


def test_widget_choice_chain_can_filter_clickable_nodes_or_not(monkeypatch) -> None:
    backend = FakeBackend(
        ui_xml=(
            '<hierarchy><node text="页面"><node text="标题" />'
            '<node text="进入设置" content-desc="设置" clickable="true" '
            'bounds="[10,20][30,40]" />'
            '<node text="通知" clickable="true" bounds="[40,20][60,40]" />'
            '<node text="隐藏" clickable="true" visible="false" '
            'bounds="[70,20][90,40]" />'
            '<node text="小控件" clickable="true" bounds="[1,1][5,5]" />'
            '<node text="无边界" clickable="true" /></node></hierarchy>'
        )
    )
    phone, _ = make_device(backend)
    model_requests: list[tuple[dict, dict, str]] = []

    def choose(state, options, **kwargs):
        model_requests.append((state, options, kwargs["instructions"]))
        return SysOneAnswer(type="choice", choice="widget_0")

    monkeypatch.setattr(phone, "choice", choose)

    selected = phone.widgets().clickable().choice("进入设置")
    selected.click()
    phone.widgets().choice("进入设置").click()

    assert [options for _, options, _ in model_requests] == [
        {"widget_0": "进入设置 — 设置", "widget_1": "通知"},
        {"widget_0": "进入设置 — 设置", "widget_1": "通知"},
    ]
    assert [instruction for _, _, instruction in model_requests] == [
        "进入设置",
        "进入设置",
    ]
    assert all(
        all(
            "bounds" not in widget and "center" not in widget
            for widget in state["widgets"]
        )
        for state, _, _ in model_requests
    )
    assert backend.actions == [Click(Point(20, 30), 80), Click(Point(20, 30), 80)]
    assert backend.dump_request == DumpUiRequest(prefer_webview=False)


def test_widget_choice_requires_clickable_bounded_target_and_valid_choice(monkeypatch) -> None:
    backend = FakeBackend(
        ui_xml='<hierarchy><node text="not a button" bounds="[0,0][20,20]" /></hierarchy>'
    )
    phone, _ = make_device(backend)

    with pytest.raises(UiElementNotFound, match="no clickable widgets"):
        phone.widgets().choice("choose")

    backend.ui_xml = (
        '<hierarchy><node text="button" clickable="true" '
        'bounds="[10,10][30,30]" /></hierarchy>'
    )
    monkeypatch.setattr(
        phone,
        "choice",
        lambda *args, **kwargs: SysOneAnswer(type="choice", choice="unknown"),
    )
    with pytest.raises(ModelError, match="unknown widget id"):
        phone.widgets().choice("choose")

    assert backend.actions == []


def test_sysone_goal_creates_configured_ocr_only_when_requested(monkeypatch) -> None:
    config = from_mapping(
        {"models": {"ocr_providers": {"local": {"provider": "paddleocr"}}}}
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)
    created: list[str] = []

    class FakeOcr:
        def recognize(self, image: bytes):
            return []

    monkeypatch.setattr(
        phone,
        "_configured_ocr",
        lambda provider: created.append(provider) or FakeOcr(),
    )

    goal = phone.sysone_goal(sysone=object())

    assert created == []
    assert goal.max_seconds is None
    assert goal.ocr is not None
    assert goal.ocr.recognize(b"image") == []
    assert created == ["local"]


def test_device_run_uses_llm_without_implicit_sysone_call(monkeypatch) -> None:
    config = from_mapping(
        {
            "models": {
                "llm_providers": {"primary": {"model": "primary-model"}},
                "sysone_providers": {"typed": {"model": "typed-model"}},
            }
        }
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)
    created_sysone: list[str] = []
    sysone_calls: list[tuple[object, object]] = []
    created_llm: list[str] = []
    llm_calls: list[str] = []

    class FakeSysOne:
        def ask(self, state, questions):
            sysone_calls.append((state, questions))
            return SysOneResponse(
                answers={
                    "ready": SysOneAnswer(type="noul", noul=0.96),
                },
                model="fake",
            )

    class FakeLlm:
        def complete_with_tools(self, prompt, *, tools, image=None):
            llm_calls.append(prompt)
            return [LlmToolCall("goal_complete", {"reason": "LLM confirms goal"})]

    monkeypatch.setattr(
        phone,
        "_configured_sysone",
        lambda provider: created_sysone.append(provider) or FakeSysOne(),
    )
    monkeypatch.setattr(
        phone,
        "_configured_llm",
        lambda provider: created_llm.append(provider) or FakeLlm(),
    )

    result = phone.llm("检查当前页面", dry_run=True)

    assert result.success is True
    assert result.termination == "goal_complete"
    assert result.plan.provider == "primary"
    assert created_sysone == []
    assert created_llm == ["primary"]
    assert sysone_calls == []
    assert result.plan.sysone is None
    assert len(llm_calls) == 1


def test_device_run_adds_sysone_only_when_explicitly_requested(monkeypatch) -> None:
    config = from_mapping(
        {
            "models": {
                "llm_providers": {"primary": {"model": "primary-model"}},
                "sysone_providers": {"typed": {"model": "typed-model"}},
            }
        }
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)
    sysone_calls: list[object] = []

    class FakeSysOne:
        def ask(self, state, questions):
            sysone_calls.append((state, questions))
            return SysOneResponse(
                answers={"ready": SysOneAnswer(type="noul", noul=0.96)},
                model="fake",
            )

    class FakeLlm:
        def complete_with_tools(self, prompt, *, tools, image=None):
            return [LlmToolCall("goal_complete", {"reason": "LLM confirms goal"})]

    monkeypatch.setattr(phone, "_configured_sysone", lambda _provider: FakeSysOne())
    monkeypatch.setattr(phone, "_configured_llm", lambda _provider: FakeLlm())

    result = phone.llm("检查当前页面", sysone_provider="typed", dry_run=True)

    assert result.termination == "goal_complete"
    assert result.plan.sysone == {"ready": 0.96}
    assert len(sysone_calls) == 1


def test_llm_entry_point_does_not_fall_back_to_sysone(monkeypatch) -> None:
    config = from_mapping(
        {
            "models": {
                "llm": {"api_key_env": "NIER_TEST_MISSING_LLM_KEY"},
                "sysone_providers": {"typed": {"model": "typed-model"}},
            }
        }
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)
    sysone_calls: list[object] = []

    class FakeSysOne:
        def ask(self, state, questions):
            sysone_calls.append((state, questions))
            return SysOneResponse(
                answers={
                    "done": SysOneAnswer(type="noul", noul=0.96),
                    "next": SysOneAnswer(
                        type="choice",
                        choice="blocked",
                        confidence=0.99,
                        probabilities={"blocked": 0.99},
                    ),
                },
                model="fake",
            )

    monkeypatch.setattr(phone, "_configured_sysone", lambda _provider: FakeSysOne())
    with pytest.raises(ConfigurationError, match="LLM API key is missing"):
        phone.llm("检查当前页面", dry_run=True)

    assert sysone_calls == []


def test_sysone_forwards_bounded_llm_recovery_tool_calls(monkeypatch) -> None:
    config = from_mapping(
        {
            "models": {
                "llm_providers": {"primary": {"model": "primary-model"}},
                "sysone_providers": {"typed": {"model": "typed-model"}},
            }
        }
    )
    backend = FakeBackend()
    phone = Device(DeviceSession(backend), app_config=config)
    llm_created: list[str] = []
    tool_requests: list[object] = []
    choices = iter(["call_llm", "blocked"])

    class FakeSysOne:
        def ask(self, state, questions):
            choice = next(choices)
            return SysOneResponse(
                answers={
                    "done": SysOneAnswer(type="noul", noul=0.10 if choice == "call_llm" else 0.96),
                    "next": SysOneAnswer(
                        type="choice",
                        choice=choice,
                        confidence=0.99,
                        probabilities={choice: 0.99},
                    ),
                },
                model="fake",
            )

    class FakeLlm:
        def complete(self, prompt: str, *, image: bytes | None = None) -> str:
            return "返回上一页"

        def complete_with_tools(self, prompt: str, *, tools, image: bytes | None = None):
            tool_requests.append(tools)
            if len(tool_requests) == 1:
                return [LlmToolCall("recovery_action", {"candidate_id": "back"})]
            return [LlmToolCall("recovery_complete", {})]

    monkeypatch.setattr(phone, "_configured_sysone", lambda provider: FakeSysOne())
    monkeypatch.setattr(
        phone,
        "_configured_llm",
        lambda provider: llm_created.append(provider) or FakeLlm(),
    )

    result = phone.sysone("继续操作", max_llm_assists=1)

    assert result.success is True
    assert llm_created == ["primary"]
    assert len(tool_requests) == 2
    assert backend.actions == [Key(KeyCode.BACK)]


def test_unbound_screenshot_rejects_ocr() -> None:
    screenshot = Screenshot(b"image", ImageFormat.PNG, 100, 200, "digest")

    with pytest.raises(ProtocolError, match=r"phone\.screenshot"):
        screenshot.ocr()


def test_uidump_returns_text_and_optionally_writes_file(tmp_path) -> None:
    phone, backend = make_device()
    target = tmp_path / "nested" / "ui.xml"

    xml = phone.uidump(target, prefer_webview=False, include_invisible=True)

    assert xml == "<hierarchy />"
    assert target.read_text(encoding="utf-8") == xml
    assert backend.dump_request == DumpUiRequest(
        prefer_webview=False,
        include_invisible=True,
    )


def test_device_can_capture_and_parse_a_dump() -> None:
    phone, _ = make_device()

    document = phone.parse_uidump()

    assert document.find(tag="hierarchy") is not None


def test_context_manager_closes_backend() -> None:
    phone, backend = make_device()

    with phone:
        assert phone.health()

    assert backend.closed is True


def test_connect_accepts_script_friendly_remote_endpoint() -> None:
    phone = connect(
        remote="192.0.2.10:5566",
        adb_server=("adb.example", 5038),
        retries=0,
    )
    config = phone.session.backend.config  # type: ignore[attr-defined]
    try:
        assert config.remote_host == "192.0.2.10"
        assert config.remote_port == 5566
        assert config.adb_server_host == "adb.example"
        assert config.adb_server_port == 5038
        assert phone.session.retries == 0
    finally:
        phone.close()


def test_connect_rejects_conflicting_targets() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        connect(serial="device", remote="192.0.2.10")
