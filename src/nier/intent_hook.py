"""LSPosed Intent capture over the configured ADB logcat connection."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from queue import Empty, Queue

from .adb import AdbClient
from .errors import HookError, HookUnavailable
from .protocol import normalize_activity_component, validate_package_name


_EVENT_PATTERN = re.compile(
    r"NIER_INTENT_V1\|([A-Za-z0-9_.-]+)\|(\d+)/(\d+)\|([A-Za-z0-9+/=]+)"
)
_MAX_EVENT_PARTS = 512
_MAX_PENDING_EVENTS = 32


@dataclass(frozen=True)
class IntentHookEvent:
    """One LSPosed status or Activity launch event for the selected package."""

    kind: str
    payload: Mapping[str, object]


class IntentEventAssembler:
    """Reassemble bounded Base64 JSON events split across logcat records."""

    def __init__(self) -> None:
        self._pending: dict[str, list[str | None]] = {}

    def feed(self, line: str) -> dict[str, object] | None:
        """Return a complete decoded event when ``line`` contains its last part."""
        match = _EVENT_PATTERN.search(line)
        if match is None:
            return None
        event_id, raw_part, raw_count, chunk = match.groups()
        part = int(raw_part)
        count = int(raw_count)
        if count < 1 or count > _MAX_EVENT_PARTS or part < 1 or part > count:
            self._pending.pop(event_id, None)
            return None

        parts = self._pending.get(event_id)
        if parts is None or len(parts) != count:
            if len(self._pending) >= _MAX_PENDING_EVENTS:
                self._pending.pop(next(iter(self._pending)))
            parts = [None] * count
            self._pending[event_id] = parts
        parts[part - 1] = chunk
        if any(item is None for item in parts):
            return None

        self._pending.pop(event_id, None)
        try:
            decoded = base64.b64decode("".join(item or "" for item in parts), validate=True)
            event = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            return None
        return event


class IntentHookSession:
    """Stream LSPosed Intent hook events from one configured ADB device."""

    def __init__(self, adb: AdbClient, package: str) -> None:
        self.package = validate_package_name(package)
        self._process = adb.start_logcat("NierIntentHook:I", "*:S")
        self._events: Queue[IntentHookEvent] = Queue()
        self._pending: deque[IntentHookEvent] = deque()
        self._assembler = IntentEventAssembler()
        self._closed = threading.Event()
        self._reader = threading.Thread(
            target=self._read_events,
            name="nier-lsposed-intent-logcat",
            daemon=True,
        )
        self._reader.start()

    def _read_events(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._events.put(
                IntentHookEvent("error", {"error": "ADB logcat has no output stream"})
            )
            return
        try:
            for line in stream:
                if self._closed.is_set():
                    return
                event = self._assembler.feed(line)
                if event is None:
                    continue
                process_name = event.get("process")
                process_package = (
                    process_name.split(":", 1)[0]
                    if isinstance(process_name, str)
                    else None
                )
                if event.get("package") != self.package and process_package != self.package:
                    continue
                kind = event.get("event")
                if not isinstance(kind, str):
                    continue
                payload = {key: value for key, value in event.items() if key != "event"}
                self._events.put(IntentHookEvent(kind, payload))
        except (OSError, ValueError) as exc:
            if not self._closed.is_set():
                self._events.put(IntentHookEvent("error", {"error": str(exc)}))
            return

        if not self._closed.is_set():
            return_code = self._process.poll()
            self._events.put(
                IntentHookEvent(
                    "error",
                    {"error": f"ADB logcat stopped unexpectedly (exit status {return_code})"},
                )
            )

    def wait_ready(self, timeout: float) -> None:
        """Wait until LSPosed reports that hooks were installed in this app."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HookUnavailable(
                    "LSPosed did not load the Nier module for this package; "
                    "enable Nier in LSPosed and add the package to its scope"
                )
            event = self.next_event(timeout=remaining)
            if event is None:
                raise HookUnavailable(
                    "LSPosed did not load the Nier module for this package; "
                    "enable Nier in LSPosed and add the package to its scope"
                )
            if event.kind == "module_ready":
                self._pending.append(event)
                return
            if event.kind == "module_error":
                raise HookUnavailable(
                    str(event.payload.get("error", "LSPosed could not install the Intent hooks"))
                )
            if event.kind == "error":
                raise HookError(str(event.payload.get("error", "ADB logcat failed")))
            self._pending.append(event)

    def next_event(self, timeout: float | None = None) -> IntentHookEvent | None:
        """Return the next matching event, or ``None`` when ``timeout`` expires."""
        if self._pending:
            return self._pending.popleft()
        try:
            if timeout is None:
                return self._events.get()
            return self._events.get(timeout=timeout)
        except Empty:
            return None

    def close(self) -> None:
        """Stop the host logcat process and its reader thread."""
        if self._closed.is_set():
            return
        self._closed.set()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.0)
        if self._process.stdout is not None:
            self._process.stdout.close()
        self._reader.join(timeout=1.0)


class LsposedIntentHook:
    """Listen for Intent events produced by the Nier LSPosed module."""

    def __init__(self, adb: AdbClient, *, timeout_seconds: float = 10.0) -> None:
        self._adb = adb
        self._timeout_seconds = timeout_seconds

    def attach(
        self,
        package: str,
        *,
        spawn: bool = False,
        activity: str | None = None,
    ) -> IntentHookSession:
        """Listen to a package and optionally restart it to activate LSPosed."""
        target = validate_package_name(package)
        if activity is not None and not spawn:
            raise ValueError("--activity requires --spawn")
        component = (
            normalize_activity_component(target, activity)
            if activity is not None
            else None
        )

        session = IntentHookSession(self._adb, target)
        try:
            if spawn:
                self._adb.shell("am", "force-stop", target, timeout=self._timeout_seconds)
                if activity is None:
                    output = self._adb.shell(
                        "monkey",
                        "-p",
                        target,
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                        timeout=self._timeout_seconds,
                    )
                    if "No activities found" in output or "monkey aborted" in output:
                        raise HookUnavailable(
                            f"no launchable Activity found for {target}; pass --activity"
                        )
                else:
                    assert component is not None
                    self._adb.shell(
                        "am",
                        "start",
                        "-n",
                        component,
                        timeout=self._timeout_seconds,
                    )
                session.wait_ready(self._timeout_seconds)
            return session
        except (HookError, HookUnavailable, ValueError):
            session.close()
            raise
        except Exception as exc:
            session.close()
            raise HookUnavailable(
                f"could not start LSPosed Intent hook for {target}: {exc}"
            ) from exc
        except BaseException:
            session.close()
            raise
