from __future__ import annotations

import base64
import io
import json

from nier.adb import AdbClient
from nier.config import DeviceConfig
from nier.intent_codegen import generate_intent_python
from nier.intent_hook import (
    IntentEventAssembler,
    IntentHookEvent,
    IntentHookSession,
    LsposedIntentHook,
)
from nier.protocol import normalize_intent


def _log_lines(event: dict[str, object], *, event_id: str = "42-1", width: int = 32) -> list[str]:
    payload = base64.b64encode(json.dumps(event).encode("utf-8")).decode("ascii")
    chunks = [payload[index : index + width] for index in range(0, len(payload), width)]
    return [
        f"I/NierIntentHook( 42): NIER_INTENT_V1|{event_id}|{index + 1}/{len(chunks)}|{chunk}"
        for index, chunk in enumerate(chunks)
    ]


def test_event_assembler_reassembles_out_of_order_logcat_parts() -> None:
    event = {"event": "intent", "package": "com.example.app", "intent": {"action": "go"}}
    lines = _log_lines(event)
    assembler = IntentEventAssembler()

    assert assembler.feed(lines[1]) is None
    assert assembler.feed(lines[0]) is None
    decoded = None
    for line in lines[2:]:
        decoded = assembler.feed(line)

    assert decoded == event


def test_event_assembler_ignores_invalid_chunks() -> None:
    assembler = IntentEventAssembler()

    assert (
        assembler.feed("I/NierIntentHook( 42): NIER_INTENT_V1|42-1|513/513|AAAA")
        is None
    )
    assert assembler.feed("ordinary logcat message") is None


def test_truncated_fields_are_omitted_from_generated_launch_code() -> None:
    intent = {
        "component": {
            "package": "com.example.app",
            "class": "com.example.app.DetailActivity",
        },
        "type": "application/example",
        "type_truncated": True,
        "categories": ["com.example.OPEN"],
        "categories_truncated": True,
        "extras": {},
    }

    snippet = generate_intent_python(intent)
    compile(snippet, "intent-hook-generated-example", "exec")

    assert "The captured MIME type was truncated and has been omitted." in snippet
    assert "Some Intent categories were omitted by the capture limit." in snippet
    assert "'type': None" in snippet
    assert "'categories': []" in snippet
    try:
        normalize_intent(intent)
    except ValueError as exc:
        assert "MIME type was truncated" in str(exc)
    else:
        raise AssertionError("direct Intent replay must reject truncated MIME types")


def test_start_logcat_uses_configured_adb_target(monkeypatch) -> None:
    commands = []

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        commands.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("nier.adb.subprocess.Popen", fake_popen)
    client = AdbClient(
        DeviceConfig(serial="device-123", adb_server_host="adb.example", adb_server_port=5040)
    )

    process = client.start_logcat("NierIntentHook:I", "*:S")

    assert isinstance(process, FakeProcess)
    assert commands == [
        (
            [
                "adb",
                "-H",
                "adb.example",
                "-P",
                "5040",
                "-s",
                "device-123",
                "logcat",
                "-T",
                "0",
                "-v",
                "brief",
                "NierIntentHook:I",
                "*:S",
            ],
            {
                "stdout": -1,
                "stderr": -2,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            },
        )
    ]


def test_spawn_restarts_package_and_uses_explicit_activity(monkeypatch) -> None:
    calls = []

    class FakeSession:
        def __init__(self, _adb, package):
            self.package = package
            self.ready_timeout = None
            self.closed = False

        def wait_ready(self, timeout):
            self.ready_timeout = timeout

        def close(self):
            self.closed = True

    class FakeAdb:
        def shell(self, *args, timeout=None):
            calls.append((args, timeout))
            return ""

    monkeypatch.setattr("nier.intent_hook.IntentHookSession", FakeSession)
    hook = LsposedIntentHook(FakeAdb(), timeout_seconds=2.5)  # type: ignore[arg-type]

    session = hook.attach(
        "com.example.app",
        spawn=True,
        activity=".DetailActivity",
    )

    assert session.package == "com.example.app"
    assert session.ready_timeout == 2.5
    assert calls == [
        (("am", "force-stop", "com.example.app"), 2.5),
        (("am", "start", "-n", "com.example.app/com.example.app.DetailActivity"), 2.5),
    ]


def test_spawn_interrupt_closes_logcat_session(monkeypatch) -> None:
    sessions = []

    class FakeSession:
        def __init__(self, _adb, _package):
            self.closed = False
            sessions.append(self)

        def wait_ready(self, _timeout):
            raise KeyboardInterrupt

        def close(self):
            self.closed = True

    class FakeAdb:
        def shell(self, *_args, **_kwargs):
            return ""

    monkeypatch.setattr("nier.intent_hook.IntentHookSession", FakeSession)
    hook = LsposedIntentHook(FakeAdb())  # type: ignore[arg-type]

    try:
        hook.attach("com.example.app", spawn=True)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("startup interrupt should propagate")

    assert sessions[0].closed


def test_session_filters_other_packages_and_decodes_events() -> None:
    events = [
        {"event": "module_ready", "package": "com.other.app", "pid": 10},
        {"event": "module_ready", "package": "com.example.app", "pid": 42},
        {
            "event": "intent",
            "package": "com.example.app",
            "source": "execStartActivity",
            "intent": {"action": "com.example.OPEN"},
        },
    ]
    lines = []
    for index, event in enumerate(events):
        lines.extend(_log_lines(event, event_id=f"42-{index}", width=60))

    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO("\n".join(lines) + "\n")
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

    process = FakeProcess()

    class FakeAdb:
        def start_logcat(self, *filters):
            assert filters == ("NierIntentHook:I", "*:S")
            return process

    session = IntentHookSession(FakeAdb(), "com.example.app")  # type: ignore[arg-type]
    try:
        assert session.next_event(timeout=1) == IntentHookEvent(
            "module_ready",
            {"package": "com.example.app", "pid": 42},
        )
        assert session.next_event(timeout=1) == IntentHookEvent(
            "intent",
            {
                "package": "com.example.app",
                "source": "execStartActivity",
                "intent": {"action": "com.example.OPEN"},
            },
        )
    finally:
        session.close()
