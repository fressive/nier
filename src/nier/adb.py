"""Small, direct ADB client used by the default host-side backend."""

from __future__ import annotations

import select
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .config import DeviceConfig
from .errors import BackendError, BackendUnavailable
from .logging_utils import request as log_request
from .logging_utils import response as log_response


@dataclass
class AdbClient:
    """Run commands through ADB and manage an optional persistent shell.

    Normal operations use individual ``adb shell`` commands. Rooted touch
    injection can additionally use a long-lived stdin/stdout shell running the
    ``nier-uinput serve`` command; this is a pipe, not a device-side network
    server or Android service. The optional IME text backend is the one
    explicit exception: it talks to the installed Nier InputMethodService
    through ``adb shell content call`` when configured.
    """

    config: DeviceConfig
    _remote_connected: bool = field(default=False, init=False, repr=False)
    _root_shell_mode: str | None = field(default=None, init=False, repr=False)

    def _base(self, *, include_serial: bool = True) -> list[str]:
        command = [self.config.adb_path]
        if self.config.adb_server_host:
            command.extend(["-H", self.config.adb_server_host, "-P", str(self.config.adb_server_port)])
        if include_serial:
            serial = self._target_serial()
            if serial:
                command.extend(["-s", serial])
        return command

    def _target_serial(self) -> str | None:
        if self.config.remote_host:
            host = self.config.remote_host
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            return f"{host}:{self.config.remote_port}"
        return self.config.serial

    def _ensure_remote_connection(self) -> None:
        if not self.config.remote_host or not self.config.auto_connect or self._remote_connected:
            return

        endpoint = self._target_serial()
        assert endpoint is not None
        result = self._run_process(
            [*self._base(include_serial=False), "connect", endpoint],
            timeout=self.config.connect_timeout_seconds,
        )
        output = " ".join(
            part for part in (self._decode(result.stdout), self._decode(result.stderr)) if part
        ).strip()
        normalized = output.lower()
        connected = f"connected to {endpoint}".lower() in normalized
        already_connected = f"already connected to {endpoint}".lower() in normalized
        if result.returncode != 0 or not (connected or already_connected):
            raise BackendUnavailable(output or f"ADB could not connect to {endpoint}")
        self._remote_connected = True

    def _run_process(
        self,
        command: list[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=False,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(f"ADB command failed: {exc}") from exc

    def run(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run one ADB command and return its raw result."""
        self._ensure_remote_connection()
        channel = args[0] if args else "command"
        log_request("adb", channel, "<configured-device>", arg_count=len(args))
        result = self._run_process(
            [*self._base(), *args],
            timeout=self.config.connect_timeout_seconds if timeout is None else timeout,
        )
        log_response(
            "adb",
            result.returncode,
            target="<configured-device>",
            stdout_bytes=len(result.stdout or b""),
            stderr_bytes=len(result.stderr or b""),
        )
        if check and result.returncode != 0:
            detail = self._decode(result.stderr).strip() or self._decode(result.stdout).strip()
            raise BackendUnavailable(detail or f"ADB exited with {result.returncode}")
        return result

    def passthrough(self, *args: str) -> int:
        """Run an ADB command with stdin, stdout, and stderr attached.

        Unlike :meth:`run`, this method does not capture output, so it can
        stream binary data and long-running commands such as ``logcat``. The
        configured ADB server and device are selected by default for
        device-scoped commands; explicit ADB selectors in ``args`` take
        precedence. ADB server-management commands are passed through without
        adding the configured device or auto-connecting a remote target.
        """
        if not args:
            raise ValueError("an ADB command is required")

        value_options = {"-s", "-t", "-H", "-P", "-L", "--one-device"}
        explicit_selector = False
        explicit_server = False
        command: str | None = None
        skip_value = False
        for argument in args:
            if skip_value:
                skip_value = False
                continue
            if argument in value_options:
                skip_value = True
                explicit_selector = explicit_selector or argument in {"-s", "-t"}
                explicit_server = explicit_server or argument in {"-H", "-P", "-L"}
                continue
            if argument in {"-d", "-e"}:
                explicit_selector = True
                continue
            if argument.startswith("--serial="):
                explicit_selector = True
                continue
            if argument.startswith(("-H", "-P", "-L")) and len(argument) > 2:
                explicit_server = True
                continue
            if argument.startswith("-"):
                continue
            command = argument
            break

        server_commands = {
            "connect",
            "devices",
            "disconnect",
            "help",
            "kill-server",
            "start-server",
            "version",
        }
        device_scoped = command is not None and command not in server_commands

        if (
            device_scoped
            and not explicit_selector
            and not explicit_server
            and self.config.remote_host
            and self.config.auto_connect
        ):
            self._ensure_remote_connection()

        adb_command = [self.config.adb_path]
        if not explicit_server:
            if self.config.adb_server_host:
                adb_command.extend(["-H", self.config.adb_server_host])
            if self.config.adb_server_port != 5037:
                adb_command.extend(["-P", str(self.config.adb_server_port)])
        if device_scoped and not explicit_selector:
            serial = self._target_serial()
            if serial:
                adb_command.extend(["-s", serial])
        adb_command.extend(args)

        try:
            result = subprocess.run(adb_command, check=False)
        except OSError as exc:
            raise BackendUnavailable(f"ADB command failed: {exc}") from exc
        return result.returncode

    def start_logcat(self, *filters: str) -> subprocess.Popen[str]:
        """Start a configured-device logcat stream for a host-side reader."""
        self._ensure_remote_connection()
        command = [*self._base(), "logcat", "-T", "0", "-v", "brief", *filters]
        try:
            return subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise BackendUnavailable(f"could not start ADB logcat: {exc}") from exc

    @staticmethod
    def _decode(value: bytes | None) -> str:
        return (value or b"").decode("utf-8", errors="replace")

    def text(self, *args: str, timeout: float | None = None, check: bool = True) -> str:
        return self._decode(self.run(*args, timeout=timeout, check=check).stdout)

    def shell(self, *args: str, timeout: float | None = None, check: bool = True) -> str:
        return self.text("shell", *args, timeout=timeout, check=check)

    def shell_bytes(self, *args: str, timeout: float | None = None, check: bool = True) -> bytes:
        return self.run("shell", *args, timeout=timeout, check=check).stdout

    def exec_out(self, *args: str, timeout: float | None = None, check: bool = True) -> bytes:
        return self.run("exec-out", *args, timeout=timeout, check=check).stdout

    def root_shell(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a safely quoted command through the root ADB shell or ``su``."""
        if not args:
            raise ValueError("root_shell requires a command")
        remote = self._root_shell_command(args)
        return self.run("shell", remote, timeout=timeout, check=check)

    def _root_shell_command(self, args: tuple[str, ...]) -> str:
        command = shlex.join(args)
        if self._root_shell_mode == "adb":
            return command
        su_prefix = "su -c" if self._root_shell_mode == "su" else "su -M -c"
        return f"{su_prefix} {shlex.quote(command)}"

    def start_root_shell(self, *args: str, timeout: float | None = None) -> PersistentRootShell:
        """Start a root shell whose stdin/stdout stay attached to the host.

        The remote command is expected to speak a line-oriented protocol and
        print ``READY`` before accepting commands. The caller owns the
        returned process and must close it.
        """
        if not args:
            raise ValueError("start_root_shell requires a command")
        self._ensure_remote_connection()
        remote = self._root_shell_command(args)
        try:
            process = subprocess.Popen(
                [*self._base(), "shell", remote],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise BackendUnavailable(f"failed to start persistent ADB shell: {exc}") from exc

        shell = PersistentRootShell(process)
        try:
            shell.wait_ready(self.config.connect_timeout_seconds if timeout is None else timeout)
        except Exception:
            shell.close()
            raise
        return shell

    def ensure_device(self) -> None:
        state = self.text("get-state", timeout=self.config.connect_timeout_seconds).strip()
        if state != "device":
            raise BackendUnavailable(f"ADB device is not ready: {state or 'unknown'}")

    def is_root(self) -> bool:
        """Check root access through adbd, ``su -M``, or standard ``su -c``."""
        probes = (
            ("adb", "id -u"),
            ("su-m", f"su -M -c {shlex.quote('id -u')}"),
            ("su", f"su -c {shlex.quote('id -u')}"),
        )
        for mode, command in probes:
            result = self.run("shell", command, check=False)
            if result.returncode == 0 and self._decode(result.stdout).strip() == "0":
                self._root_shell_mode = mode
                return True
        return False

    def root_command_available(self, *args: str) -> bool:
        result = self.root_shell(*args, check=False)
        return result.returncode == 0


class PersistentRootShell:
    """Line-oriented stdin/stdout wrapper for a persistent ``adb shell``."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._process: subprocess.Popen | None = process
        self._lock = threading.RLock()

    def wait_ready(self, timeout: float) -> None:
        with self._lock:
            response = self._read_line_locked(timeout)
            if response != "READY":
                raise BackendUnavailable(f"persistent ADB shell did not become ready: {response}")

    def request(self, command: str, *, timeout: float) -> None:
        if "\n" in command or "\r" in command:
            raise ValueError("persistent shell commands must be single-line")
        with self._lock:
            response = self._request_locked(command, timeout)
            if response == "OK":
                return
            if response.startswith("ERR "):
                raise BackendError(response[4:] or "persistent uinput command failed")
            raise BackendUnavailable(f"unexpected persistent ADB shell response: {response}")

    def close(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            try:
                if process.poll() is None:
                    try:
                        self._request_locked("CLOSE", timeout=2.0)
                    except Exception:
                        pass
                    self._close_stdin(process)
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=1.0)
                else:
                    self._close_stdin(process)
            finally:
                self._process = None

    def _request_locked(self, command: str, timeout: float) -> str:
        process = self._ensure_process_locked()
        if process.stdin is None:
            raise BackendUnavailable("persistent ADB shell has no stdin")
        try:
            process.stdin.write((command + "\n").encode("utf-8"))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise BackendUnavailable(self._failure_detail_locked("persistent ADB shell write failed")) from exc
        return self._read_line_locked(timeout)

    def _read_line_locked(self, timeout: float) -> str:
        process = self._ensure_process_locked()
        if process.stdout is None:
            raise BackendUnavailable("persistent ADB shell has no stdout")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendUnavailable("persistent ADB shell timed out")
            try:
                readable, _, _ = select.select([process.stdout], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise BackendUnavailable("persistent ADB shell became unreadable") from exc
            if not readable:
                raise BackendUnavailable("persistent ADB shell timed out")
            line = process.stdout.readline()
            if not line:
                raise BackendUnavailable(self._failure_detail_locked("persistent ADB shell exited"))
            return AdbClient._decode(line).rstrip("\r\n")

    def _ensure_process_locked(self) -> subprocess.Popen:
        process = self._process
        if process is None:
            raise BackendUnavailable("persistent ADB shell is closed")
        if process.poll() is not None:
            raise BackendUnavailable(self._failure_detail_locked("persistent ADB shell exited"))
        return process

    def _failure_detail_locked(self, fallback: str) -> str:
        process = self._process
        if process is None or process.poll() is None or process.stderr is None:
            return fallback
        detail = AdbClient._decode(process.stderr.read()).strip()
        return detail or f"{fallback} (exit code {process.returncode})"

    @staticmethod
    def _close_stdin(process: subprocess.Popen) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
