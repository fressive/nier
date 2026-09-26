from __future__ import annotations

import subprocess
from base64 import b64decode

import pytest

from nier.adb import AdbClient
from nier.backends.adb import AdbBackend, _unique_webview_bounds
from nier.config import DeviceConfig, HookConfig, HookMode
from nier.errors import BackendError, BackendUnavailable
from nier.hooks import HookCapabilities
from nier.protocol import (
    Click,
    DumpUiRequest,
    ImageFormat,
    InputText,
    Key,
    KeyCode,
    Point,
    Swipe,
)

PNG_1X1 = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_unique_webview_bounds_requires_one_native_webview() -> None:
    single = (
        '<hierarchy><node class="android.webkit.WebView" '
        'bounds="[12,34][512,934]" /></hierarchy>'
    )
    multiple = (
        '<hierarchy><node class="android.webkit.WebView" bounds="[0,0][10,10]" />'
        '<node class="com.example.WebView" bounds="[10,10][20,20]" /></hierarchy>'
    )
    duplicate_wrappers = (
        '<hierarchy><node class="android.webkit.WebView" bounds="[0,112][1239,2604]" />'
        '<node class="android.webkit.WebView" bounds="[0,112][1240,2604]" /></hierarchy>'
    )

    assert _unique_webview_bounds(single) == (12, 34, 512, 934)
    assert _unique_webview_bounds(multiple) is None
    assert _unique_webview_bounds(duplicate_wrappers) == (0, 112, 1239, 2604)


def test_adb_root_probe_accepts_root_adbd_and_uses_it_for_commands(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"0\n", b"")

    monkeypatch.setattr("nier.adb.subprocess.run", run)
    adb = AdbClient(DeviceConfig(serial="device"))

    assert adb.is_root() is True
    result = adb.root_shell("id", "-u")

    assert result.returncode == 0
    assert calls == [
        ["adb", "-s", "device", "shell", "id -u"],
        ["adb", "-s", "device", "shell", "id -u"],
    ]


def test_adb_root_probe_falls_back_to_standard_su(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs):
        calls.append(command)
        if command[-2:] == ["shell", "id -u"]:
            return subprocess.CompletedProcess(command, 0, b"2000\n", b"")
        if command[-2:] == ["shell", "su -M -c 'id -u'"]:
            return subprocess.CompletedProcess(command, 1, b"", b"invalid option")
        return subprocess.CompletedProcess(command, 0, b"0\n", b"")

    monkeypatch.setattr("nier.adb.subprocess.run", run)
    adb = AdbClient(DeviceConfig(serial="device"))

    assert adb.is_root() is True
    result = adb.root_shell("id", "-u")

    assert result.returncode == 0
    assert calls[-2:] == [
        ["adb", "-s", "device", "shell", "su -c 'id -u'"],
        ["adb", "-s", "device", "shell", "su -c 'id -u'"],
    ]


def test_adb_root_probe_preserves_mount_master_when_supported(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs):
        calls.append(command)
        if command[-2:] == ["shell", "id -u"]:
            return subprocess.CompletedProcess(command, 0, b"2000\n", b"")
        return subprocess.CompletedProcess(command, 0, b"0\n", b"")

    monkeypatch.setattr("nier.adb.subprocess.run", run)
    adb = AdbClient(DeviceConfig(serial="device"))

    assert adb.is_root() is True
    adb.root_shell("id", "-u")

    assert calls[-2:] == [
        ["adb", "-s", "device", "shell", "su -M -c 'id -u'"],
        ["adb", "-s", "device", "shell", "su -M -c 'id -u'"],
    ]


