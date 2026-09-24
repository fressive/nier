"""STEP-boundary controls used by the local web script runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
from time import monotonic
from typing import Any, Callable

from .logging_utils import _WEB_EVENT_LOCK


_EVENT_PREFIX = "\x1eNIER_EVENT "
_COMMANDS = {"continue", "step", "step_into", "step_out"}
_commands: queue.Queue[str] = queue.Queue()
_step_lock = threading.Lock()
_mode = "step"
_target_depth = 0
_LINE_TRACE_INTERVAL = 0.05


class _ScriptLineTracer:
    """Publish sampled source locations for files inside the script root."""

    def __init__(self, script_root: Path) -> None:
        self.script_root = script_root.resolve()
        self.last_location: tuple[str, int, str] | None = None
        self.last_published_at = 0.0

    def __call__(self, frame, event: str, _arg):
        if event == "call":
            return self if self._relative_file(frame) is not None else None
        if event == "line":
            self._publish_location(frame)
        elif event == "return" and frame.f_code.co_name == "<module>":
            self._publish_location(frame, force=True)
        return self

    def _relative_file(self, frame) -> str | None:
        try:
            filename = Path(frame.f_code.co_filename).resolve()
            if not filename.is_relative_to(self.script_root):
                return None
            return filename.relative_to(self.script_root).as_posix()
        except (OSError, RuntimeError, ValueError):
            return None

    def _publish_location(self, frame, *, force: bool = False) -> None:
        filename = self._relative_file(frame)
        if filename is None:
            return
        location = (filename, frame.f_lineno, frame.f_code.co_name)
        if location == self.last_location:
            return
        now = monotonic()
        if not force and now - self.last_published_at < _LINE_TRACE_INTERVAL:
            return
        self.last_location = location
        self.last_published_at = now
        _publish_event(
            "execution.location",
            file=filename,
            line=frame.f_lineno,
            function=frame.f_code.co_name,
        )


def install_line_tracing() -> bool:
    """Trace script-relative Python lines when enabled by the web runner."""
    root_value = os.environ.get("NIER_WEB_SCRIPT_ROOT")
    if os.environ.get("NIER_WEB_TRACE") != "1" or not root_value:
        return False
    try:
        script_root = Path(root_value).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    sys.settrace(_ScriptLineTracer(script_root))
    return True


def submit_command(command: str) -> None:
    """Queue one validated control command from the dashboard process."""
    if command in _COMMANDS:
        _commands.put(command)


def read_commands(stream) -> None:
    """Read control commands from the runner's private stdin pipe."""
    for line in stream:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        command = payload.get("command") if isinstance(payload, dict) else None
        if command in _COMMANDS:
            submit_command(command)


def emit_step(message: str, details: dict[str, Any], emit: Callable[[], None]) -> None:
    """Publish a STEP and pause at the next matching STEP boundary."""
    global _mode, _target_depth
    with _step_lock:
        depth, location, stack = _call_context()
        emit()
        if not _should_pause(depth):
            return

        _publish_event(
            "debug.paused",
            category="STEP",
            message=message,
            details=details,
            depth=depth,
            stack=stack,
            **location,
        )
        command = _commands.get()
        _publish_event("debug.resumed", command=command)
        if command == "continue":
            _mode = "continue"
            _target_depth = depth
        elif command == "step":
            _mode = "step"
            _target_depth = depth
        elif command == "step_into":
            _mode = "step_into"
            _target_depth = depth
        elif command == "step_out":
            _mode = "step_out"
            _target_depth = depth


def _should_pause(depth: int) -> bool:
    if _mode in {"step", "step_into"}:
        return _mode == "step" or depth > _target_depth
    if _mode == "step_out":
        return depth < _target_depth
    return False


def _call_context() -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    root_value = os.environ.get("NIER_WEB_SCRIPT_ROOT")
    if not root_value:
        return 0, {"file": "", "line": 0, "function": ""}, []
    root = Path(root_value).resolve()
    try:
        frame = sys._getframe(4)
    except ValueError:
        return 0, {"file": "", "line": 0, "function": ""}, []

    stack: list[dict[str, Any]] = []
    entered_script = False
    while frame is not None:
        try:
            filename = Path(frame.f_code.co_filename).resolve()
        except (OSError, RuntimeError, ValueError):
            frame = frame.f_back
            continue
        in_script = filename.is_relative_to(root)
        if entered_script and not in_script:
            break
        if in_script:
            relative = filename.relative_to(root).as_posix()
            entered_script = True
        else:
            relative = filename.name
        stack.append({
            "file": relative,
            "line": frame.f_lineno,
            "function": frame.f_code.co_name,
        })
        frame = frame.f_back

    location = stack[0] if stack else {"file": "", "line": 0, "function": ""}
    stack.reverse()
    return len(stack), location, stack


def _publish_event(event_type: str, **fields: Any) -> None:
    event = {"type": event_type, **fields}
    try:
        with _WEB_EVENT_LOCK:
            sys.stdout.write(_EVENT_PREFIX)
            sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            sys.stdout.write("\n")
            sys.stdout.flush()
    except (OSError, UnicodeError):
        return
