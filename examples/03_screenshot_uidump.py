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

        print({"screenshot": str(screenshot_path), "sha256": screenshot.sha256})
        print({"ui_dump": str(ui_path), "source": dump.source.value})

        document = parse_uidump(dump)
        structured_path = OUTPUT / "ui.json"
        structured_path.write_text(
            json.dumps(document.to_dict(max_nodes=256), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        buttons = [
            {
                "text": node.text_content,
                "resource_id": node.resource_id,
                "center": node.center,
            }
            for node in document.find_all(clickable=True)
        ]
        print(
            json.dumps(
                {"structured_ui": str(structured_path), "clickable_nodes": buttons},
                ensure_ascii=False,
                indent=2,
            )
        )
        phone.save_run("screen-inspection.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
