"""Small, privacy-aware verbosity logging helpers for the host runtime."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit


MAX_LOG_PAYLOAD = 4096
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|secret|token)",
    re.IGNORECASE,
)
_DATA_URI = re.compile(r"^data:[^,]*,", re.IGNORECASE)
_LOGGER = logging.getLogger("nier")
_VERBOSITY = 0
_WEB_EVENT_PREFIX = "\x1eNIER_EVENT "
_WEB_EVENT_LOCK = threading.Lock()
_RESET = "\x1b[0m"
_CATEGORY_COLORS = {
    "STEP": "\x1b[36;1m",
    "TOOL CALL": "\x1b[35;1m",
    "OCR RESULT": "\x1b[36;1m",
    "UIDUMP RESULT": "\x1b[33;1m",
    "SYS ONE RESULT": "\x1b[32;1m",
    "SYS ONE CONTEXT": "\x1b[35;1m",
    "LLM RESULT": "\x1b[35;1m",
}


class _NierFormatter(logging.Formatter):
    """Color event categories and timestamp logs sent to a terminal."""

    def __init__(self, *, use_color: bool) -> None:
        super().__init__("%(asctime)s %(message)s", datefmt="%H:%M:%S")
        self.use_color = use_color

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = super().formatTime(record, datefmt)
        return f"{timestamp}.{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        timestamp = self.formatTime(record, self.datefmt)
        timestamp_prefix = f"{timestamp} "
        if not formatted.startswith(timestamp_prefix):
            return formatted

        message = formatted[len(timestamp_prefix):]
        if not self.use_color:
            return formatted

        category = getattr(record, "nier_category", None)
        level = getattr(record, "nier_verbosity", None)
        if not isinstance(level, str) or not isinstance(category, str):
            return formatted

        prefix = f"[nier {level}] "
        if not message.startswith(prefix + category):
            return formatted

        category_color = _CATEGORY_COLORS.get(category)
        if category_color is None:
            if category.endswith("REQUEST"):
                category_color = "\x1b[34;1m"
            elif category.endswith("RESPONSE"):
                category_color = "\x1b[32;1m"
            else:
                category_color = "\x1b[37;1m"

        return (
            f"\x1b[2m{timestamp}{_RESET} "
            f"{prefix}{category_color}{category}{_RESET}"
            f"{message[len(prefix) + len(category):]}"
        )


def configure_logging(verbosity: int) -> None:
    """Configure Nier's stdout logger for verbosity levels 0 through 3."""
    global _VERBOSITY
    if isinstance(verbosity, bool) or not isinstance(verbosity, int):
        raise ValueError("logging verbosity must be an integer from 0 to 3")
    if not 0 <= verbosity <= 3:
        raise ValueError("logging verbosity must be between 0 and 3")
    # The web runner asks child scripts for the same bounded, sanitized
    # request/response detail available at -vvv, regardless of the script's
    # terminal logging configuration.
    if os.environ.get("NIER_WEB_EVENT_STREAM") == "1":
        verbosity = max(verbosity, 3)
    _VERBOSITY = verbosity

    # Keep the dedicated Nier logger deterministic. In particular, pytest and
    # embedding applications may attach their own capture handler directly to
    # this logger; retaining it would duplicate every line. Removed handlers
    # are intentionally not closed because their stream may already belong to
    # a finished capture context.
    for handler in list(_LOGGER.handlers):
        _LOGGER.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _NierFormatter(use_color=_supports_color(handler.stream))
    )
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False
    _LOGGER.disabled = False
    _LOGGER.setLevel(logging.INFO if verbosity else logging.CRITICAL + 1)


def verbosity() -> int:
    """Return the currently active Nier verbosity."""
    return _VERBOSITY


def step(message: str, **fields: Any) -> None:
    """Write one high-level operation at ``v`` and above."""
    if _VERBOSITY >= 1:
        _emit("v", "STEP", message, fields)


def tool_call(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    call_id: str | None = None,
    **fields: Any,
) -> None:
    """Write a safe model tool call at ``v`` and above.

    Text, value, and reason arguments are represented by their lengths so a
    verbose run does not copy input contents into the log. Other arguments use
    the same redaction and size limits as request/response logging.
    """
    if _VERBOSITY >= 1:
        details = dict(fields)
        details["name"] = name
        if call_id:
            details["id"] = call_id
        if arguments is not None:
            details["arguments"] = arguments
        _emit("v", "TOOL CALL", "model requested", details)


def request(
    protocol: str,
    method: str,
    target: str,
    *,
    headers: Mapping[str, Any] | None = None,
    body: Any = None,
    **fields: Any,
) -> None:
    """Write a sanitized transport request at ``vvv``."""
    if _VERBOSITY >= 3:
        details = dict(fields)
        details["method"] = method
        details["target"] = _safe_target(target)
        if headers:
            details["headers"] = _safe_mapping(headers)
        if body is not None:
            details["body"] = _safe_payload(body)
        _emit("vvv", f"{protocol.upper()} REQUEST", "outgoing", details)


def response(
    protocol: str,
    status: Any = None,
    *,
    target: str | None = None,
    headers: Mapping[str, Any] | None = None,
    body: Any = None,
    **fields: Any,
) -> None:
    """Write a sanitized response body at ``vvv`` and above."""
    if _VERBOSITY >= 3:
        details = dict(fields)
        if status is not None:
            details["status"] = status
        if target is not None:
            details["target"] = _safe_target(target)
        if headers:
            details["headers"] = _safe_mapping(headers)
        if body is not None:
            details["body"] = _safe_payload(body)
        _emit("vvv", f"{protocol.upper()} RESPONSE", "incoming", details)


