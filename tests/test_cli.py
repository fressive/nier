from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from nier import cli
from nier.config import AppConfig, DeviceConfig, HookConfig, HookMode, RuntimeConfig
from nier.intent_hook import IntentHookEvent
from nier.models.base import BoundingBox, TextSpan
from nier.protocol import ImageFormat, Screenshot, UiDump, UiSource
from nier.ui import parse_uidump


def test_cli_parses_device_tool_options_and_adb_remainder() -> None:
    parser = cli._parser()

    screenshot = parser.parse_args(
        [
            "screenshot",
            "--output",
            "screen.jpg",
            "--quality",
            "75",
            "--max-width",
            "800",
        ]
    )
    uidump = parser.parse_args(["uidump", "--format", "json", "--include-raw"])
    legacy_uidump = parser.parse_args(["dump-ui"])
    locate = parser.parse_args(
        ["locate", "icon", "icon.png", "--region", "1", "2", "3", "4"]
    )
    ocr = parser.parse_args(["ocr"])
    intent_hook = parser.parse_args(
        ["intent-hook", "--package", "com.example.app", "--spawn",
         "--activity", ".DetailActivity", "--once"]
    )
    adb = parser.parse_args(["adb", "exec-out", "screencap", "-p"])

    assert (screenshot.command, screenshot.quality, screenshot.max_width) == (
        "screenshot",
        75,
        800,
    )
    assert (uidump.command, uidump.format, uidump.include_raw) == (
        "uidump",
        "json",
        True,
    )
    assert legacy_uidump.command == "dump-ui"
    assert locate.region == [1, 2, 3, 4]
    assert ocr.command == "ocr"
    assert (
        intent_hook.command,
        intent_hook.package,
        intent_hook.spawn,
        intent_hook.activity,
        intent_hook.once,
    ) == ("intent-hook", "com.example.app", True, ".DetailActivity", True)
    assert adb.adb_args == ["exec-out", "screencap", "-p"]


def test_intent_hook_uses_lsposed_events_without_frida(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "nier.yaml"
    config = AppConfig(
        hook=HookConfig(
            mode=HookMode.NON_ROOT,
            target_package="com.example.app",
        )
    )
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)

    class FakeSession:
        def __init__(self):
            self.events = [
                IntentHookEvent(
                    "module_ready",
                    {
                        "pid": 123,
                        "hooks": 16,
                        "hook_sources": {
                            "Instrumentation": 4,
                            "ActivityThread": 1,
                        },
                    },
                ),
                IntentHookEvent(
                    "intent",
                    {
                        "source": "execStartActivity",
                        "intent": {
                            "component": {
                                "package": "com.example.app",
                                "class": "com.example.app.DetailActivity",
                            },
                            "action": "com.example.OPEN",
                            "data": None,
                            "type": None,
                            "package": None,
                            "flags": 0,
                            "categories": [],
                            "extras": {},
                        },
                    },
                ),
            ]
            self.closed = False

        def next_event(self, timeout=None):
            del timeout
            return self.events.pop(0) if self.events else None

        def close(self):
            self.closed = True

    session = FakeSession()
    hook_calls = []

    class FakeLsposedIntentHook:
        def __init__(self, adb, *, timeout_seconds):
            hook_calls.append(("init", timeout_seconds))

        def attach(self, package, *, spawn, activity):
            hook_calls.append(("attach", package, spawn, activity))
            return session

    monkeypatch.setattr(cli, "LsposedIntentHook", FakeLsposedIntentHook)
    args = SimpleNamespace(
        verbose=0,
        config=config_path,
        package=None,
        spawn=None,
        activity=None,
        once=True,
    )

    assert cli._run_intent_hook(args) == 0

    output = capsys.readouterr().out
    assert "Listening for LSPosed Intent events from com.example.app" in output
    assert "16 hooks; Instrumentation=4, ActivityThread=1" in output
    assert "Reusable Nier Python launch code:" in output
    assert "phone.start_intent(intent)" in output
    assert hook_calls == [("init", 10.0), ("attach", "com.example.app", False, None)]
    assert session.closed


