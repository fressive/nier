from __future__ import annotations

import runpy
from pathlib import Path

import nier


def test_jev_goal_example_modes_are_opt_in_and_import_safe(monkeypatch) -> None:
    def fail_if_connected(*args, **kwargs) -> None:
        raise AssertionError("importing the example must not connect to a device")

    monkeypatch.setattr(nier, "connect", fail_if_connected)
    example_path = Path(__file__).parents[1] / "examples" / "10_jev_goal.py"
    example = runpy.run_path(example_path, run_name="jev_goal_example_test")
    parser = example["_parser"]()
    options = example["_goal_options"]

    preview = parser.parse_args([])
    assert options(preview) == (("关于本机",), True)

    execute = parser.parse_args(["--execute"])
    assert options(execute) == (("关于本机",), False)

    yolo = parser.parse_args(["--yolo"])
    assert options(yolo) == (None, False)

    constrained_yolo = parser.parse_args(
        ["--yolo", "--allow-control", "返回上一页"]
    )
    assert options(constrained_yolo) == (("返回上一页",), False)
