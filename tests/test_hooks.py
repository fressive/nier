from __future__ import annotations

import subprocess

import pytest

from nier.config import HookConfig, HookMode
from nier.errors import HookUnavailable
from nier.hooks import (
    DEFAULT_WEBVIEW_SCRIPT,
    LsposedWebViewHook,
    NonRootWebViewHook,
    RootFridaWebViewHook,
    _load_webview_script,
    create_webview_hook,
)


class FakeAdb:
    def __init__(self, rooted: bool) -> None:
        self.rooted = rooted
        self.root_checks = 0
        self.root_shell_calls: list[tuple[str, ...]] = []

    def is_root(self) -> bool:
        self.root_checks += 1
        return self.rooted

    def root_shell(self, *args: str, timeout: float | None = None):
        del timeout
        self.root_shell_calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_explicit_non_root_mode_never_checks_root_or_injects() -> None:
    adb = FakeAdb(rooted=True)
    hook = create_webview_hook(HookConfig(mode=HookMode.NON_ROOT), adb)  # type: ignore[arg-type]

    assert isinstance(hook, NonRootWebViewHook)
    assert hook.capabilities.can_inject is False
    assert hook.capabilities.requires_app_integration is True
    assert adb.root_checks == 0
    with pytest.raises(HookUnavailable, match="cannot inject"):
        hook.attach("com.example.app")


def test_auto_mode_selects_root_or_non_root() -> None:
    rooted = create_webview_hook(HookConfig(), FakeAdb(rooted=True))  # type: ignore[arg-type]
    unrooted = create_webview_hook(HookConfig(), FakeAdb(rooted=False))  # type: ignore[arg-type]

    assert isinstance(rooted, RootFridaWebViewHook)
    assert rooted.capabilities.can_inject is True
    assert isinstance(unrooted, NonRootWebViewHook)


def test_lsposed_mode_checks_module_readiness_without_root_or_frida() -> None:
    class FakeLsposedAdb(FakeAdb):
        def __init__(self) -> None:
            super().__init__(rooted=False)
            self.commands: list[tuple[str, ...]] = []

        def is_root(self) -> bool:
            raise AssertionError("LSPosed mode must not check root access")

        def shell(self, *args: str, **_kwargs) -> str:
            self.commands.append(args)
            if args[:2] == ("pidof", "com.example.app"):
                return "123\n"
            if args[:2] == ("logcat", "-d"):
                return (
                    "I/NierWebViewHook( 123): "
                    "NIER_WEBVIEW_V1|READY|com.example.app|123|com.example.app\n"
                )
            raise AssertionError(f"unexpected command: {args}")

    adb = FakeLsposedAdb()
    hook = create_webview_hook(
        HookConfig(mode=HookMode.LSPOSED, target_package="com.example.app"),
        adb,  # type: ignore[arg-type]
    )

    assert isinstance(hook, LsposedWebViewHook)
    assert hook.capabilities.can_enable_webview_debugging is True
    session = hook.attach()
    assert session.pid == 123  # type: ignore[attr-defined]
    assert adb.commands == [
        ("pidof", "com.example.app"),
        ("logcat", "-d", "-t", "2000", "-s", "NierWebViewHook:I"),
    ]


def test_lsposed_mode_explains_missing_module_scope() -> None:
    class FakeLsposedAdb(FakeAdb):
        def shell(self, *args: str, **_kwargs) -> str:
            if args[:2] == ("pidof", "com.example.app"):
                return "123\n"
            return ""

    hook = LsposedWebViewHook(
        FakeLsposedAdb(rooted=True),
        HookConfig(mode=HookMode.LSPOSED, target_package="com.example.app"),
    )

    with pytest.raises(HookUnavailable, match="add the package to its scope"):
        hook.attach()


def test_lsposed_mode_reports_module_hook_errors() -> None:
    class FakeLsposedAdb(FakeAdb):
        def shell(self, *args: str, **_kwargs) -> str:
            if args[:2] == ("pidof", "com.example.app"):
                return "123\n"
            return (
                "E/NierWebViewHook( 123): "
                "NIER_WEBVIEW_V1|ERROR|com.example.app|123|NoSuchMethodException\n"
            )

    hook = LsposedWebViewHook(
        FakeLsposedAdb(rooted=True),
        HookConfig(mode=HookMode.LSPOSED, target_package="com.example.app"),
    )

    with pytest.raises(HookUnavailable, match="NoSuchMethodException"):
        hook.attach()


def test_root_mode_rejects_unrooted_device_before_loading_frida() -> None:
    hook = RootFridaWebViewHook(FakeAdb(rooted=False), HookConfig(mode=HookMode.ROOT))  # type: ignore[arg-type]

    with pytest.raises(HookUnavailable, match="rooted device"):
        hook.attach("com.example.app")


