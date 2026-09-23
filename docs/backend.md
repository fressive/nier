# Backend API

The backend protocol is a synchronous interface for device access. A backend
must provide:

| Method | Return value |
| --- | --- |
| `health()` | `bool` |
| `capabilities()` | `Capabilities` |
| `execute(action)` | `ActionResult` |
| `screenshot(request=None)` | `Screenshot` |
| `dump_ui(request=None)` | `UiDump` |
| `list_apps()` | `list[str]` |
| `list_app_activities(package)` | `list[str]` |
| `open_app(package)` | `ActionResult` |
| `start_activity(package, activity)` | `ActionResult` |
| `close()` | `None` |

The interface is defined by [`src/nier/backend.py`](../src/nier/backend.py).
`AdbBackend` is the default implementation; custom backends can implement the
same protocol for tests or other authorized device transports.

For a device reachable over TCP, see the [remote ADB guide](remote-adb.md).

## Custom backend

Any object implementing the protocol can be passed to `DeviceSession`:

```python
from nier.backend import Backend
from nier.protocol import (
    Action,
    ActionResult,
    Capabilities,
    Click,
    DumpUiRequest,
    Point,
    Screenshot,
    ScreenshotRequest,
    UiDump,
)
from nier.session import DeviceSession


class RecordingBackend:
    def health(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities(
            protocol_version="v1",
            device_id="fake-device",
            model="simulator",
            screen_width=1080,
            screen_height=1920,
            is_rooted=False,
            supports_uinput=False,
            supports_ui_automator=False,
            supports_webview_debugging=False,
        )

    def execute(self, action: Action) -> ActionResult:
        return ActionResult(success=True, message=f"recorded {action!r}")

    def screenshot(self, request: ScreenshotRequest | None = None) -> Screenshot:
        raise NotImplementedError

    def dump_ui(self, request: DumpUiRequest | None = None) -> UiDump:
        raise NotImplementedError

    def list_apps(self) -> list[str]:
        raise NotImplementedError

    def list_app_activities(self, package: str) -> list[str]:
        raise NotImplementedError

    def open_app(self, package: str) -> ActionResult:
        raise NotImplementedError

    def start_activity(self, package: str, activity: str) -> ActionResult:
        raise NotImplementedError

    def close(self) -> None:
        pass


backend: Backend = RecordingBackend()
session = DeviceSession(backend)
print(session.execute(Click(Point(10, 20))))
session.close()
```

Backends must report failed device operations as errors rather than returning a
successful result. `DeviceSession` retries read operations only; `execute`,
`open_app`, and `start_activity` are never automatically retried.
