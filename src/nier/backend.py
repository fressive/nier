"""Backend interface used by the test runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .protocol import (
    Action,
    ActionResult,
    ActivityInfo,
    Capabilities,
    DumpUiRequest,
    Screenshot,
    ScreenshotRequest,
    UiDump,
)


class Backend(Protocol):
    """Synchronous interface implemented by ADB and custom test backends."""

    def health(self) -> bool:
        ...

    def capabilities(self) -> Capabilities:
        ...

    def execute(self, action: Action) -> ActionResult:
        ...

    def screenshot(self, request: ScreenshotRequest | None = None) -> Screenshot:
        ...

    def dump_ui(self, request: DumpUiRequest | None = None) -> UiDump:
        ...

    def current_activity(self) -> ActivityInfo | None:
        ...

    def list_apps(self) -> list[str]:
        """Return installed Android package names."""
        ...

    def list_app_activities(self, package: str) -> list[str]:
        """Return fully qualified Activity class names for ``package``."""
        ...

    def open_app(self, package: str) -> ActionResult:
        """Open the package's launcher Activity without retrying the action."""
        ...

    def start_activity(self, package: str, activity: str) -> ActionResult:
        """Start one Activity without retrying the action."""
        ...

    def start_intent(self, intent: Mapping[str, object]) -> ActionResult:
        """Start one captured Intent without retrying the action."""
        ...

    def close(self) -> None:
        ...
