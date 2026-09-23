"""Run a bounded UI goal with Jev selecting validated candidates."""

from __future__ import annotations

import argparse
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
GOAL = "打开设置，进入关于本机"
MAX_STEPS = 8


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
        help="execute without preview and offer all discovered UI/OCR control labels",
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
    if run.termination == "needs_verification":
        outcome = "goal completion reported; verification required"
    elif run.termination == "next_action_preview":
        outcome = "preview ready"
    else:
        outcome = "success" if run.success else "stopped"
    print(f"Outcome: {outcome}")
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
    if run.plan.jev and run.plan.jev.get("recovery_subgoals"):
        print("Recovery subgoals:")
        for index, subgoal in enumerate(run.plan.jev["recovery_subgoals"], start=1):
            goal = subgoal.get("recovery_goal", "(not generated)")
            print(f"  {index}. {goal} — {subgoal['outcome']}")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    allowed_controls, dry_run = _goal_options(args)
    with connect(CONFIG) as phone:
        result = phone.run(
            GOAL,
            max_steps=MAX_STEPS,
            use_score=False,
            prefer_webview=False,
        )
        _print_run_summary(result)
        if result.termination == "needs_verification":
            print("Jev signaled completion; inspect a fresh screenshot or UI dump to verify.")
        phone.save_run("jev-goal-run.json")


if __name__ == "__main__":
    main()
