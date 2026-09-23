"""Dependency-light domain types for the host and ADB runtime."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import TYPE_CHECKING, Union
from uuid import uuid4

from .errors import ProtocolError

if TYPE_CHECKING:
    from .models.base import TextSpan


PROTOCOL_VERSION = "v1"
_ANDROID_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")
_ANDROID_ACTIVITY_NAME = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
)


def validate_package_name(package: str) -> str:
    """Validate and normalize an Android package name before device access."""
    if not isinstance(package, str) or not package.strip():
        raise ValueError("package must not be empty")
    normalized = package.strip()
    if _ANDROID_PACKAGE_NAME.fullmatch(normalized) is None:
        raise ValueError(f"invalid Android package name: {package!r}")
    return normalized


def normalize_activity_component(package: str, activity: str) -> str:
    """Normalize an Activity class or component to ``package/class`` form."""
    package = validate_package_name(package)
    if not isinstance(activity, str) or not activity.strip():
        raise ValueError("activity must not be empty")
    value = activity.strip()
    if "/" in value:
        component_package, separator, value = value.partition("/")
        if not separator or validate_package_name(component_package) != package:
            raise ValueError(
                f"activity component must belong to package {package!r}: {activity!r}"
            )
        value = value.strip()
    if value.startswith("."):
        full_name = f"{package}{value}"
    elif value.startswith(f"{package}."):
        full_name = value
    elif "." not in value:
        full_name = f"{package}.{value}"
    else:
        raise ValueError(f"activity must belong to package {package!r}: {activity!r}")
    if _ANDROID_ACTIVITY_NAME.fullmatch(full_name) is None:
        raise ValueError(f"invalid Android Activity name: {activity!r}")
    return f"{package}/{full_name}"


class KeyCode(str, Enum):
    BACK = "BACK"
    HOME = "HOME"
    ENTER = "ENTER"
    RECENTS = "RECENTS"
    POWER = "POWER"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"


class ImageFormat(str, Enum):
    PNG = "PNG"
    JPEG = "JPEG"


class UiSource(str, Enum):
    UIAUTOMATOR = "UIAUTOMATOR"
    WEBVIEW_DEVTOOLS = "WEBVIEW_DEVTOOLS"
    UIAUTOMATOR_FALLBACK = "UIAUTOMATOR_FALLBACK"


@dataclass(frozen=True)
class RequestContext:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    deadline_ms: int = 15_000

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ProtocolError("request_id must not be empty")
        if self.deadline_ms <= 0:
            raise ProtocolError("deadline_ms must be positive")


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    normalized: bool = False

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y)):
            raise ProtocolError("point coordinates must be finite")
        if self.normalized and not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
            raise ProtocolError("normalized point coordinates must be between 0 and 1")


@dataclass(frozen=True)
class Click:
    point: Point
    duration_ms: int = 80

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ProtocolError("click duration must not be negative")


@dataclass(frozen=True)
class Swipe:
    points: tuple[Point, ...]
    duration_ms: int = 300

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ProtocolError("swipe requires at least two points")
        if self.duration_ms <= 0:
            raise ProtocolError("swipe duration must be positive")


@dataclass(frozen=True)
class InputText:
    text: str


@dataclass(frozen=True)
class Key:
    key_code: KeyCode


Action = Union[Click, Swipe, InputText, Key]


@dataclass(frozen=True)
class ScreenshotRequest:
    format: ImageFormat = ImageFormat.PNG
    quality: int = 90
    max_width: int = 0
    max_height: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.quality <= 100:
            raise ProtocolError("screenshot quality must be between 1 and 100")
        if self.max_width < 0 or self.max_height < 0:
            raise ProtocolError("screenshot dimensions must not be negative")


@dataclass(frozen=True)
class DumpUiRequest:
    prefer_webview: bool = True
    include_invisible: bool = False


@dataclass(frozen=True)
class Capabilities:
    protocol_version: str
    device_id: str
    model: str
    screen_width: int
    screen_height: int
    is_rooted: bool
    supports_uinput: bool
    supports_ui_automator: bool
    supports_webview_debugging: bool
    action_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class Screenshot:
    data: bytes
    format: ImageFormat
    width: int
    height: int
    sha256: str
    _ocr_callback: Callable[[bytes], Sequence[TextSpan]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def ocr(self) -> Sequence[TextSpan]:
        """Recognize this screenshot through the phone's configured OCR provider."""
        if self._ocr_callback is None:
            raise ProtocolError(
                "screenshot OCR is only available from phone.screenshot(); "
                "connect with a model configuration first"
            )
        return self._ocr_callback(self.data)


@dataclass(frozen=True)
class UiDump:
    xml: str
    source: UiSource
    complete: bool = True
    warning: str = ""


@dataclass(frozen=True)
class ActivityInfo:
    """The foreground Android Activity observed from the device."""

    package: str
    activity: str
    component: str
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "package": self.package,
            "activity": self.activity,
            "component": self.component,
            "source": self.source,
        }
