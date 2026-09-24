from __future__ import annotations

import runpy
import sys

from nier import web_debugger


def test_line_tracer_publishes_script_relative_locations(monkeypatch, tmp_path) -> None:
    script_root = tmp_path / "scripts"
    script_root.mkdir()
    script = script_root / "example.py"
    script.write_text("first = 1\nsecond = first + 1\n", encoding="utf-8")
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("NIER_WEB_SCRIPT_ROOT", str(script_root))
    monkeypatch.setenv("NIER_WEB_TRACE", "1")
    monkeypatch.setattr(
        web_debugger,
        "_publish_event",
        lambda event_type, **fields: events.append((event_type, fields)),
    )

    assert web_debugger.install_line_tracing()
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.settrace(None)

    locations = [fields for event_type, fields in events if event_type == "execution.location"]
    assert locations
    assert all(location["file"] == "example.py" for location in locations)
    assert locations[-1]["line"] == 2
    assert set(locations[-1]) == {"file", "line", "function"}
