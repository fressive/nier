"""Use the configured remote PaddleOCR API to locate a visible label."""

from __future__ import annotations

from pathlib import Path

from nier import connect
from nier.config import load_config
from nier.models.decision import TextMatchDecisionProvider

CONFIG = Path("config/nier.yaml")
INSTRUCTION = "打开浏览器"
EXECUTE = False


def main() -> int:
    config = load_config(CONFIG)
    with connect(config) as phone:
        spans = phone.screenshot().ocr()
        print({"recognized": [span.text for span in spans]})

        decision = TextMatchDecisionProvider().decide(spans, INSTRUCTION)
        print(decision)
        if EXECUTE and decision.action == "tap" and decision.point is not None:
            phone.tap(*decision.point)
        phone.save_run("remote-ocr-decision.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