def fake_adb(monkeypatch):
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs):
        calls.append(command)
        joined = " ".join(command)
        if "connect" in command:
            endpoint = command[-1]
            return subprocess.CompletedProcess(command, 0, f"connected to {endpoint}\n".encode(), b"")
        if "exec-out" in command and "screencap" in command:
            return subprocess.CompletedProcess(command, 0, PNG_1X1, b"")
        if "exec-out" in command and "uiautomator" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                b"<?xml version='1.0'?><hierarchy />UI hierchary dumped to: /dev/stdout\n",
                b"",
            )
        if "get-state" in command:
            return subprocess.CompletedProcess(command, 0, b"device\n", b"")
        if "resolve-activity" in command:
            package = command[command.index("-p") + 1]
            component = f"{package}/com.example.launcher.LaunchActivity"
            return subprocess.CompletedProcess(
                command,
                0,
                f"priority=0 preferredOrder=0 match=0x108000\n{component}\n".encode(),
                b"",
            )
        if "am" in command and "start" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                b"Status: ok\nLaunchState: COLD\nActivity: com.example.app/com.example.launcher.LaunchActivity\n",
                b"",
            )
        if "wm size" in joined:
            return subprocess.CompletedProcess(command, 0, b"Physical size: 1080x1920\n", b"")
        if "getprop ro.product.model" in joined:
            return subprocess.CompletedProcess(command, 0, b"RMX3820\n", b"")
        if "settings get secure android_id" in joined:
            return subprocess.CompletedProcess(command, 0, b"test-device\n", b"")
        if "id -u" in joined:
            return subprocess.CompletedProcess(command, 0, b"0\n", b"")
        if "probe" in joined:
            return subprocess.CompletedProcess(command, 0, b"root=true\nwritable=true\npersistent=true\n", b"")
        if "cat /sdcard/nier-ui.xml" in joined:
            return subprocess.CompletedProcess(command, 0, b"<hierarchy />\n", b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    class FakePersistentShell:
        def request(self, command: str, *, timeout: float) -> None:
            calls.append(["persistent-request", command])

        def close(self) -> None:
            calls.append(["persistent-close"])

    def start_root_shell(_client, *args: str, timeout: float | None = None):
        calls.append(["persistent-start", *args])
        return FakePersistentShell()

    monkeypatch.setattr("nier.adb.subprocess.run", run)
    monkeypatch.setattr("nier.adb.AdbClient.start_root_shell", start_root_shell)
    return calls


def test_adb_backend_uses_direct_adb_and_phone_uinput(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device"))

    assert backend.health() is True
    capabilities = backend.capabilities()
    assert capabilities.device_id == "test-device"
    assert capabilities.screen_width == 1080
    assert capabilities.supports_uinput is True
    assert "list_apps" in capabilities.action_names
    assert "list_app_activities" in capabilities.action_names
    assert "open_app" in capabilities.action_names
    assert "start_activity" in capabilities.action_names

    backend.execute(Click(Point(0.5, 0.5, normalized=True)))
    backend.execute(Click(Point(0.25, 0.25, normalized=True)))
    backend.execute(Swipe((Point(10, 20), Point(30, 40)), duration_ms=120))
    backend.close()
    commands = [" ".join(call) for call in calls]
    assert sum(call[0] == "persistent-start" for call in calls) == 1
    assert any(call[0] == "persistent-request" and call[1].startswith("CLICK ") for call in calls)
    assert any(call[0] == "persistent-request" and call[1].startswith("SWIPE 120 2 ") for call in calls)
    assert any(call[0] == "persistent-close" for call in calls)
    assert any("su -M -c" not in command and "serve" in command for command in commands)
    assert not any(" forward " in f" {command} " or "startservice" in command for command in commands)


def test_adb_backend_falls_back_to_android_input(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    backend.execute(InputText("hello world"))
    backend.execute(Key(KeyCode.BACK))
    commands = [" ".join(call) for call in calls]
    assert any("shell input text hello%sworld" in command for command in commands)
    assert any("shell input keyevent 4" in command for command in commands)


def test_adb_fallback_click_honors_hold_duration(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    backend.execute(Click(Point(23, 31), duration_ms=900))
    backend.execute(Click(Point(23, 31), duration_ms=0))

    assert [
        "adb",
        "-s",
        "device",
        "shell",
        "input",
        "swipe",
        "23",
        "31",
        "23",
        "31",
        "900",
    ] in calls
    assert [
        "adb",
        "-s",
        "device",
        "shell",
        "input",
        "tap",
        "23",
        "31",
    ] in calls


def test_force_system_back_attaches_frida_before_back(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)

    class FakeHookSession:
        pid = 123

        def close(self) -> None:
            calls.append(["hook-close"])

    class FakeHook:
        capabilities = HookCapabilities(
            mode=HookMode.ROOT,
            can_inject=True,
            requires_app_integration=False,
            can_enable_webview_debugging=True,
        )

        def __init__(self) -> None:
            self.attach_calls = 0

        def attach(self, package: str, *, spawn: bool | None = None) -> FakeHookSession:
            assert package == "com.example.app"
            del spawn
            self.attach_calls += 1
            return FakeHookSession()

    hook = FakeHook()
    monkeypatch.setattr("nier.backends.adb.create_webview_hook", lambda *_args: hook)
    backend = AdbBackend(
        DeviceConfig(serial="device", use_uinput=False),
        hook_config=HookConfig(
            mode=HookMode.ROOT,
            target_package="com.example.app",
            force_system_back=True,
        ),
    )

    backend.execute(Key(KeyCode.BACK))
    backend.execute(Key(KeyCode.BACK))

    assert hook.attach_calls == 1
    commands = [" ".join(call) for call in calls]
    assert sum("shell input keyevent 4" in command for command in commands) == 2
    backend.close()
    assert any(call == ["hook-close"] for call in calls)


def test_adb_backend_connects_to_remote_device_over_tcp(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(
        DeviceConfig(
            remote_host="192.0.2.10",
            remote_port=5555,
            use_uinput=False,
        )
    )

    assert backend.health() is True
    backend.health()

    connect_calls = [call for call in calls if "connect" in call]
    assert connect_calls == [["adb", "connect", "192.0.2.10:5555"]]
    assert any(
        call[:3] == ["adb", "-s", "192.0.2.10:5555"] and "get-state" in call
        for call in calls
    )


def test_adb_backend_can_use_a_remote_adb_server(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(
        DeviceConfig(
            serial="remote-device",
            adb_server_host="192.0.2.20",
            adb_server_port=5038,
            use_uinput=False,
        )
    )

    assert backend.health() is True
    assert ["adb", "-H", "192.0.2.20", "-P", "5038", "-s", "remote-device", "get-state"] in calls


def test_adb_screenshot_uses_exec_out(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device"))

    screenshot = backend.screenshot()
    assert screenshot.format is ImageFormat.PNG
    assert (screenshot.width, screenshot.height) == (1, 1)
    assert screenshot.data == PNG_1X1
    assert any("exec-out" in call and "screencap" in call for call in calls)


def test_adb_dump_ui_uses_exec_out_without_a_device_file(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device"))

    dump = backend.dump_ui()
    assert dump.xml.endswith("<hierarchy />")
    assert dump.warning
    assert any(
        call[-4:] == ["uiautomator", "dump", "--compressed", "/dev/stdout"]
        for call in calls
    )
    assert not any("cat /sdcard/nier-ui.xml" in " ".join(call) for call in calls)


def test_adb_backend_uses_lsposed_ready_process_for_webview_dump(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)

    class FakeSession:
        pid = 321
        tcp_port = 9223

        def close(self) -> None:
            calls.append(["lsposed-session-close"])

    class FakeHook:
        capabilities = HookCapabilities(
            mode=HookMode.LSPOSED,
            can_inject=True,
            requires_app_integration=False,
            can_enable_webview_debugging=True,
        )

        def __init__(self) -> None:
            self.attach_calls = 0

        def attach(self, package: str, *, spawn: bool | None = None) -> FakeSession:
            assert package == "com.example.app"
            assert spawn is None
            self.attach_calls += 1
            return FakeSession()

    class FakeDevTools:
        def __init__(self, _adb, *, package, pid, tcp_port, timeout) -> None:
            assert package == "com.example.app"
            assert pid == 321
            assert tcp_port == 9223
            assert timeout == 10.0

        def dump_dom(self, **_kwargs) -> str:
            return "<html><body>lsposed</body></html>"

    hook = FakeHook()
    monkeypatch.setattr("nier.backends.adb.create_webview_hook", lambda *_args: hook)
    monkeypatch.setattr("nier.backends.adb.WebViewDevTools", FakeDevTools)
    backend = AdbBackend(
        DeviceConfig(serial="device", use_uinput=False),
        hook_config=HookConfig(
            mode=HookMode.LSPOSED,
            target_package="com.example.app",
        ),
    )

    dump = backend.dump_ui()

    assert dump.source.value == "WEBVIEW_DEVTOOLS"
    assert dump.xml == "<html><body>lsposed</body></html>"
    assert hook.attach_calls == 1
    backend.close()
    assert ["lsposed-session-close"] in calls


def test_adb_dump_ui_keeps_file_fallback_and_cleans_up(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device"))

    def unavailable(*args, **kwargs):
        del args, kwargs
        raise BackendUnavailable("exec-out unsupported")

    monkeypatch.setattr(backend.adb, "exec_out", unavailable)

    dump = backend.dump_ui(DumpUiRequest(prefer_webview=False))

    assert dump.xml == "<hierarchy />"
    assert any("uiautomator dump --compressed /sdcard/nier-ui.xml" in " ".join(call) for call in calls)
    assert any("rm -f /sdcard/nier-ui.xml" in " ".join(call) for call in calls)


def test_adb_backend_reads_current_activity(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device"))
    monkeypatch.setattr(
        backend.adb,
        "shell",
        lambda *args, **kwargs: (
            "topResumedActivity=ActivityRecord{abc u0 "
            "com.android.settings/.Settings t42}\n"
        ),
    )

    activity = backend.current_activity()

    assert activity is not None
    assert activity.package == "com.android.settings"
    assert activity.activity == "com.android.settings.Settings"
    assert activity.component == "com.android.settings/com.android.settings.Settings"
    assert activity.source == "top_resumed_activity"


def test_adb_backend_lists_apps_and_declared_activities(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    def shell(*args: str, **kwargs: object) -> str:
        del kwargs
        calls.append(["shell", *args])
        if args == ("pm", "list", "packages"):
            return "package:com.example.one\npackage:com.example.two\n"
        if args == ("dumpsys", "package", "com.example.one"):
            return (
                "Package [com.example.one]:\n"
                "  Activities:\n"
                "    Activity{abc com.example.one/.MainActivity}\n"
                "    Activity{def com.example.one/com.example.one.SettingsActivity}\n"
                "  Receivers:\n"
                "    Receiver{ghi com.example.one/.Receiver}\n"
            )
        raise AssertionError(args)

    monkeypatch.setattr(backend.adb, "shell", shell)

    assert backend.list_apps() == ["com.example.one", "com.example.two"]
    assert backend.list_app_activities("com.example.one") == [
        "com.example.one.MainActivity",
        "com.example.one.SettingsActivity",
    ]
    assert ["shell", "pm", "list", "packages"] in calls
    assert ["shell", "dumpsys", "package", "com.example.one"] in calls


def test_adb_backend_rejects_invalid_activity_package(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    with pytest.raises(ValueError, match="invalid Android package"):
        backend.list_app_activities("com.example.app; rm -rf /")


def test_adb_backend_can_open_apps_and_start_activities(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    assert backend.open_app("com.example.app").success is True
    assert backend.start_activity("com.example.app", ".MainActivity").success is True

    assert [
        "adb",
        "-s",
        "device",
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        "-p",
        "com.example.app",
    ] in calls
    assert [
        "adb",
        "-s",
        "device",
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        "com.example.app/com.example.launcher.LaunchActivity",
    ] in calls
    assert any(
        call[-5:]
        == [
            "shell",
            "am",
            "start",
            "-n",
            "com.example.app/com.example.app.MainActivity",
        ]
        for call in calls
    )


def test_adb_backend_force_stops_app_before_restart(monkeypatch) -> None:
    calls = fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    result = backend.open_app("com.example.app", restart=True)

    assert result.success is True
    force_stop_call = [
        "adb",
        "-s",
        "device",
        "shell",
        "am",
        "force-stop",
        "com.example.app",
    ]
    launch_call = [
        "adb",
        "-s",
        "device",
        "shell",
        "am",
        "start",
        "-W",
        "--activity-clear-task",
        "-n",
        "com.example.app/com.example.launcher.LaunchActivity",
    ]
    resolver_index = calls.index(
        [
            "adb",
            "-s",
            "device",
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-p",
            "com.example.app",
        ]
    )
    assert resolver_index < calls.index(force_stop_call) < calls.index(launch_call)


def test_adb_backend_reports_launch_errors(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    def shell(*args, **kwargs):
        if "resolve-activity" in args:
            return "com.example.app/com.example.app.MainActivity"
        return "Status: timeout\n"

    monkeypatch.setattr(backend.adb, "shell", shell)

    with pytest.raises(BackendError, match="open app"):
        backend.open_app("com.example.app")


def test_adb_backend_rejects_packages_without_a_launcher(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))
    monkeypatch.setattr(
        backend.adb,
        "shell",
        lambda *args, **kwargs: "No activity found",
    )

    with pytest.raises(BackendError, match="could not resolve launcher Activity"):
        backend.open_app("com.example.app")


def test_adb_backend_starts_nonexported_intent_through_root_shell(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))
    root_calls = []
    monkeypatch.setattr(backend.adb, "is_root", lambda: True)
    monkeypatch.setattr(
        backend.adb,
        "root_shell",
        lambda *args, **kwargs: (
            root_calls.append((args, kwargs))
            or subprocess.CompletedProcess(args, 0, b"Starting: Intent { }\n", b"")
        ),
    )

    result = backend.start_intent(
        {
            "component": {
                "package": "com.example.app",
                "class": "com.example.app.HiddenActivity",
                "exported": False,
            }
        },
        root=True,
    )

    assert result.success is True
    assert root_calls == [
        (
            (
                "am",
                "start",
                "-n",
                "com.example.app/com.example.app.HiddenActivity",
            ),
            {},
        )
    ]


def test_adb_backend_requires_root_before_a_root_intent_launch(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))
    monkeypatch.setattr(backend.adb, "is_root", lambda: False)
    root_calls = []
    monkeypatch.setattr(
        backend.adb,
        "root_shell",
        lambda *args, **kwargs: root_calls.append((args, kwargs)),
    )

    with pytest.raises(BackendUnavailable, match="root=True requires"):
        backend.start_intent({"component": None}, root=True)
    assert root_calls == []


def test_adb_backend_explains_nonexported_intent_denial(monkeypatch) -> None:
    fake_adb(monkeypatch)
    backend = AdbBackend(DeviceConfig(serial="device", use_uinput=False))

    def deny_shell(*_args, **_kwargs):
        raise BackendUnavailable(
            "Permission Denial: H5Activity not exported from uid 10292"
        )

    monkeypatch.setattr(backend.adb, "shell", deny_shell)

    with pytest.raises(BackendUnavailable, match="root=True"):
        backend.start_intent({"component": None})
