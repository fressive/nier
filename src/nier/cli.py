"""Command-line commands for Android devices and local script execution."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path

from .adb import AdbClient
from .backends.adb import AdbBackend
from .config import HookMode, load_config
from .errors import NierError
from .hooks import RootFridaIntentHook
from .intent_codegen import generate_intent_code
from .logging_utils import configure_logging
from .protocol import Capabilities, validate_package_name
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
        help="increase logs: -v steps, -vv results, -vvv transport details",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")
    subparsers.add_parser("capabilities")
    subparsers.add_parser("screenshot")
    subparsers.add_parser("dump-ui")
    web_parser = subparsers.add_parser(
        "web",
        help="open the local execution dashboard for Python scripts",
    )
    web_parser.add_argument(
        "--scripts",
        type=Path,
        required=True,
        help="directory containing scripts available to the dashboard",
    )
    web_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="dashboard bind address (default: 127.0.0.1)",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="dashboard port (default: 8765)",
    )
    web_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="print the dashboard URL without opening a browser",
    )
    intent_parser = subparsers.add_parser(
        "intent-hook",
        help="capture Activity Intents from a rooted Android app",
    )
    intent_parser.add_argument(
        "--package",
        help="target Android package (defaults to hook.target_package)",
    )
    spawn_group = intent_parser.add_mutually_exclusive_group()
    spawn_group.add_argument(
        "--spawn",
        dest="spawn",
        action="store_true",
        default=None,
        help="spawn the target with the hook installed before resume",
    )
    spawn_group.add_argument(
        "--attach",
        dest="spawn",
        action="store_false",
        default=None,
        help="attach to the already running target process",
    )
    intent_parser.add_argument(
        "--format",
        choices=("kotlin", "java"),
        default="kotlin",
        help="language for the reusable startActivity helper (default: kotlin)",
    )
    intent_parser.add_argument(
        "--once",
        action="store_true",
        help="exit after capturing the first Activity Intent",
    )
    return parser


def _print_capabilities(capabilities: Capabilities) -> None:
    print("Device capabilities:")
    print(f"  Device: {capabilities.model or 'unknown'} ({capabilities.device_id})")
    print(f"  Protocol: {capabilities.protocol_version}")
    print(f"  Screen: {capabilities.screen_width} × {capabilities.screen_height}")
    print(f"  Root access: {'yes' if capabilities.is_rooted else 'no'}")
    print(
        "  UIAutomator: "
        f"{'available' if capabilities.supports_ui_automator else 'unavailable'}"
    )
    print(
        "  WebView debugging: "
        f"{'available' if capabilities.supports_webview_debugging else 'unavailable'}"
    )
    print(f"  uinput: {'available' if capabilities.supports_uinput else 'unavailable'}")
    print(f"  Actions: {', '.join(capabilities.action_names) or 'none'}")


def _run_intent_hook(args: argparse.Namespace) -> int:
    if args.verbose > 3:
        raise SystemExit("nier: at most -vvv is supported")
    try:
        config = load_config(args.config)
    except (NierError, OSError, ValueError) as exc:
        raise SystemExit(f"nier intent-hook: {exc}") from exc
    configure_logging(max(config.logging.verbosity, args.verbose))
    if config.hook.mode is HookMode.NON_ROOT:
        raise SystemExit(
            "nier intent-hook: hook.mode is non-root; set hook.mode: root to use Frida"
        )

    try:
        package = validate_package_name(args.package or config.hook.target_package or "")
        hook_config = replace(
            config.hook,
            mode=HookMode.ROOT,
            target_package=package,
        )
        hook = RootFridaIntentHook(AdbClient(config.device), hook_config)
        session = hook.attach(package, spawn=args.spawn)
    except (NierError, OSError, ValueError) as exc:
        raise SystemExit(f"nier intent-hook: {exc}") from exc

    print(f"Intent hook attached to {package} (pid {session.pid}). Press Ctrl-C to stop.", flush=True)
    captured = 0
    try:
        while True:
            event = session.next_event(timeout=0.5)
            if event is None:
                continue
            if event.type == "error":
                raise SystemExit(
                    f"nier intent-hook: {event.payload.get('error', 'Frida agent failed')}"
                )
            if event.type == "intent_hook_warning":
                print(
                    f"Intent hook warning: {event.payload.get('error', event.payload)}",
                    flush=True,
                )
                continue
            if event.type != "intent_started":
                continue

            intent = event.payload.get("intent")
            if not isinstance(intent, Mapping):
                print("Intent hook warning: received an invalid Intent payload", flush=True)
                continue
            captured += 1
            print(f"\nActivity launch #{captured} ({event.payload.get('source', 'unknown')}):")
            print(json.dumps(dict(intent), ensure_ascii=False, indent=2))
            print(f"\nReusable {args.format} startActivity code:")
            print(generate_intent_code(intent, args.format), end="", flush=True)
            if args.once:
                return 0
    except KeyboardInterrupt:
        print("\nIntent hook stopped.", flush=True)
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "web":
        from .web import serve_web

        try:
            serve_web(
                args.scripts,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(f"nier web: {exc}") from exc
        return 0
    if args.command == "intent-hook":
        return _run_intent_hook(args)

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
            print(f"Device status: {'ready' if session.health() else 'not ready'}")
        elif args.command == "capabilities":
            _print_capabilities(session.capabilities())
        elif args.command == "screenshot":
            screenshot = session.screenshot()
            target = config.runtime.output_dir / f"screenshot.{screenshot.format.value.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(screenshot.data)
            print(f"Screenshot saved to: {target}")
        elif args.command == "dump-ui":
            dump = session.dump_ui()
            target = config.runtime.output_dir / "ui.xml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dump.xml, encoding="utf-8")
            print(f"UI dump saved to: {target}")
            print(f"Source: {dump.source.value}")
            if dump.warning:
                print(f"Note: {dump.warning}")
        recorder.write_json()
        return 0
    finally:
        session.close()
