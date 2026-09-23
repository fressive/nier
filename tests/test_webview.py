from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from typing import Any

from nier.backends.adb import AdbBackend
from nier.config import DeviceConfig, HookConfig, HookMode
from nier.protocol import UiSource
from nier.webview import (
    DevToolsTarget,
    WebViewDevTools,
    _CdpClient,
    _WebSocketClient,
    _WS_GUID,
    _select_target,
    _websocket_path,
)


class FakeWebSocket:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.commands: list[dict[str, Any]] = []

    def send_json(self, value: dict[str, Any]) -> None:
        self.commands.append(value)

    def receive_json(self, *, timeout: float) -> dict[str, Any]:
        del timeout
        return next(self.responses)


def test_cdp_client_exports_document_html() -> None:
    websocket = FakeWebSocket(
        [
            {"id": 1, "result": {}},
            {"id": 2, "result": {"root": {"nodeId": 7}}},
            {"id": 3, "result": {"outerHTML": "<html><body>ok</body></html>"}},
        ]
    )

    html = _CdpClient(websocket, timeout=1.0).dump_document()  # type: ignore[arg-type]

    assert html == "<html><body>ok</body></html>"
    assert [command["method"] for command in websocket.commands] == [
        "DOM.enable",
        "DOM.getDocument",
        "DOM.getOuterHTML",
    ]


def test_cdp_client_falls_back_to_runtime_evaluate() -> None:
    websocket = FakeWebSocket(
        [
            {"id": 1, "result": {}},
            {"id": 2, "result": {"root": {"nodeId": 7}}},
            {"id": 3, "error": {"code": -32000, "message": "not supported"}},
            {"id": 4, "result": {"result": {"value": "<html><body>fallback</body></html>"}}},
        ]
    )

    html = _CdpClient(websocket, timeout=1.0).dump_document()  # type: ignore[arg-type]

    assert html.endswith("fallback</body></html>")
    assert websocket.commands[-1]["method"] == "Runtime.evaluate"


def test_target_discovery_helpers() -> None:
    target = _select_target(
        [
            {"type": "worker", "webSocketDebuggerUrl": "ws://127.0.0.1/worker"},
            {
                "type": "page",
                "title": "Example",
                "url": "https://example.test",
                "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/abc?x=1",
            },
        ]
    )

    assert target == DevToolsTarget(
        websocket_url="ws://localhost:9222/devtools/page/abc?x=1",
        target_type="page",
        title="Example",
        url="https://example.test",
    )
    assert _websocket_path(target.websocket_url) == "/devtools/page/abc?x=1"


def test_adb_backend_returns_webview_dump_when_cdp_succeeds(monkeypatch) -> None:
    class FakeDevTools:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def dump_dom(self) -> str:
            return "<html><body>from-webview</body></html>"

    monkeypatch.setattr("nier.backends.adb.WebViewDevTools", FakeDevTools)
    backend = AdbBackend(
        DeviceConfig(serial="device"),
        hook_config=HookConfig(mode=HookMode.NON_ROOT, target_package="com.example.app"),
    )

    dump = backend.dump_ui()

    assert dump.source is UiSource.WEBVIEW_DEVTOOLS
    assert dump.complete is True
    assert dump.xml == "<html><body>from-webview</body></html>"
    monkeypatch.setattr(backend, "_read_screen_size", lambda: (100, 200))
    monkeypatch.setattr(backend, "_is_rooted", lambda: False)
    monkeypatch.setattr(backend, "_read_setting", lambda *_args: "device")
    monkeypatch.setattr(backend, "_read_property", lambda *_args: "model")
    assert backend.capabilities().supports_webview_debugging is True


def test_webview_dump_forwards_socket_and_removes_forward(monkeypatch) -> None:
    class FakeAdb:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args: str, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            self.calls.append(args)
            if args[:2] == ("shell", "pidof"):
                return subprocess.CompletedProcess(args, 0, b"123\n", b"")
            if args[:2] == ("shell", "cat"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    b"00000000 00000000 00010000 0001 01 12345 @webview_devtools_remote_123\n",
                    b"",
                )
            return subprocess.CompletedProcess(args, 0, b"", b"")

    class FakeWebSocket:
        def close(self) -> None:
            pass

    class FakeCdp:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def dump_document(self) -> str:
            return "<html />"

    monkeypatch.setattr("nier.webview._free_local_port", lambda: 45678)
    monkeypatch.setattr(
        "nier.webview._get_json",
        lambda *_args, **_kwargs: [{"type": "page", "webSocketDebuggerUrl": "ws://localhost/page"}],
    )
    monkeypatch.setattr("nier.webview._WebSocketClient.connect", lambda *_args, **_kwargs: FakeWebSocket())
    monkeypatch.setattr("nier.webview._CdpClient", FakeCdp)
    adb = FakeAdb()

    assert WebViewDevTools(adb, package="com.example.app", timeout=1.0).dump_dom() == "<html />"  # type: ignore[arg-type]
    assert ("forward", "tcp:45678", "localabstract:webview_devtools_remote_123") in adb.calls
    assert ("forward", "--remove", "tcp:45678") in adb.calls


def test_websocket_client_handshakes_masks_commands_and_reads_cdp() -> None:
    class InMemoryWebSocket:
        def __init__(self) -> None:
            self.incoming = bytearray()
            self.handshaken = False
            self.closed = False

        def sendall(self, data: bytes) -> None:
            if not self.handshaken:
                headers = data.decode("latin-1").split("\r\n")
                values = {
                    line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip()
                    for line in headers[1:]
                    if ":" in line
                }
                accept = base64.b64encode(
                    hashlib.sha1((values["sec-websocket-key"] + _WS_GUID).encode("ascii")).digest()
                ).decode("ascii")
                self.incoming.extend(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode("ascii")
                )
                self.handshaken = True
                return

            first, second = data[:2]
            opcode = first & 0x0F
            if opcode == 0x8:
                return
            assert first == 0x81
            assert second & 0x80
            length = second & 0x7F
            offset = 2
            if length == 126:
                length = int.from_bytes(data[offset : offset + 2], "big")
                offset += 2
            mask = data[offset : offset + 4]
            offset += 4
            payload = bytearray(data[offset : offset + length])
            for index in range(len(payload)):
                payload[index] ^= mask[index % 4]
            command = json.loads(payload.decode("utf-8"))
            assert command["method"] == "Runtime.enable"
            response = json.dumps({"id": command["id"], "result": {}}).encode("utf-8")
            self.incoming.extend(bytes((0x81, len(response))) + response)

        def recv(self, size: int) -> bytes:
            if not self.incoming:
                raise AssertionError("test WebSocket has no queued server data")
            value = bytes(self.incoming[:size])
            del self.incoming[:size]
            return value

        def settimeout(self, _timeout: float) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    websocket = _WebSocketClient(InMemoryWebSocket())  # type: ignore[arg-type]
    websocket._handshake("127.0.0.1", 1, "/devtools/page/test")
    websocket.send_json({"id": 1, "method": "Runtime.enable"})
    assert websocket.receive_json(timeout=1.0) == {"id": 1, "result": {}}
    websocket.close()
