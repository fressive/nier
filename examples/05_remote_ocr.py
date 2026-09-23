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
        print(f"Recognized labels ({len(spans)}):")
        for span in spans:
            print(f"  - {span.text!r} (confidence {span.confidence:.0%})")

        decision = TextMatchDecisionProvider().decide(spans, INSTRUCTION)
        print(f"Decision: {decision.action}")
        print(f"Confidence: {decision.confidence:.0%}")
        if decision.rationale:
            print(f"Reason: {decision.rationale}")
        if decision.point is not None:
            print(f"Tap point: ({decision.point[0]:.1f}, {decision.point[1]:.1f})")
        if EXECUTE and decision.action == "tap" and decision.point is not None:
            phone.tap(*decision.point)
        phone.save_run("remote-ocr-decision.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
