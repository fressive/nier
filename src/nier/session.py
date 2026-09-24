"""High-level device session with safe retry and recording semantics."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from .backend import Backend
from .errors import BackendError, BackendUnavailable, HookError
from .logging_utils import result as log_result
from .logging_utils import step
from .protocol import (
    Action,
    ActionResult,
    ActivityInfo,
    Capabilities,
    DumpUiRequest,
    ImageFormat,
    Screenshot,
    ScreenshotRequest,
    UiDump,
    normalize_activity_component,
    validate_package_name,
)
from .results import RunRecorder


T = TypeVar("T")


def _read_response_details(value: Any) -> Any:
    """Return a useful representation of a successful read result."""
    if isinstance(value, Capabilities):
        return {
            "protocol_version": value.protocol_version,
            "model": value.model,
            "screen_width": value.screen_width,
            "screen_height": value.screen_height,
            "is_rooted": value.is_rooted,
            "supports_uinput": value.supports_uinput,
            "supports_ui_automator": value.supports_ui_automator,
            "supports_webview_debugging": value.supports_webview_debugging,
            "action_names": value.action_names,
        }
    if isinstance(value, Screenshot):
        return {
            "format": getattr(value.format, "value", value.format),
            "width": value.width,
            "height": value.height,
            "sha256": value.sha256,
            "data": f"<binary {len(value.data)} bytes>",
        }
    if isinstance(value, UiDump):
        return {
            "source": value.source.value,
            "complete": value.complete,
            "warning": value.warning,
        }
    if isinstance(value, ActivityInfo):
        return value.to_dict()
    return value


class DeviceSession:
    def __init__(self, backend: Backend, *, retries: int = 2, recorder: RunRecorder | None = None) -> None:
        if retries < 0:
            raise ValueError("retries must not be negative")
        self.backend = backend
        self.retries = retries
        self.recorder = recorder or RunRecorder()

    def _read_with_retry(self, operation: str, callback: Callable[[], T]) -> T:
        record = self.recorder.start(operation)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            step("read", operation=operation, attempt=attempt + 1, status="start")
            try:
                result = callback()
                record.finish(True, attempts=attempt + 1)
                log_result(
                    "read",
                    _read_response_details(result),
                    operation=operation,
                    attempt=attempt + 1,
                )
                return result
            except (BackendUnavailable, TimeoutError) as exc:
                last_error = exc
                step(
                    "read",
                    operation=operation,
                    attempt=attempt + 1,
                    status="retry" if attempt < self.retries else "failed",
                    error=str(exc),
                )
                if attempt < self.retries:
                    time.sleep(min(0.25 * (2**attempt), 2.0))
        assert last_error is not None
        record.error = str(last_error)
        record.finish(False, attempts=self.retries + 1)
        raise last_error

    def health(self) -> bool:
        return self._read_with_retry("health", self.backend.health)

    def capabilities(self):
        return self._read_with_retry("capabilities", self.backend.capabilities)

    def execute(self, action: Action) -> ActionResult:
        # Actions are deliberately never retried automatically: repeating a
        # tap or text input can mutate the application twice after a lost reply.
        record = self.recorder.start(type(action).__name__)
        details: dict[str, object] = {"action": type(action).__name__}
        if hasattr(action, "point"):
            point = action.point
            details["point"] = {"x": point.x, "y": point.y, "normalized": point.normalized}
        elif hasattr(action, "points"):
            details["points"] = len(action.points)
        elif hasattr(action, "text"):
            details["text_length"] = len(action.text)
        elif hasattr(action, "key_code"):
            details["key"] = action.key_code.value
        step("action", **details)
        try:
            result = self.backend.execute(action)
            record.finish(result.success, message=result.message, error_code=result.error_code)
            step("action", action=type(action).__name__, status="ok" if result.success else "failed")
            return result
        except (BackendError, HookError) as exc:
            record.error = str(exc)
            record.finish(False)
            step("action", action=type(action).__name__, status="failed", error=str(exc))
            raise

    def screenshot(
        self,
        request: ScreenshotRequest | None = None,
        *,
        format: ImageFormat | None = None,
        quality: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> Screenshot:
        """Capture a screenshot using a request or keyword options.

        The keyword form is intended for ordinary Python callers. Passing a
        ``ScreenshotRequest`` remains useful for transport adapters and
        reusable structured requests; the two forms must not be mixed.
        """
        options = (format, quality, max_width, max_height)
        if request is not None and any(option is not None for option in options):
            raise ValueError("pass either screenshot request or keyword options, not both")
        if request is None and any(option is not None for option in options):
            request = ScreenshotRequest(
                format=ImageFormat.PNG if format is None else format,
                quality=90 if quality is None else quality,
                max_width=0 if max_width is None else max_width,
                max_height=0 if max_height is None else max_height,
            )
        step(
            "screenshot",
            format=(request.format.value if request is not None else ImageFormat.PNG.value),
            max_width=(request.max_width if request is not None else 0),
            max_height=(request.max_height if request is not None else 0),
        )
        return self._read_with_retry("screenshot", lambda: self.backend.screenshot(request))

    def dump_ui(
        self,
        request: DumpUiRequest | None = None,
        *,
        prefer_webview: bool | None = None,
        include_invisible: bool | None = None,
    ) -> UiDump:
        """Dump the UI using a request or keyword options.

        The keyword form is intended for ordinary Python callers. Passing a
        ``DumpUiRequest`` remains supported for structured transport calls;
        the two forms must not be mixed.
        """
        options = (prefer_webview, include_invisible)
        if request is not None and any(option is not None for option in options):
            raise ValueError("pass either UI dump request or keyword options, not both")
        if request is None and any(option is not None for option in options):
            request = DumpUiRequest(
                prefer_webview=True if prefer_webview is None else prefer_webview,
                include_invisible=False if include_invisible is None else include_invisible,
            )
        step(
            "dump-ui",
            prefer_webview=(request.prefer_webview if request is not None else True),
            include_invisible=(request.include_invisible if request is not None else False),
        )
        dump = self._read_with_retry("dump_ui", lambda: self.backend.dump_ui(request))
        log_result(
            "uidump",
            {
                "source": dump.source.value,
                "complete": dump.complete,
                "warning": dump.warning,
            },
        )
        return dump

    def current_activity(self) -> ActivityInfo | None:
        """Return the foreground Activity when the backend can report it."""
        callback = getattr(self.backend, "current_activity", None)
        if not callable(callback):
            step("current-activity", available=False, reason="backend-unsupported")
            return None
        return self._read_with_retry("current_activity", callback)

    def list_apps(self) -> list[str]:
        """Return installed package names using the session read policy."""
        callback = getattr(self.backend, "list_apps", None)
        if not callable(callback):
            callback = getattr(self.backend, "list_app", None)
        if not callable(callback):
            raise BackendError("backend does not support listing installed apps")
        return self._read_with_retry("list_apps", callback)

    def list_app(self) -> list[str]:
        """Compatibility alias for :meth:`list_apps`."""
        return self.list_apps()

    def list_app_activities(self, package: str) -> list[str]:
        """Return Activity class names for an installed package."""
        package = validate_package_name(package)
        callback = getattr(self.backend, "list_app_activities", None)
        if not callable(callback):
            callback = getattr(self.backend, "list_app_activity", None)
        if not callable(callback):
            raise BackendError("backend does not support listing app activities")
        return self._read_with_retry(
            "list_app_activities",
            lambda: callback(package),
        )

    def list_app_activity(self, package: str) -> list[str]:
        """Compatibility alias for :meth:`list_app_activities`."""
        return self.list_app_activities(package)

    def _run_named_action(
        self,
        operation: str,
        callback: Callable[[], ActionResult],
    ) -> ActionResult:
        """Run one non-idempotent backend action without retrying it."""
        record = self.recorder.start(operation)
        step("action", action=operation)
        try:
            result = callback()
            record.finish(result.success, message=result.message, error_code=result.error_code)
            step("action", action=operation, status="ok" if result.success else "failed")
            return result
        except (BackendError, HookError, TimeoutError) as exc:
            record.error = str(exc)
            record.finish(False)
            step("action", action=operation, status="failed", error=str(exc))
            raise

    def open_app(self, package: str) -> ActionResult:
        """Open an app's launcher Activity; the action is never retried."""
        package = validate_package_name(package)
        callback = getattr(self.backend, "open_app", None)
        if not callable(callback):
            callback = getattr(self.backend, "launch_app", None)
        if not callable(callback):
            raise BackendError("backend does not support opening apps")
        return self._run_named_action("open_app", lambda: callback(package))

    def launch_app(self, package: str) -> ActionResult:
        """Compatibility alias for :meth:`open_app`."""
        return self.open_app(package)

    def start_activity(self, package: str, activity: str) -> ActionResult:
        """Start an Activity; the action is never retried."""
        package = validate_package_name(package)
        component = normalize_activity_component(package, activity)
        callback = getattr(self.backend, "start_activity", None)
        if not callable(callback):
            callback = getattr(self.backend, "open_activity", None)
        if not callable(callback):
            raise BackendError("backend does not support starting Activities")
        return self._run_named_action(
            "start_activity",
            lambda: callback(package, component),
        )

    def open_activity(self, package: str, activity: str) -> ActionResult:
        """Compatibility alias for :meth:`start_activity`."""
        return self.start_activity(package, activity)

    def close(self) -> None:
        self.backend.close()
