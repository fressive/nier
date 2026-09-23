"""Chrome DevTools Protocol access for Android WebViews.

The Android WebView DevTools endpoint is an abstract Unix socket owned by the
target application.  This module forwards that socket to a temporary loopback
port on the host, discovers a page target, and uses the small subset of CDP
needed to return the WebView DOM.  It deliberately does not open a listening
socket on the device.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import http.client
import json
import re
import secrets
import socket
import struct
import time
from typing import Any
from urllib.parse import urlsplit

from .adb import AdbClient
from .errors import BackendError, BackendUnavailable, ProtocolError
from .logging_utils import request as log_request
from .logging_utils import response as log_response


_CDP_SOCKET_PREFIX = "webview_devtools_remote"
_MAX_HTTP_BYTES = 4 * 1024 * 1024
_MAX_FRAME_BYTES = 32 * 1024 * 1024
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass(frozen=True)
class DevToolsTarget:
    """A page target returned by the CDP HTTP discovery endpoint."""

    websocket_url: str
    target_type: str = ""
    title: str = ""
    url: str = ""


class WebViewDevTools:
    """Dump a debug-enabled Android WebView through Chrome DevTools Protocol.

    ``package`` is used to find the application process.  Callers that have
    already attached a root Frida session may pass ``pid`` instead.  A
    concrete ``socket_name`` is also accepted for applications that expose a
    custom WebView DevTools socket.
    """

    def __init__(
        self,
        adb: AdbClient,
        *,
        package: str | None = None,
        pid: int | None = None,
        socket_name: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not package and pid is None and not socket_name:
            raise ValueError("package, pid, or socket_name is required")
        if pid is not None and pid <= 0:
            raise ValueError("pid must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._adb = adb
        self._package = package.strip() if package else None
        self._pid = pid
        self._socket_name = _clean_socket_name(socket_name) if socket_name else None
        self._timeout = timeout

    def dump_dom(self) -> str:
        """Return the current WebView document as HTML/XML text."""
        socket_name = self._resolve_socket()
        forward = _AdbForward(self._adb, socket_name, timeout=self._timeout)
        with forward:
            port = forward.local_port
            if port is None:  # pragma: no cover - guarded by _AdbForward.__enter__
                raise BackendUnavailable("ADB WebView DevTools forward was not created")
            target = self._discover_target(port)
            path = _websocket_path(target.websocket_url)
            websocket = _WebSocketClient.connect(
                "127.0.0.1",
                port,
                path,
                timeout=self._timeout,
            )
            try:
                cdp = _CdpClient(websocket, timeout=self._timeout)
                return cdp.dump_document()
            finally:
                websocket.close()

    def _resolve_socket(self) -> str:
        if self._socket_name:
            return self._socket_name

        deadline = time.monotonic() + self._timeout
        pid = self._pid
        if pid is None:
            pid = self._find_pid(deadline)

        expected = f"{_CDP_SOCKET_PREFIX}_{pid}"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                target = self._package or str(pid)
                raise BackendUnavailable(
                    f"no WebView DevTools socket found for {target} before the timeout"
                )
            names = self._list_socket_names(remaining)
            matching = [
                name
                for name in names
                if name == expected or name.startswith(expected + "_")
            ]
            if matching:
                return matching[0]
            time.sleep(min(0.1, remaining))

    def _find_pid(self, deadline: float) -> int:
        if not self._package:
            raise BackendUnavailable("a package or pid is required to find the WebView process")
        remaining = max(0.1, deadline - time.monotonic())
        output = self._shell_text(("pidof", self._package), timeout=remaining)
        pids = [int(value) for value in re.findall(r"\b\d+\b", output)]
        if pids:
            return pids[0]

        # Some older Android images do not ship pidof in the shell PATH.  The
        # ps fallback keeps the non-root cooperative path usable there.
        output = self._shell_text(("ps", "-A"), timeout=remaining)
        for line in output.splitlines():
            if not re.search(rf"(?:^|\s){re.escape(self._package)}(?:\s|$)", line):
                continue
            fields = line.split()
            for field in fields[1:3]:
                if field.isdigit():
                    return int(field)
        raise BackendUnavailable(f"could not find a running process for {self._package}")

    def _list_socket_names(self, timeout: float) -> list[str]:
        output = self._shell_text(("cat", "/proc/net/unix"), timeout=timeout)
        names: list[str] = []
        for match in re.finditer(r"@?(webview_devtools_remote[^\s]*)", output):
            name = _clean_socket_name(match.group(1))
            if name and name not in names:
                names.append(name)
        return names

    def _shell_text(self, args: Sequence[str], *, timeout: float) -> str:
        result = self._adb.run("shell", *args, timeout=timeout, check=False)
        if result.returncode != 0:
            return ""
        return (result.stdout or b"").decode("utf-8", errors="replace")

    def _discover_target(self, port: int) -> DevToolsTarget:
        last_error: Exception | None = None
        for endpoint in ("/json/list", "/json"):
            try:
                payload = _get_json("127.0.0.1", port, endpoint, timeout=self._timeout)
                return _select_target(payload)
            except (BackendError, ProtocolError) as exc:
                last_error = exc
        raise BackendUnavailable(
            f"the forwarded WebView DevTools endpoint did not expose a page target: {last_error}"
        ) from last_error


def _clean_socket_name(value: str) -> str:
    return value.lstrip("@\x00")


def _select_target(payload: Any) -> DevToolsTarget:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        raise ProtocolError("WebView DevTools target list is not an array")
    candidates: list[DevToolsTarget] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        websocket_url = item.get("webSocketDebuggerUrl")
        if not isinstance(websocket_url, str) or not websocket_url:
            continue
        target = DevToolsTarget(
            websocket_url=websocket_url,
            target_type=str(item.get("type", "")),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
        )
        candidates.append(target)
    if not candidates:
        raise ProtocolError("WebView DevTools returned no WebSocket page target")
    for candidate in candidates:
        if candidate.target_type in {"page", "webview"}:
            return candidate
    return candidates[0]


def _websocket_path(websocket_url: str) -> str:
    parsed = urlsplit(websocket_url)
    if parsed.scheme != "ws":
        raise ProtocolError(f"unsupported WebView DevTools WebSocket scheme: {parsed.scheme}")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


def _get_json(host: str, port: int, path: str, *, timeout: float) -> Any:
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    target = f"http://{host}:{port}{path}"
    log_request("http", "GET", target, headers={"Connection": "close"})
    try:
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(_MAX_HTTP_BYTES + 1)
        log_response(
            "http",
            response.status,
            target=target,
            headers=response.headers,
            body=body,
        )
        if len(body) > _MAX_HTTP_BYTES:
            raise ProtocolError("WebView DevTools discovery response is too large")
        if response.status != 200:
            raise BackendUnavailable(
                f"WebView DevTools discovery returned HTTP {response.status}"
            )
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("WebView DevTools discovery returned invalid JSON") from exc
    except (OSError, TimeoutError) as exc:
        raise BackendUnavailable(f"could not query WebView DevTools discovery: {exc}") from exc
    finally:
        connection.close()


class _AdbForward:
    def __init__(self, adb: AdbClient, socket_name: str, *, timeout: float) -> None:
        self._adb = adb
        self._socket_name = socket_name
        self._timeout = timeout
        self.local_port: int | None = None

    def __enter__(self) -> _AdbForward:
        self.local_port = _free_local_port()
        try:
            self._adb.run(
                "forward",
                f"tcp:{self.local_port}",
                f"localabstract:{self._socket_name}",
                timeout=self._timeout,
            )
        except Exception:
            self.local_port = None
            raise
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        port = self.local_port
        self.local_port = None
        if port is None:
            return
        try:
            self._adb.run("forward", "--remove", f"tcp:{port}", check=False)
        except Exception:
            pass


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _WebSocketClient:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._buffer = bytearray()
        self._closed = False

    @classmethod
    def connect(cls, host: str, port: int, path: str, *, timeout: float) -> _WebSocketClient:
        try:
            connection = socket.create_connection((host, port), timeout=timeout)
        except (OSError, TimeoutError) as exc:
            raise BackendUnavailable(f"could not connect to WebView DevTools WebSocket: {exc}") from exc
        client = cls(connection)
        try:
            client._handshake(host, port, path)
        except Exception:
            client.close()
            raise
        return client

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        try:
            self._connection.sendall(request)
            headers = self._read_http_headers()
        except (OSError, TimeoutError) as exc:
            raise BackendUnavailable(f"WebView DevTools WebSocket handshake failed: {exc}") from exc
        lines = headers.decode("latin-1").split("\r\n")
        if not lines or not lines[0].startswith("HTTP/1.1 101"):
            raise BackendUnavailable(
                f"WebView DevTools WebSocket rejected the handshake: {lines[0] if lines else 'empty response'}"
            )
        values: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                values[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        if values.get("sec-websocket-accept") != expected:
            raise ProtocolError("WebView DevTools WebSocket returned an invalid accept key")

    def _read_http_headers(self) -> bytes:
        while b"\r\n\r\n" not in self._buffer:
            chunk = self._connection.recv(4096)
            if not chunk:
                raise BackendUnavailable("WebView DevTools WebSocket closed during handshake")
            self._buffer.extend(chunk)
            if len(self._buffer) > 64 * 1024:
                raise ProtocolError("WebView DevTools WebSocket handshake is too large")
        end = self._buffer.index(b"\r\n\r\n") + 4
        headers = bytes(self._buffer[:end])
        del self._buffer[:end]
        return headers

    def send_json(self, value: Mapping[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, payload)

    def receive_json(self, *, timeout: float) -> Mapping[str, Any]:
        payload = self._receive_message(timeout=timeout)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("WebView DevTools returned invalid JSON over WebSocket") from exc
        if not isinstance(value, Mapping):
            raise ProtocolError("WebView DevTools returned a non-object message")
        return value

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise BackendUnavailable("WebView DevTools WebSocket is closed")
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack(">H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack(">Q", length)
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        try:
            self._connection.sendall(header + mask + masked)
        except (OSError, TimeoutError) as exc:
            raise BackendUnavailable(f"could not send WebView DevTools message: {exc}") from exc

    def _receive_message(self, *, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        fragments: bytearray | None = None
        fragment_opcode: int | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendUnavailable("timed out waiting for WebView DevTools response")
            try:
                self._connection.settimeout(remaining)
                fin, opcode, payload = self._receive_frame()
            except socket.timeout as exc:
                raise BackendUnavailable("timed out waiting for WebView DevTools response") from exc
            except OSError as exc:
                raise BackendUnavailable(f"WebView DevTools WebSocket read failed: {exc}") from exc

            if opcode == 0x9:  # ping
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:
                self.close()
                raise BackendUnavailable("WebView DevTools WebSocket closed")
            if opcode in (0x1, 0x2):
                if fragments is not None:
                    raise ProtocolError("WebView DevTools sent an invalid nested WebSocket message")
                if fin:
                    if opcode != 0x1:
                        raise ProtocolError("WebView DevTools returned a binary message")
                    return payload
                fragments = bytearray(payload)
                fragment_opcode = opcode
                continue
            if opcode == 0x0:
                if fragments is None or fragment_opcode is None:
                    raise ProtocolError("WebView DevTools sent an unexpected continuation frame")
                fragments.extend(payload)
                if fin:
                    if fragment_opcode != 0x1:
                        raise ProtocolError("WebView DevTools returned a binary message")
                    return bytes(fragments)
                continue
            raise ProtocolError(f"WebView DevTools sent unsupported WebSocket opcode {opcode}")

    def _receive_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        if length > _MAX_FRAME_BYTES:
            raise ProtocolError("WebView DevTools WebSocket frame is too large")
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return fin, opcode, payload

    def _read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = self._connection.recv(max(4096, size - len(self._buffer)))
            if not chunk:
                raise BackendUnavailable("WebView DevTools WebSocket closed unexpectedly")
            self._buffer.extend(chunk)
        value = bytes(self._buffer[:size])
        del self._buffer[:size]
        return value

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        self._closed = True
        try:
            self._connection.close()
        except OSError:
            pass


class _CdpClient:
    def __init__(self, websocket: _WebSocketClient, *, timeout: float) -> None:
        self._websocket = websocket
        self._timeout = timeout
        self._next_id = 1

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        command_id = self._next_id
        self._next_id += 1
        command: dict[str, Any] = {"id": command_id, "method": method}
        if params:
            command["params"] = dict(params)
        self._websocket.send_json(command)
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendUnavailable(f"timed out waiting for CDP method {method}")
            message = self._websocket.receive_json(timeout=remaining)
            if message.get("id") != command_id:
                continue
            error = message.get("error")
            if isinstance(error, Mapping):
                code = error.get("code", "unknown")
                detail = error.get("message", "unknown CDP error")
                raise BackendError(f"CDP {method} failed ({code}): {detail}")
            result = message.get("result", {})
            if not isinstance(result, Mapping):
                raise ProtocolError(f"CDP {method} returned a non-object result")
            return result

    def dump_document(self) -> str:
        self.call("DOM.enable")
        document = self.call("DOM.getDocument", {"depth": -1, "pierce": True})
        root = document.get("root")
        node_id = root.get("nodeId") if isinstance(root, Mapping) else None
        html = ""
        if isinstance(node_id, int):
            try:
                response = self.call("DOM.getOuterHTML", {"nodeId": node_id})
                value = response.get("outerHTML")
                if isinstance(value, str):
                    html = value
            except BackendError:
                # Runtime.evaluate below is a useful fallback for WebView/CDP
                # revisions that do not accept the document node id.
                pass
        if not html:
            response = self.call(
                "Runtime.evaluate",
                {
                    "expression": (
                        "document.documentElement ? document.documentElement.outerHTML : "
                        "(document.body ? document.body.outerHTML : '')"
                    ),
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            )
            result = response.get("result")
            value = result.get("value") if isinstance(result, Mapping) else None
            if isinstance(value, str):
                html = value
        html = html.strip()
        if not html:
            raise ProtocolError("WebView DevTools returned an empty DOM")
        return html
