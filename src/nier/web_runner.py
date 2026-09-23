"""Run a script for the local dashboard with STEP-boundary controls."""

from __future__ import annotations

import io
from pathlib import Path
import runpy
import sys
import threading

from .web_debugger import read_commands


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m nier.web_runner SCRIPT")

    script = sys.argv[1]
    sys.path.insert(0, str(Path(script).resolve().parent))
    sys.argv = [script]
    command_stream = sys.stdin
    threading.Thread(
        target=read_commands,
        args=(command_stream,),
        name="nier-web-debug-commands",
        daemon=True,
    ).start()

    # Dashboard commands use the runner's stdin pipe, not script input.
    sys.stdin = io.StringIO()
    sys.__stdin__ = sys.stdin
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
