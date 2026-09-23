"""Command-line entry points for smoke-testing a connected device."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backends.adb import AdbBackend
from .config import load_config
from .logging_utils import configure_logging
from .results import RunRecorder
from .session import DeviceSession


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nier")
    parser.add_argument("--config", type=Path, default=Path("config/nier.yaml"))
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase logs: -v steps, -vv requests, -vvv responses",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")
    subparsers.add_parser("capabilities")
    subparsers.add_parser("screenshot")
    subparsers.add_parser("dump-ui")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(args.config)
    if args.verbose > 3:
        raise SystemExit("nier: at most -vvv is supported")
    configure_logging(max(config.logging.verbosity, args.verbose))
    backend = AdbBackend(
        config.device,
        hook_config=config.hook,
        input_text_config=config.input_text,
    )
    recorder = RunRecorder(config.runtime.output_dir)
    session = DeviceSession(backend, retries=config.runtime.retries, recorder=recorder)
    try:
        if args.command == "health":
            print(json.dumps({"ready": session.health()}))
        elif args.command == "capabilities":
            print(json.dumps(session.capabilities().__dict__, ensure_ascii=False, indent=2))
        elif args.command == "screenshot":
            screenshot = session.screenshot()
            target = config.runtime.output_dir / f"screenshot.{screenshot.format.value.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(screenshot.data)
            print(target)
        elif args.command == "dump-ui":
            dump = session.dump_ui()
            target = config.runtime.output_dir / "ui.xml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dump.xml, encoding="utf-8")
            print(json.dumps({"path": str(target), "source": dump.source.value, "warning": dump.warning}))
        recorder.write_json()
        return 0
    finally:
        session.close()
