from __future__ import annotations

import json
from io import StringIO

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
