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
        print(decision)
        if decision.action == "tap" and decision.point is not None:
            phone.tap(*decision.point)
        phone.save_run("ocr-decision.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
