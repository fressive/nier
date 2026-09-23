"""Use OCR text and screen coordinates to tap a known UI label."""

from pathlib import Path

from nier import connect
from nier.models.decision import TextMatchDecisionProvider

CONFIG = Path("config/nier.yaml")
INSTRUCTION = "打开设置"


def main() -> int:
    with connect(CONFIG) as phone:
        spans = phone.screenshot().ocr()
        decision = TextMatchDecisionProvider().decide(spans, INSTRUCTION)
        print(f"Decision: {decision.action}")
        print(f"Confidence: {decision.confidence:.0%}")
        if decision.rationale:
            print(f"Reason: {decision.rationale}")
        if decision.point is not None:
            print(f"Tap point: ({decision.point[0]:.1f}, {decision.point[1]:.1f})")
        if decision.action == "tap" and decision.point is not None:
            phone.tap(*decision.point)
        phone.save_run("ocr-decision.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