def test_adb_passthrough_inherits_streams_and_uses_configured_target(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Completed", (), {"returncode": 7})()

    monkeypatch.setattr("nier.adb.subprocess.run", fake_run)
    client = cli.AdbClient(DeviceConfig(serial="configured", adb_server_port=5040))

    result = client.passthrough("exec-out", "screencap", "-p")

    assert result == 7
    assert calls == [
        (
            ["adb", "-P", "5040", "-s", "configured", "exec-out", "screencap", "-p"],
            {"check": False},
        )
    ]


def test_adb_passthrough_respects_explicit_target_and_server_commands(
    monkeypatch,
) -> None:
    commands = []
    monkeypatch.setattr(
        "nier.adb.subprocess.run",
        lambda command, **kwargs: (
            commands.append(command) or type("Completed", (), {"returncode": 0})()
        ),
    )
    client = cli.AdbClient(
        DeviceConfig(
            serial="configured", adb_server_host="adb.example", adb_server_port=5040
        )
    )

    client.passthrough("-s", "chosen", "shell", "getprop")
    client.passthrough("devices", "-l")

    assert commands[0] == [
        "adb",
        "-H",
        "adb.example",
        "-P",
        "5040",
        "-s",
        "chosen",
        "shell",
        "getprop",
    ]
    assert commands[1] == ["adb", "-H", "adb.example", "-P", "5040", "devices", "-l"]


def test_adb_passthrough_auto_connects_configured_remote_only_for_device_commands(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "nier.adb.subprocess.run",
        lambda command, **kwargs: type("Completed", (), {"returncode": 0})(),
    )
    client = cli.AdbClient(DeviceConfig(remote_host="192.0.2.10", auto_connect=True))
    monkeypatch.setattr(
        client, "_ensure_remote_connection", lambda: calls.append("connect")
    )

    client.passthrough("shell", "getprop")
    client.passthrough("devices", "-l")

    assert calls == ["connect"]


def test_adb_cli_returns_adb_exit_status(monkeypatch, tmp_path) -> None:
    config = AppConfig(runtime=RuntimeConfig(output_dir=tmp_path))
    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    class FakeAdbClient:
        def __init__(self, _device_config):
            pass

        def passthrough(self, *args):
            assert args == ("shell", "false")
            return 23

    monkeypatch.setattr(cli, "AdbClient", FakeAdbClient)

    assert cli.main(["adb", "shell", "false"]) == 23


@dataclass
class FakeCliDevice:
    screenshot_options: dict[str, object] = field(default_factory=dict)
    dump_options: dict[str, object] = field(default_factory=dict)
    formatted_documents: list[object] = field(default_factory=list)
    locate_calls: list[tuple[object, ...]] = field(default_factory=list)
    taps: list[int] = field(default_factory=list)
    ocr_spans: list[TextSpan] = field(default_factory=list)
    match: object | None = None
    closed: bool = False
    run_saved: bool = False

    def screenshot(self, path=None, **options):
        target = None if path is None else Path(path)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"image")
        self.screenshot_options = {"path": target, **options}
        image_format = (
            ImageFormat.JPEG
            if options.get("format") in {"jpg", "jpeg"}
            else ImageFormat.PNG
        )
        return Screenshot(
            b"image",
            image_format,
            800,
            600,
            "digest",
            _ocr_callback=lambda _image: self.ocr_spans,
        )

    def dump_ui(self, **options):
        self.dump_options = options
        return UiDump(
            '<hierarchy><node text="hello" /></hierarchy>',
            UiSource.UIAUTOMATOR,
        )

    def parse_uidump(self, dump):
        return parse_uidump(dump)

    def format_tree(self, document):
        self.formatted_documents.append(document)
        return "<hierarchy>\n└── node [text='hello']"

    def locate_text(self, query, *, min_score):
        self.locate_calls.append(("text", query, min_score))
        return self.match

    def locate_icon(self, template, *, min_score, region):
        self.locate_calls.append(("icon", template, min_score, region))
        return self.match

    def save_run(self):
        self.run_saved = True

    def close(self):
        self.closed = True


def _patch_cli_device(monkeypatch, tmp_path, device):
    config = AppConfig(runtime=RuntimeConfig(output_dir=tmp_path))
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "connect", lambda _config: device)
    return config


