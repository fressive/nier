from __future__ import annotations

import runpy
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import nier


def test_jev_goal_example_modes_are_opt_in_and_import_safe(monkeypatch) -> None:
    def fail_if_connected(*args, **kwargs) -> None:
        raise AssertionError("importing the example must not connect to a device")

    monkeypatch.setattr(nier, "connect", fail_if_connected)
    example_path = Path(__file__).parents[1] / "examples" / "06_jev_goal.py"
    example = runpy.run_path(example_path, run_name="jev_goal_example_test")
    parser = example["_parser"]()
    options = example["_goal_options"]

    preview = parser.parse_args([])
    assert options(preview) == (None, True)

    execute = parser.parse_args(["--execute"])
    assert options(execute) == (None, False)

    yolo = parser.parse_args(["--yolo"])
    assert options(yolo) == (None, False)

    constrained_yolo = parser.parse_args(
        ["--yolo", "--allow-control", "返回上一页"]
    )
    assert options(constrained_yolo) == (("返回上一页",), False)


def test_jev_goal_example_uses_a_bounded_main_action_budget(monkeypatch) -> None:
    example_path = Path(__file__).parents[1] / "examples" / "06_jev_goal.py"
    example = runpy.run_path(example_path, run_name="jev_goal_example_budget_test")
    run_options: dict[str, object] = {}

    def run(_instruction: str, **options: object) -> SimpleNamespace:
        run_options.update(options)
        return SimpleNamespace(termination="blocked")

    phone = SimpleNamespace(run_jev_goal=run, save_run=lambda _name: None)
    namespace = example["main"].__globals__
    monkeypatch.setitem(namespace, "connect", lambda _config: nullcontext(phone))
    monkeypatch.setitem(namespace, "_print_run_summary", lambda _run: None)

    example["main"](["--execute"])

    assert run_options["max_steps"] == 8
    assert run_options["dry_run"] is False
    assert run_options["allowed_controls"] is None

    run_options.clear()
    example["main"]([])
    assert run_options["dry_run"] is True

    run_options.clear()
    example["main"](["--execute", "--allow-control", "关于本机", "--deny-control", "取消"])
    assert run_options["allowed_controls"] == ("关于本机",)
    assert run_options["denied_controls"] == ["取消"]


def test_jev_goal_example_reports_preview_and_unverified_completion() -> None:
    example_path = Path(__file__).parents[1] / "examples" / "06_jev_goal.py"
    example = runpy.run_path(example_path, run_name="jev_goal_example_summary_test")
    run = SimpleNamespace(
        instruction="打开设置，进入关于本机",
        success=True,
        dry_run=False,
        termination="needs_verification",
        completed_steps=2,
        plan=SimpleNamespace(steps=(), jev=None),
        results=(),
    )
    output = StringIO()

    with redirect_stdout(output):
        example["_print_run_summary"](run)

    assert "Outcome: goal completion reported; verification required" in output.getvalue()
    assert "Outcome: success" not in output.getvalue()

    run.dry_run = True
    run.termination = "next_action_preview"
    output = StringIO()
    with redirect_stdout(output):
        example["_print_run_summary"](run)
    assert "Outcome: preview ready" in output.getvalue()
