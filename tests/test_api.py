from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nier import Device, connect
from nier.config import from_mapping
from nier.errors import ProtocolError
from nier.models.base import BoundingBox, TextSpan
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
        return UiDump("<hierarchy />", UiSource.UIAUTOMATOR)

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


def test_jev_is_created_from_configuration_and_cached(monkeypatch) -> None:
    phone, _ = make_device()

    class FakeJev:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake = FakeJev()

    def create(provider: str):
        assert provider == "default"
        return fake

    monkeypatch.setattr(phone, "_configured_jev", create)

    assert phone.jev() is fake
    assert phone.jev() is fake
    assert phone._jev_cache == {"default": fake}

    phone.close()

    assert fake.closed is True


def test_omitted_provider_names_use_the_first_configured_entries(monkeypatch) -> None:
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
                "jev_providers": {
                    "typed": {"model": "typed-model"},
                    "backup": {"model": "backup-model"},
                },
            }
        }
    )
    phone = Device(DeviceSession(FakeBackend()), app_config=config)
    selected: dict[str, list[str]] = {"ocr": [], "llm": [], "jev": []}

    class FakeOcr:
        def recognize(self, image: bytes):
            return []

    class FakeJev:
        pass

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
        "_configured_jev",
        lambda provider: selected["jev"].append(provider) or FakeJev(),
    )

    phone.screenshot().ocr()
    phone.jev()
    agent = phone.agent()

    assert selected == {
        "ocr": ["cloud"],
        "llm": ["primary"],
        "jev": ["typed"],
    }
    assert agent.provider == "primary"


def test_jev_goal_creates_configured_ocr_only_when_requested(monkeypatch) -> None:
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

    goal = phone.jev_goal(jev=object())

    assert created == []
    assert goal.ocr is not None
    assert goal.ocr.recognize(b"image") == []
    assert created == ["local"]


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
