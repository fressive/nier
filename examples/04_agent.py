"""Run an LLM UI goal with validated actions and optional on-demand OCR."""

from __future__ import annotations

import argparse
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
GOAL = "打开设置，进入关于手机"


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute validated LLM-selected actions on the connected device",
    )
    args = parser.parse_args()

    with connect(CONFIG) as phone:
        result = phone.llm(
            GOAL,
            max_steps=8,
            dry_run=not args.execute,
        )
        _print_run_summary(result)
        phone.save_run("agent-run.json")


if __name__ == "__main__":
    main()
