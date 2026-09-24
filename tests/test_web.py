from __future__ import annotations

import json
from io import StringIO

from nier.web import _DashboardState


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