def result(category: str, value: Any, **fields: Any) -> None:
    """Write a bounded domain result at ``vv`` and above."""
    if _VERBOSITY >= 2:
        details = dict(fields)
        details["result"] = value
        _emit("vv", f"{category.upper()} RESULT", "returned", details)


def block(
    verbosity_level: int,
    category: str,
    message: str,
    body: str,
    **fields: Any,
) -> None:
    """Write a bounded, indented text block at a selected verbosity level."""
    if _VERBOSITY >= verbosity_level:
        level = "v" * verbosity_level
        suffix = "\n" + _format_fields(fields) if fields else ""
        content = _truncate(body)
        indented = "\n".join(f"  {line}" for line in content.splitlines())
        _LOGGER.info(
            "[nier %s] %s %s%s\n%s",
            level,
            category,
            message,
            suffix,
            indented,
            extra={"nier_verbosity": level, "nier_category": category},
        )


def _emit(level: str, category: str, message: str, fields: Mapping[str, Any]) -> None:
    safe_fields = _safe_mapping(fields)

    def publish() -> None:
        details = _format_fields(fields)
        output = f"[nier {level}] {category} {message}"
        if details:
            output += f"\n{details}"
        _LOGGER.info(
            "%s",
            output,
            extra={"nier_verbosity": level, "nier_category": category},
        )
        _publish_web_event(level, category, message, safe_fields)

    if category == "STEP" and os.environ.get("NIER_WEB_DEBUG") == "1":
        from .web_debugger import emit_step

        emit_step(message, safe_fields, publish)
        return
    publish()


def _publish_web_event(
    level: str,
    category: str,
    message: str,
    fields: Mapping[str, Any],
) -> None:
    """Send a sanitized structured event to a parent Nier web process."""
    if os.environ.get("NIER_WEB_EVENT_STREAM") != "1":
        return
    event = {
        "type": "log",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "category": category,
        "message": message,
        "details": fields,
    }
    try:
        with _WEB_EVENT_LOCK:
            sys.stdout.write(_WEB_EVENT_PREFIX)
            sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            sys.stdout.write("\n")
            sys.stdout.flush()
    except (OSError, UnicodeError):
        # Logging must not interrupt a device action if the dashboard closes.
        return


def _format_fields(fields: Mapping[str, Any]) -> str:
    """Render sanitized event fields as labeled text rather than JSON."""
    safe_fields = _safe_mapping(fields)
    lines: list[str] = []
    for key in sorted(safe_fields):
        value = safe_fields[key]
        if isinstance(value, (Mapping, list, tuple)):
            lines.append(f"  {key}:")
            lines.extend(_format_nested(value, indent=4))
        else:
            lines.append(f"  {key}: {_format_scalar(value)}")
    return "\n".join(lines)


def _format_nested(value: Any, *, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return [f"{prefix}(empty)"]
        lines: list[str] = []
        for key in sorted(value, key=str):
            item = value[key]
            if isinstance(item, (Mapping, list, tuple)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_format_nested(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return lines
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"{prefix}(empty)"]
        lines = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)):
                lines.append(f"{prefix}-")
                lines.extend(_format_nested(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(value)}"]


def _format_scalar(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return repr(value) if value else "(empty)"
    return str(value)


def _supports_color(stream: Any) -> bool:
    """Return whether ANSI styling is appropriate for this output stream."""
    if "NO_COLOR" in os.environ or os.environ.get("TERM", "").lower() == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


def _safe_target(value: str) -> str:
    """Keep URL paths while redacting query values and userinfo."""
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return "<invalid-target>"
    if not parsed.scheme or not parsed.netloc:
        return str(value)[:MAX_LOG_PAYLOAD]
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "<redacted>" if parsed.query else "", ""))


def _safe_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _safe_value(item, key=str(key)) for key, item in value.items()}


def _safe_tool_arguments(value: Mapping[Any, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if name.lower() in {"reason", "text", "value"} and isinstance(item, str):
            safe[name] = f"<{len(item)} chars>"
        else:
            safe[name] = _safe_value(item, key=name)
    return safe


def _safe_value(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if key.lower() == "arguments" and isinstance(value, Mapping):
        return _safe_tool_arguments(value)
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:100]]
    if isinstance(value, bytes):
        return _safe_bytes(value)
    if isinstance(value, str):
        if _DATA_URI.match(value):
            return f"<data-uri {len(value)} chars>"
        return _truncate(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _truncate(repr(value))


def _safe_payload(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            decoded = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _safe_bytes(value)
        return _safe_value(decoded)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return _safe_value(value)
        return _safe_value(decoded)
    return _safe_value(value)


def _safe_bytes(value: bytes) -> str:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary {len(value)} bytes>"
    return _truncate(text)


def _truncate(value: str) -> str:
    if len(value) <= MAX_LOG_PAYLOAD:
        return value
    return f"{value[:MAX_LOG_PAYLOAD]}... <truncated {len(value)} chars>"


__all__ = [
    "MAX_LOG_PAYLOAD",
    "block",
    "configure_logging",
    "request",
    "result",
    "response",
    "step",
    "tool_call",
    "verbosity",
]
