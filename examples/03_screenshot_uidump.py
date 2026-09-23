"""Capture evidence and inspect the buttons on the current screen."""

from __future__ import annotations

import json
from pathlib import Path

from nier import connect, parse_uidump

CONFIG = Path("config/nier.yaml")
OUTPUT = Path("artifacts/current-screen")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with connect(CONFIG) as phone:
        screenshot_path = OUTPUT / "screen.png"
        screenshot = phone.screenshot(
            screenshot_path,
            max_width=1280,
            max_height=1280,
        )
        dump = phone.dump_ui(prefer_webview=True)
        ui_path = OUTPUT / "ui.xml"
        ui_path.write_text(dump.xml, encoding="utf-8")

        print(f"Screenshot saved to: {screenshot_path}")
        print(f"Screenshot SHA-256: {screenshot.sha256}")
        print(f"UI dump saved to: {ui_path}")
        print(f"UI dump source: {dump.source.value}")
        if dump.warning:
            print(f"UI dump note: {dump.warning}")

        document = parse_uidump(dump)
        structured_path = OUTPUT / "ui.json"
        structured_path.write_text(
            json.dumps(document.to_dict(max_nodes=256), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        buttons = document.find_all(clickable=True)
        print(f"Structured UI tree saved to: {structured_path}")
        print(f"Clickable nodes ({len(buttons)}):")
        for node in buttons:
            label = node.text_content or node.content_desc or "(no label)"
            center = (
                "unknown"
                if node.center is None
                else f"({node.center[0]:.1f}, {node.center[1]:.1f})"
            )
            resource_id = f"; id={node.resource_id}" if node.resource_id else ""
            print(f"  - {label!r}{resource_id}; center={center}")
        phone.save_run("screen-inspection.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