def test_screenshot_command_passes_options_and_saves_to_requested_path(
    monkeypatch, tmp_path, capsys
) -> None:
    device = FakeCliDevice()
    _patch_cli_device(monkeypatch, tmp_path, device)
    output = tmp_path / "nested" / "screen.jpg"

    assert (
        cli.main(
            [
                "screenshot",
                "--output",
                str(output),
                "--format",
                "jpeg",
                "--quality",
                "81",
                "--max-width",
                "900",
            ]
        )
        == 0
    )

    assert output.read_bytes() == b"image"
    assert device.screenshot_options == {
        "path": output,
        "format": "jpeg",
        "quality": 81,
        "max_width": 900,
        "max_height": 0,
    }
    assert "Screenshot saved to:" in capsys.readouterr().out
    assert device.closed and device.run_saved


def test_ocr_command_prints_text_confidence_and_screen_bounds(
    monkeypatch, tmp_path, capsys
) -> None:
    device = FakeCliDevice(
        ocr_spans=[
            TextSpan(
                text="设置",
                confidence=0.975,
                box=BoundingBox(left=40, top=80, right=220, bottom=140),
            )
        ]
    )
    _patch_cli_device(monkeypatch, tmp_path, device)

    assert cli.main(["ocr"]) == 0

    output = capsys.readouterr().out
    assert "OCR results (1 span):" in output
    assert "设置" in output
    assert "Confidence: 0.975" in output
    assert "Bounds: [40,80][220,140]" in output
    assert device.screenshot_options == {"path": None}
    assert device.closed and device.run_saved


def test_ocr_command_reports_empty_results(monkeypatch, tmp_path, capsys) -> None:
    device = FakeCliDevice()
    _patch_cli_device(monkeypatch, tmp_path, device)

    assert cli.main(["ocr"]) == 0

    assert capsys.readouterr().out.strip() == "No text recognized."
    assert device.closed and device.run_saved


def test_uidump_json_command_writes_parsed_tree_and_prints_formatted_tree(
    monkeypatch, tmp_path, capsys
) -> None:
    device = FakeCliDevice()
    _patch_cli_device(monkeypatch, tmp_path, device)
    output = tmp_path / "ui.json"

    assert cli.main(["uidump", "--format", "json", "--output", str(output)]) == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["source"] == "UIAUTOMATOR"
    assert document["root"]["children"][0]["text"] == "hello"
    assert device.dump_options == {"prefer_webview": True, "include_invisible": False}
    assert len(device.formatted_documents) == 1
    stdout = capsys.readouterr().out
    assert "UI dump saved to:" in stdout
    assert "UI hierarchy:\n<hierarchy>\n└── node [text='hello']" in stdout


def test_uidump_xml_command_prints_formatted_tree(monkeypatch, tmp_path, capsys) -> None:
    device = FakeCliDevice()
    _patch_cli_device(monkeypatch, tmp_path, device)
    output = tmp_path / "ui.xml"

    assert cli.main(["uidump", "--output", str(output)]) == 0

    assert output.read_text(encoding="utf-8") == (
        '<hierarchy><node text="hello" /></hierarchy>'
    )
    stdout = capsys.readouterr().out
    assert "UI hierarchy:\n<hierarchy>\n└── node [text='hello']" in stdout


@dataclass(frozen=True)
class FakeMatch:
    bounds: tuple[int, int, int, int] = (10, 20, 30, 40)
    center: tuple[float, float] = (20.0, 30.0)
    score: float = 0.91
    taps: list[int] = field(default_factory=list, compare=False)

    def click(self, *, duration_ms=80):
        self.taps.append(duration_ms)
        return type(
            "ActionResult",
            (),
            {"success": True, "message": "ok", "error_code": ""},
        )()


def test_locate_only_taps_when_requested(monkeypatch, tmp_path):
    match = FakeMatch()
    device = FakeCliDevice(match=match)
    _patch_cli_device(monkeypatch, tmp_path, device)

    assert cli.main(["locate", "text", "hello"]) == 0
    assert match.taps == []
    assert cli.main(["locate", "text", "hello", "--tap", "--tap-duration", "120"]) == 0
    assert match.taps == [120]
