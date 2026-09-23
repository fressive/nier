from __future__ import annotations

from base64 import urlsafe_b64decode
import subprocess

import pytest

from nier.config import InputTextConfig, InputTextMode
from nier.errors import BackendUnavailable
from nier.input import ImeTextInputBackend, ShellTextInputBackend, create_text_input_backend


class FakeAdb:
    def __init__(self, current_ime: str, *, rooted: bool = False) -> None:
        self.current_ime = current_ime
        self.rooted = rooted
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _decode(value: bytes | None) -> str:
        return (value or b"").decode("utf-8", errors="replace")

    def shell(self, *args: str, **_kwargs) -> str:
        self.calls.append(args)
        return ""

    def is_root(self) -> bool:
        self.calls.append(("is_root",))
        return self.rooted

    def root_shell(self, *args: str, **_kwargs) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(("root_shell", *args))
        if args[:2] == ("ime", "set"):
            self.current_ime = args[2]
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def run(self, *args: str, **_kwargs) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(args)
        if args[:4] == ("shell", "settings", "get", "secure"):
            return subprocess.CompletedProcess(args, 0, f"{self.current_ime}\n".encode(), b"")
        if args[:2] == ("shell", "ime"):
            command, component = args[2:4]
            if self.rooted:
                return subprocess.CompletedProcess(args, 255, b"", b"permission denied")
            if command == "set":
                self.current_ime = component
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:3] == ("shell", "content", "call"):
            return subprocess.CompletedProcess(args, 0, b"Result: Bundle[{ok=true}]\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_ime_backend_commits_utf8_text_and_restores_previous_ime() -> None:
    adb = FakeAdb("com.android.inputmethod/.LatinIME")
    backend = ImeTextInputBackend(
        adb,  # type: ignore[arg-type]
        InputTextConfig(mode=InputTextMode.IME, auto_enable=True),
    )

    backend.send("你好 world")
    content_call = next(call for call in adb.calls if call[:3] == ("shell", "content", "call"))
    encoded = content_call[-1].removeprefix("text_b64:s:")
    assert urlsafe_b64decode(encoded).decode("utf-8") == "你好 world"
    assert adb.current_ime == "icu.rina.nier.backend/.NierInputMethodService"

    backend.close()

    assert adb.current_ime == "com.android.inputmethod/.LatinIME"


def test_ime_backend_requires_selected_ime_without_auto_enable() -> None:
    adb = FakeAdb("com.android.inputmethod/.LatinIME")
    backend = ImeTextInputBackend(
        adb,  # type: ignore[arg-type]
        InputTextConfig(mode=InputTextMode.IME, auto_enable=False),
    )

    with pytest.raises(BackendUnavailable, match="not the current input method"):
        backend.send("text")

    assert not any(call[:2] == ("shell", "content") for call in adb.calls)


def test_ime_backend_uses_root_for_ime_management_when_shell_is_denied() -> None:
    adb = FakeAdb("com.android.inputmethod/.LatinIME", rooted=True)
    backend = ImeTextInputBackend(
        adb,  # type: ignore[arg-type]
        InputTextConfig(mode=InputTextMode.IME, auto_enable=True),
    )

    backend.send("text")

    assert (
        "root_shell",
        "ime",
        "enable",
        "icu.rina.nier.backend/.NierInputMethodService",
    ) in adb.calls
    assert (
        "root_shell",
        "ime",
        "set",
        "icu.rina.nier.backend/.NierInputMethodService",
    ) in adb.calls


def test_text_input_backend_factory_preserves_shell_default() -> None:
    adb = FakeAdb("com.android.inputmethod/.LatinIME")
    backend = create_text_input_backend(adb, InputTextConfig())  # type: ignore[arg-type]

    assert isinstance(backend, ShellTextInputBackend)
    backend.send("hello world")
    assert ("input", "text", "hello%sworld") in adb.calls
