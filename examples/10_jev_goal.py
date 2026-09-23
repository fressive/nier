"""Run a bounded UI goal with Jev selecting validated candidates."""

from __future__ import annotations

import argparse
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
GOAL = "打开设置，进入关于本机"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument(
        "--execute",
        action="store_true",
        help="execute actions with the default UI label allowlist",
    )
    execution.add_argument(
        "--yolo",
        action="store_true",
        help="execute actions and offer all discovered UI/OCR control labels",
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
    return parser


def _goal_options(args: argparse.Namespace) -> tuple[tuple[str, ...] | None, bool]:
    if args.allowed_controls:
        allowed_controls = tuple(args.allowed_controls)
    elif args.yolo:
        allowed_controls = None
    else:
        allowed_controls = ("关于本机",)
    dry_run = not (args.execute or args.yolo)
    return allowed_controls, dry_run


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


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    allowed_controls, dry_run = _goal_options(args)
    with connect(CONFIG) as phone:
        result = phone.run_jev_goal(
            GOAL,
            max_steps=100,
            max_seconds=45,
            allowed_apps={"设置": "com.android.settings"},
            allowed_controls=allowed_controls,
            denied_controls=args.denied_controls,
            use_score=False,
            dry_run=dry_run,
        )
        _print_run_summary(result)
        if result.termination == "needs_verification":
            print("Jev signaled completion; inspect a fresh screenshot or UI dump to verify.")
        phone.save_run("jev-goal-run.json")


if __name__ == "__main__":
    main()
