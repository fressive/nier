from __future__ import annotations

from dataclasses import dataclass

import pytest

from nier.errors import BackendUnavailable
from nier.protocol import (
    ActionResult,
    Capabilities,
    Click,
    DumpUiRequest,
    ImageFormat,
    Point,
    Screenshot,
    ScreenshotRequest,
    UiDump,
    UiSource,
)
from nier.results import RunRecorder
from nier.session import DeviceSession


@dataclass
class FakeBackend:
    health_calls: int = 0
    screenshot_calls: int = 0
    execute_calls: int = 0
    open_app_calls: int = 0
    start_activity_calls: int = 0
    fail_open_app: bool = False
    fail_start_activity: bool = False
    last_screenshot_request: ScreenshotRequest | None = None
    last_dump_ui_request: DumpUiRequest | None = None

    def health(self) -> bool:
        self.health_calls += 1
        if self.health_calls == 1:
            raise BackendUnavailable("temporary")
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("v1", "device", "model", 100, 200, False, False, True, False)

    def execute(self, action):
        self.execute_calls += 1
        return ActionResult(True, "ok")

    def screenshot(self, request=None) -> Screenshot:
        self.screenshot_calls += 1
        self.last_screenshot_request = request
        if self.screenshot_calls == 1:
            raise BackendUnavailable("temporary")
        return Screenshot(b"image", "PNG", 1, 1, "digest")  # type: ignore[arg-type]

    def dump_ui(self, request=None) -> UiDump:
        self.last_dump_ui_request = request
        return UiDump("<hierarchy />", UiSource.UIAUTOMATOR)

    def list_apps(self) -> list[str]:
        return ["com.example.app"]

    def list_app_activities(self, package: str) -> list[str]:
        return [f"{package}.MainActivity"]

    def open_app(self, package: str) -> ActionResult:
        self.open_app_calls += 1
        if self.fail_open_app:
            raise BackendUnavailable("launch response unavailable")
        return ActionResult(True, f"opened {package}")

    def start_activity(self, package: str, activity: str) -> ActionResult:
        self.start_activity_calls += 1
        if self.fail_start_activity:
            raise BackendUnavailable("activity response unavailable")
        return ActionResult(True, f"started {package}/{activity}")

    def close(self) -> None:
        pass


def test_read_operations_retry_and_record() -> None:
    backend = FakeBackend()
    recorder = RunRecorder()
    session = DeviceSession(backend, retries=1, recorder=recorder)
    assert session.health() is True
    assert session.screenshot().data == b"image"
    assert backend.health_calls == 2
    assert backend.screenshot_calls == 2
    assert all(record.success for record in recorder.records)


def test_actions_are_not_retried() -> None:
    backend = FakeBackend()
    session = DeviceSession(backend, retries=3)
    result = session.execute(Click(Point(1, 2)))
    assert result.success
    assert backend.execute_calls == 1


def test_session_accepts_keyword_screenshot_options() -> None:
    backend = FakeBackend()
    session = DeviceSession(backend, retries=1)

    session.screenshot(format=ImageFormat.JPEG, quality=75, max_width=640, max_height=480)

    assert backend.last_screenshot_request == ScreenshotRequest(
        format=ImageFormat.JPEG,
        quality=75,
        max_width=640,
        max_height=480,
    )


def test_session_keeps_structured_requests_supported() -> None:
    backend = FakeBackend()
    session = DeviceSession(backend, retries=1)
    screenshot_request = ScreenshotRequest(quality=70)
    dump_request = DumpUiRequest(prefer_webview=False)

    session.screenshot(screenshot_request)
    session.dump_ui(dump_request)

    assert backend.last_screenshot_request is screenshot_request
    assert backend.last_dump_ui_request is dump_request


def test_session_accepts_keyword_ui_dump_options() -> None:
    backend = FakeBackend()
    session = DeviceSession(backend)

    session.dump_ui(prefer_webview=False, include_invisible=True)

    assert backend.last_dump_ui_request == DumpUiRequest(
        prefer_webview=False,
        include_invisible=True,
    )


def test_session_rejects_mixed_request_styles() -> None:
    session = DeviceSession(FakeBackend())

    with pytest.raises(ValueError):
        session.screenshot(ScreenshotRequest(), quality=80)
    with pytest.raises(ValueError):
        session.dump_ui(DumpUiRequest(), prefer_webview=False)


def test_session_exposes_app_queries_as_read_operations() -> None:
    session = DeviceSession(FakeBackend(), retries=0)

    assert session.list_apps() == ["com.example.app"]
    assert session.list_app_activities("com.example.app") == [
        "com.example.app.MainActivity"
    ]


def test_session_does_not_retry_launch_actions() -> None:
    backend = FakeBackend(fail_open_app=True, fail_start_activity=True)
    session = DeviceSession(backend, retries=3)

    with pytest.raises(BackendUnavailable):
        session.open_app("com.example.app")
    with pytest.raises(BackendUnavailable):
        session.start_activity("com.example.app", ".MainActivity")
    assert backend.open_app_calls == 1
    assert backend.start_activity_calls == 1
