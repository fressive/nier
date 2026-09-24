from __future__ import annotations

import base64
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from nier.web import _DashboardState, create_app


def test_dashboard_filters_stdout_log_lines_but_keeps_script_output(tmp_path) -> None:
    dashboard = _DashboardState(tmp_path, tmp_path)
    dashboard.run_state["id"] = "run-1"
    event = {
        "type": "log",
        "run_id": "run-1",
        "category": "STEP",
        "message": "tap",
        "details": {},
    }
    location = {
        "type": "execution.location",
        "run_id": "run-1",
        "file": "example.py",
        "line": 23,
        "function": "main",
    }
    stdout = StringIO(
        "12:34:56.789 [nier v] STEP tap\n"
        "  x: 10\n"
        f"\x1eNIER_EVENT {json.dumps(event)}\n"
        f"\x1eNIER_EVENT {json.dumps(location)}\n"
        "script output\n"
    )

    dashboard._read_output(stdout, "stdout", "run-1")

    assert [item["type"] for item in dashboard.history] == ["log", "console"]
    assert dashboard.history[-1]["text"] == "script output"
    assert dashboard.run_state["execution_location"] == {
        "file": "example.py",
        "line": 23,
        "function": "main",
    }


def test_source_endpoint_reads_only_available_scripts_and_disables_caching(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    nested = scripts / "nested"
    nested.mkdir()
    source_text = "def main():\n    print('你好')\n"
    (nested / "example.py").write_text(source_text, encoding="utf-8")
    (scripts / "invalid_encoding.py").write_bytes(b"\xff\xfe")
    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n", encoding="utf-8")
    (scripts / "linked.py").symlink_to(outside)
    client = TestClient(create_app(scripts, cwd=tmp_path))

    response = client.get("/api/source/nested/example.py")

    assert response.status_code == 200
    assert response.json() == {"path": "nested/example.py", "source": source_text}
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/source/linked.py").status_code == 404
    assert client.get("/api/source/outside.py").status_code == 404
    assert client.get("/api/source/%2E%2E%2Foutside.py").status_code == 404
    assert client.get("/api/source/invalid_encoding.py").status_code == 415
    assert client.get(
        "/api/source/nested/example.py",
        headers={"Origin": "https://attacker.example"},
    ).status_code == 403


def test_uidump_capture_uses_configured_device_and_returns_inspection_data(
    monkeypatch,
    tmp_path,
) -> None:
    dashboard = _DashboardState(tmp_path, tmp_path, Path("custom/nier.yaml"))
    dashboard.preview.status = lambda: {
        "devices": [{"serial": "device-1", "state": "device"}]
    }
    calls = []

    class FakeDevice:
        def screenshot(self):
            calls.append("screenshot")
            return SimpleNamespace(
                data=b"png-data",
                format=SimpleNamespace(value="PNG"),
                width=120,
                height=240,
            )

        def dump_ui(self, **options):
            calls.append(("dump_ui", options))
            return SimpleNamespace(
                xml='<hierarchy><node bounds="[1,2][3,4]" /></hierarchy>',
                source=SimpleNamespace(value="UIAUTOMATOR"),
                complete=True,
                warning="",
            )

        def parse_uidump(self, dump):
            calls.append(("parse_uidump", dump.xml))
            return "parsed-document"

        def format_tree(self, document, *, color):
            assert document == "parsed-document"
            assert color is False
            return "hierarchy\n└── node"

        def close(self):
            calls.append("close")

    def fake_connect(config_path, *, serial):
        calls.append(("connect", config_path, serial))
        return FakeDevice()

    monkeypatch.setattr("nier.web.connect", fake_connect)

    result = dashboard.capture_uidump(
        "device-1",
        prefer_webview=False,
        include_invisible=True,
    )

    assert result["screen_width"] == 120
    assert result["screen_height"] == 240
    assert base64.b64decode(result["image_base64"]) == b"png-data"
    assert result["source"] == "UIAUTOMATOR"
    assert result["tree_text"] == "hierarchy\n└── node"
    assert calls == [
        ("connect", tmp_path / "custom/nier.yaml", "device-1"),
        "screenshot",
        ("dump_ui", {"prefer_webview": False, "include_invisible": True}),
        ("parse_uidump", '<hierarchy><node bounds="[1,2][3,4]" /></hierarchy>'),
        "close",
    ]


def test_uidump_endpoint_checks_origin_and_uses_inspector_request(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    client = TestClient(create_app(scripts, cwd=tmp_path))
    state = client.app.state.dashboard
    calls = []

    def capture(serial, **options):
        calls.append((serial, options))
        return {"serial": serial, "xml": "<hierarchy />"}

    state.capture_uidump = capture
    response = client.post(
        "/api/uidump",
        json={
            "serial": "device-1",
            "prefer_webview": False,
            "include_invisible": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"serial": "device-1", "xml": "<hierarchy />"}
    assert response.headers["cache-control"] == "no-store"
    assert calls == [
        (
            "device-1",
            {"prefer_webview": False, "include_invisible": True},
        )
    ]
    forbidden = client.post(
        "/api/uidump",
        json={"serial": "device-1"},
        headers={"Origin": "https://attacker.example"},
    )
    assert forbidden.status_code == 403
