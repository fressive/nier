"""Selectable text-input backends for the ADB runtime.

The shell backend preserves the original ``adb shell input text`` behavior.
The optional IME backend talks to the Nier Android input method through an
ADB ``content call``.  It does not require a phone-side network service and
works independently of root access once the IME is installed and selected.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
import re
from typing import Protocol

from .adb import AdbClient
from .config import InputTextConfig, InputTextMode
from .errors import BackendUnavailable


class TextInputBackend(Protocol):
    """Backend used for one logical ``InputText`` action."""

    def send(self, text: str) -> None:
        """Send text to the currently focused editor."""
        ...

    def close(self) -> None:
        """Release or restore any backend-owned state."""
        ...


class ShellTextInputBackend:
    """Portable text input using Android's shell command."""

    def __init__(self, adb: AdbClient) -> None:
        self._adb = adb

    def send(self, text: str) -> None:
        self._adb.shell("input", "text", encode_shell_input_text(text))

    def close(self) -> None:
        pass


class ImeTextInputBackend:
    """Unicode-capable input through the optional Nier ``InputMethodService``."""

    def __init__(self, adb: AdbClient, config: InputTextConfig) -> None:
        self._adb = adb
        self._config = config
        self._ready = False
        self._switched = False
        self._previous_ime: str | None = None
        self._rooted: bool | None = None

    def send(self, text: str) -> None:
        self._ensure_ready()
        encoded = urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
        extra = f"text_b64:s:{encoded}"
        result = self._adb.run(
            "shell",
            "content",
            "call",
            "--uri",
            f"content://{self._config.provider_authority}",
            "--method",
            "commit_text",
            "--extra",
            extra,
            timeout=self._config.timeout_seconds,
            check=False,
        )
        output = "\n".join(
            value
            for value in (
                self._adb._decode(result.stdout).strip(),
                self._adb._decode(result.stderr).strip(),
            )
            if value
        )
        if result.returncode != 0:
            raise BackendUnavailable(
                output or f"IME content provider exited with {result.returncode}"
            )
        if not re.search(r"\bok\s*=\s*true\b", output, flags=re.IGNORECASE):
            raise BackendUnavailable(output or "IME content provider rejected the text")

    def close(self) -> None:
        if not self._ready:
            return
        try:
            if self._config.restore_previous and self._switched and self._previous_ime:
                current = self._read_current_ime()
                if current and _same_component(current, self._config.ime_component):
                    self._run_ime_command("set", self._previous_ime, check=False)
        except Exception:
            # Closing a session must remain best-effort, just like the
            # persistent uinput and Frida resources.
            pass
        finally:
            self._ready = False
            self._switched = False

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        current = self._read_current_ime()
        self._previous_ime = current
        if current and _same_component(current, self._config.ime_component):
            self._ready = True
            return
        if not self._config.auto_enable:
            raise BackendUnavailable(
                f"IME {self._config.ime_component} is not the current input method; "
                "enable it or set input_text.auto_enable=true"
            )

        try:
            self._run_ime_command("enable", self._config.ime_component)
            self._run_ime_command("set", self._config.ime_component)
            selected = self._read_current_ime()
            if not selected or not _same_component(selected, self._config.ime_component):
                raise BackendUnavailable(
                    f"Android did not select input method {self._config.ime_component}"
                )
        except Exception:
            if current and not _same_component(current, self._config.ime_component):
                self._run_ime_command("set", current, check=False)
            raise
        self._switched = True
        self._ready = True

    def _read_current_ime(self) -> str | None:
        result = self._adb.run(
            "shell",
            "settings",
            "get",
            "secure",
            "default_input_method",
            timeout=self._config.timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            detail = self._adb._decode(result.stderr).strip() or self._adb._decode(result.stdout).strip()
            raise BackendUnavailable(detail or "could not read the current input method")
        value = self._adb._decode(result.stdout).strip()
        return None if not value or value == "null" else value

    def _run_ime_command(self, command: str, value: str, *, check: bool = True) -> None:
        result = self._adb.run(
            "shell",
            "ime",
            command,
            value,
            timeout=self._config.timeout_seconds,
            check=False,
        )
        if result.returncode != 0 and self._is_rooted():
            root_shell = getattr(self._adb, "root_shell", None)
            if callable(root_shell):
                root_result = root_shell(
                    "ime",
                    command,
                    value,
                    timeout=self._config.timeout_seconds,
                    check=False,
                )
                if root_result.returncode == 0:
                    return
                result = root_result
        if check and result.returncode != 0:
            detail = self._adb._decode(result.stderr).strip() or self._adb._decode(result.stdout).strip()
            raise BackendUnavailable(detail or f"adb shell ime {command} failed")

    def _is_rooted(self) -> bool:
        if self._rooted is None:
            probe = getattr(self._adb, "is_root", None)
            self._rooted = bool(probe()) if callable(probe) else False
        return self._rooted


def create_text_input_backend(adb: AdbClient, config: InputTextConfig) -> TextInputBackend:
    """Create the configured text input implementation."""
    if config.mode is InputTextMode.IME:
        return ImeTextInputBackend(adb, config)
    return ShellTextInputBackend(adb)


def encode_shell_input_text(text: str) -> str:
    """Encode the subset of shell-input escaping supported by Android input."""
    return text.replace("%", "%25").replace(" ", "%s")


def _canonical_component(value: str) -> str:
    package, separator, service = value.strip().partition("/")
    if not separator or not package or not service:
        return value.strip()
    if service.startswith("."):
        service = package + service
    elif "." not in service:
        service = f"{package}.{service}"
    return f"{package}/{service}"


def _same_component(left: str, right: str) -> bool:
    return _canonical_component(left) == _canonical_component(right)
