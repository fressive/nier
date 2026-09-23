"""Run a bounded UI goal with Jev selecting validated candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
GOAL = "打开设置，进入关于手机"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--execute",
    action="store_true",
    help="execute selected device actions; default is a dry-run preview",
)
parser.add_argument(
    "--allow-control",
    action="append",
    dest="allowed_controls",
    help="exact UI/OCR label allowed as a target; repeat to allow multiple labels",
)
parser.add_argument(
    "--deny-control",
    action="append",
    dest="denied_controls",
    default=[],
    help="exact UI/OCR label to exclude; repeat to deny multiple labels",
)
args = parser.parse_args()
if args.execute and not args.allowed_controls:
    parser.error("--execute requires at least one --allow-control label")

with connect(CONFIG) as phone:
    result = phone.run_jev_goal(
        GOAL,
        max_steps=8,
        max_seconds=45,
        allowed_controls=args.allowed_controls,
        denied_controls=args.denied_controls,
        dry_run=not args.execute,
        use_score=False,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.termination == "needs_verification":
        print("Jev signaled completion; inspect a fresh screenshot or UI dump to verify.")
    phone.save_run("jev-goal-run.json")