def test_default_agent_enables_webview_debugging() -> None:
    assert "setWebContentsDebuggingEnabled" in DEFAULT_WEBVIEW_SCRIPT
    assert "Java.scheduleOnMainThread" in DEFAULT_WEBVIEW_SCRIPT
    assert "type: 'ready'" in DEFAULT_WEBVIEW_SCRIPT


def test_force_system_back_is_injected_into_the_frida_agent() -> None:
    script = _load_webview_script(
        force_system_back=True,
        target_package="com.example.authorized.app",
    )

    assert "const NIER_FORCE_SYSTEM_BACK = true;" in script
    assert 'const NIER_TARGET_PACKAGE = "com.example.authorized.app";' in script
    assert "OnBackInvokedDispatcher" in script
    assert "OnBackPressedDispatcher" in script
    assert "ClassLoader.loadClass" in script


def test_default_frida_agent_does_not_install_back_override() -> None:
    script = _load_webview_script(target_package="com.example.app")

    assert "const NIER_FORCE_SYSTEM_BACK = false;" in script
    assert "const backHooks = NIER_FORCE_SYSTEM_BACK ? installForceSystemBack() : [];" in script


def test_root_hook_passes_back_policy_to_frida_script(monkeypatch) -> None:
    class FakeScript:
        def __init__(self, source: str) -> None:
            self.source = source
            self.callback = None

        def on(self, _event: str, callback) -> None:
            self.callback = callback

        def load(self) -> None:
            assert self.callback is not None
            self.callback({"type": "send", "payload": {"type": "ready"}}, None)

        def unload(self) -> None:
            pass

    class FakeFridaSession:
        def __init__(self) -> None:
            self.script: FakeScript | None = None

        def create_script(self, source: str) -> FakeScript:
            self.script = FakeScript(source)
            return self.script

        def detach(self) -> None:
            pass

    class FakeProcess:
        pid = 123

    class FakeDevice:
        def __init__(self) -> None:
            self.session = FakeFridaSession()

        def get_process(self, _package: str) -> FakeProcess:
            return FakeProcess()

        def attach(self, _pid: int) -> FakeFridaSession:
            return self.session

    class FakeFrida:
        def __init__(self) -> None:
            self.device = FakeDevice()

        def get_usb_device(self, *, timeout: int) -> FakeDevice:
            del timeout
            return self.device

    fake_frida = FakeFrida()
    monkeypatch.setattr("nier.hooks._load_frida", lambda: fake_frida)
    adb = FakeAdb(rooted=True)
    hook = RootFridaWebViewHook(
        adb,
        HookConfig(
            mode=HookMode.ROOT,
            target_package="com.example.authorized.app",
            force_system_back=True,
        ),
    )

    session = hook.attach()

    assert session.pid == 123  # type: ignore[attr-defined]
    assert fake_frida.device.session.script is not None
    assert "const NIER_FORCE_SYSTEM_BACK = true;" in fake_frida.device.session.script.source
    assert len(adb.root_shell_calls) == 1
    startup_command = adb.root_shell_calls[0][2]
    assert "pidof frida-server" in startup_command
    assert "/data/local/tmp/frida-server" in startup_command


def test_root_hook_resolves_package_pid_through_adb(monkeypatch) -> None:
    class FakeAdbWithPid(FakeAdb):
        def shell(self, *args: str, **_kwargs) -> str:
            assert args == ("pidof", "com.example.authorized.app")
            return "456\n"

    class FakeScript:
        def on(self, _event: str, callback) -> None:
            callback({"type": "send", "payload": {"type": "ready"}}, None)

        def load(self) -> None:
            pass

        def unload(self) -> None:
            pass

    class FakeSession:
        def create_script(self, _source: str) -> FakeScript:
            return FakeScript()

        def detach(self) -> None:
            pass

    class FakeDevice:
        def attach(self, pid: int) -> FakeSession:
            assert pid == 456
            return FakeSession()

        def get_process(self, _package: str):
            raise AssertionError("package-name lookup should not be needed")

    class FakeFrida:
        def get_usb_device(self, *, timeout: int) -> FakeDevice:
            del timeout
            return FakeDevice()

    monkeypatch.setattr("nier.hooks._load_frida", lambda: FakeFrida())
    adb = FakeAdbWithPid(rooted=True)
    hook = RootFridaWebViewHook(
        adb,
        HookConfig(
            mode=HookMode.ROOT,
            target_package="com.example.authorized.app",
            auto_start_frida_server=False,
        ),
    )

    session = hook.attach()
    session.close()
    assert adb.root_shell_calls == []
