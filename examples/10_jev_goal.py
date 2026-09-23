"""Run a bounded UI goal with Jev selecting validated candidates."""

from __future__ import annotations

import argparse
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
parser.add_argument(
    "--allow-app",
    action="append",
    dest="allowed_app_specs",
    metavar="LABEL=PACKAGE",
    help="explicitly allow launching an app; repeat to allow multiple apps",
)
args = parser.parse_args()
allowed_apps = {}
for spec in args.allowed_app_specs or []:
    label, separator, package = spec.partition("=")
    if not separator or not label.strip() or not package.strip():
        parser.error("--allow-app must use LABEL=PACKAGE")
    if label.strip() in allowed_apps:
        parser.error(f"duplicate --allow-app label: {label.strip()!r}")
    allowed_apps[label.strip()] = package.strip()
if args.execute and not (args.allowed_controls or allowed_apps):
    parser.error("--execute requires at least one --allow-control or --allow-app")
allowed_controls = args.allowed_controls
if allowed_apps and allowed_controls is None:
    # An app-only grant in this example must not also enable discovered UI taps.
    allowed_controls = ()


def _print_run_summary(run) -> None:
    print(f"Goal: {run.instruction}")
    print(f"Outcome: {'success' if run.success else 'stopped'}")
    print(f"Mode: {'preview only' if run.dry_run else 'device actions executed'}")
    if run.termination:
        print(f"Stopped because: {run.termination.replace('_', ' ')}")
    print(f"Completed steps: {run.completed_steps}")
    if run.plan.steps:
        print("Planned actions:")
        for index, step in enumerate(run.plan.steps, start=1):
            reason = f" — {step.reason}" if step.reason else ""
            print(f"  {index}. {step.action}{reason}")
    if run.results:
        print("Action results:")
        for index, result in enumerate(run.results, start=1):
            status = "succeeded" if result.success else "failed"
            detail = result.message or result.error_code
            suffix = f": {detail}" if detail else ""
            print(f"  {index}. {status}{suffix}")


with connect(CONFIG) as phone:
    result = phone.run_jev_goal(
        GOAL,
        max_steps=8,
        max_seconds=45,
        allowed_apps=allowed_apps,
        allowed_controls=allowed_controls,
        denied_controls=args.denied_controls,
        dry_run=not args.execute,
        use_score=False,
    )
    _print_run_summary(result)
    if result.termination == "needs_verification":
        print("Jev signaled completion; inspect a fresh screenshot or UI dump to verify.")
    phone.save_run("jev-goal-run.json")
