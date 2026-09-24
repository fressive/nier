"""Dependency-light domain types for the host and ADB runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
_INTENT_EXTRA_TYPES = {
    "null",
    "string",
    "boolean",
    "int",
    "long",
    "float",
    "uri",
    "component",
    "string_array",
    "int_array",
    "long_array",
    "float_array",
}
_INTENT_MAX_TEXT_LENGTH = 4096
_INTENT_MAX_EXTRA_COUNT = 100
_INTENT_MAX_ARRAY_ITEMS = 64
_INTENT_INT_MIN = -(2**31)
_INTENT_INT_MAX = 2**31 - 1
_INTENT_LONG_MIN = -(2**63)
_INTENT_LONG_MAX = 2**63 - 1
_INTENT_FLOAT_MAX = 3.4028234663852886e38


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


def normalize_intent(intent: Mapping[str, object]) -> dict[str, object]:
    """Validate a JSON-compatible Intent payload captured by ``intent-hook``.

    The returned mapping contains only launch fields understood by Nier's ADB
    backend. Android's ``am start`` cannot recreate every Java value type; an
    unsupported or truncated extra is rejected before any device command runs.
    """
    if not isinstance(intent, Mapping):
        raise ValueError("intent must be a mapping captured by nier intent-hook")

    component_value = intent.get("component")
    component: dict[str, str] | None
    if component_value is None:
        component = None
    else:
        if not isinstance(component_value, Mapping):
            raise ValueError("intent component must contain package and class")
        component_package = validate_package_name(component_value.get("package"))
        class_name = _intent_text(component_value.get("class"), "component class")
        if _ANDROID_ACTIVITY_NAME.fullmatch(class_name) is None:
            raise ValueError(f"invalid Intent component class: {class_name!r}")
        component = {"package": component_package, "class": class_name}

    action = _optional_intent_text(intent.get("action"), "action")
    if intent.get("action_truncated") and action is not None:
        raise ValueError("captured Intent action was truncated; remove it before launch")
    data = _optional_intent_text(intent.get("data"), "data URI")
    if intent.get("data_truncated") and data is not None:
        raise ValueError("captured Intent data URI was truncated; remove it before launch")
    mime_type = _optional_intent_text(intent.get("type"), "MIME type")
    if intent.get("type_truncated") and mime_type is not None:
        raise ValueError("captured Intent MIME type was truncated; remove it before launch")

    package_value = intent.get("package")
    if intent.get("package_truncated") and package_value is not None:
        raise ValueError("captured Intent package was truncated; remove it before launch")
    package = (
        None
        if package_value is None
        else validate_package_name(_intent_text(package_value, "package"))
    )

    flags_value = intent.get("flags")
    flags: int | None
    if flags_value is None:
        flags = None
    elif (
        isinstance(flags_value, bool)
        or not isinstance(flags_value, int)
        or not _INTENT_INT_MIN <= flags_value <= _INTENT_INT_MAX
    ):
        raise ValueError("intent flags must be a signed 32-bit integer")
    else:
        flags = flags_value

    raw_categories = intent.get("categories", ())
    if not isinstance(raw_categories, Sequence) or isinstance(raw_categories, str):
        raise ValueError("intent categories must be a sequence of strings")
    if len(raw_categories) > _INTENT_MAX_EXTRA_COUNT:
        raise ValueError("intent contains too many categories")
    categories = [
        _intent_text(category, "category") for category in raw_categories
    ]
    if intent.get("categories_truncated"):
        raise ValueError("captured Intent categories were truncated; review them before launch")

    raw_extras = intent.get("extras", {})
    if not isinstance(raw_extras, Mapping):
        raise ValueError("intent extras must be a mapping")
    if len(raw_extras) > _INTENT_MAX_EXTRA_COUNT:
        raise ValueError("intent contains too many extras")
    if intent.get("extras_truncated"):
        raise ValueError("captured Intent extras were truncated; review them before launch")
    if intent.get("extras_unavailable"):
        raise ValueError("captured Intent extras were unavailable; review them before launch")
    extras: dict[str, dict[str, object]] = {}
    for key, extra in raw_extras.items():
        name = _intent_text(key, "extra key")
        extras[name] = _normalize_intent_extra(name, extra)

    return {
        "component": component,
        "action": action,
        "data": data,
        "type": mime_type,
        "package": package,
        "flags": flags,
        "categories": categories,
        "extras": extras,
    }


def _normalize_intent_extra(name: str, extra: object) -> dict[str, object]:
    if not isinstance(extra, Mapping):
        raise ValueError(f"Intent extra {name!r} must include a type and value")
    kind = extra.get("type")
    if not isinstance(kind, str):
        raise ValueError(f"Intent extra {name!r} has no supported type")
    if extra.get("truncated"):
        raise ValueError(f"Intent extra {name!r} was truncated")
    if kind not in _INTENT_EXTRA_TYPES:
        raise ValueError(
            f"Intent extra {name!r} has unsupported type {kind!r} for ADB launch"
        )
    value = extra.get("value")

    if kind == "null":
        if value is not None:
            raise ValueError(f"Intent extra {name!r} has an invalid null value")
    elif kind == "string":
        value = _intent_text(value, f"extra {name!r}")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"Intent extra {name!r} must be a boolean")
    elif kind == "int":
        value = _intent_integer(value, name, _INTENT_INT_MIN, _INTENT_INT_MAX)
    elif kind == "long":
        value = _intent_integer(value, name, _INTENT_LONG_MIN, _INTENT_LONG_MAX)
    elif kind == "float":
        value = _intent_float(value, f"extra {name!r}")
    elif kind == "uri":
        value = _intent_text(value, f"extra {name!r} URI")
    elif kind == "component":
        if not isinstance(value, Mapping):
            raise ValueError(f"Intent extra {name!r} must contain a component")
        component_package = validate_package_name(value.get("package"))
        class_name = _intent_text(value.get("class"), f"extra {name!r} class")
        if _ANDROID_ACTIVITY_NAME.fullmatch(class_name) is None:
            raise ValueError(f"Intent extra {name!r} has an invalid component class")
        value = {"package": component_package, "class": class_name}
    else:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"Intent extra {name!r} must be an array")
        if not 1 <= len(value) <= _INTENT_MAX_ARRAY_ITEMS:
            raise ValueError(
                f"Intent extra {name!r} array must contain 1 to "
                f"{_INTENT_MAX_ARRAY_ITEMS} values"
            )
        item_type = kind.removesuffix("_array")
        normalized: list[object] = []
        for item in value:
            if item_type == "string":
                text = _intent_text(item, f"Intent extra {name!r} item")
                if not text or "," in text:
                    raise ValueError(
                        f"Intent string-array extra {name!r} cannot contain empty "
                        "values or commas when launched through adb"
                    )
                normalized.append(text)
            elif item_type == "int":
                normalized.append(
                    _intent_integer(item, name, _INTENT_INT_MIN, _INTENT_INT_MAX)
                )
            elif item_type == "long":
                normalized.append(
                    _intent_integer(item, name, _INTENT_LONG_MIN, _INTENT_LONG_MAX)
                )
            elif item_type == "float":
                normalized.append(_intent_float(item, f"extra {name!r} array item"))
        value = normalized

    return {"type": kind, "value": value}


def _intent_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Intent {label} must be a string")
    if len(value) > _INTENT_MAX_TEXT_LENGTH:
        raise ValueError(f"Intent {label} exceeds {_INTENT_MAX_TEXT_LENGTH} characters")
    if "\x00" in value:
        raise ValueError(f"Intent {label} cannot contain a NUL character")
    return value


def _optional_intent_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _intent_text(value, label)


def _intent_integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"Intent extra {name!r} must be an integer")
    if isinstance(value, str):
        if not re.fullmatch(r"-?(0|[1-9]\d*)", value):
            raise ValueError(f"Intent extra {name!r} has an invalid integer value")
        value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"Intent extra {name!r} is outside its Android integer range")
    return value


def _intent_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"Intent {label} must be a float")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"Intent {label} is outside the Android float range") from exc
    if not math.isfinite(number) or abs(number) > _INTENT_FLOAT_MAX:
        raise ValueError(f"Intent {label} is outside the Android float range")
    return number


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
