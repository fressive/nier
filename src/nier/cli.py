"""Command-line commands for Android devices and local script execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from .adb import AdbClient
from .api import Device, connect
from .config import AppConfig, load_config
from .errors import NierError
from .intent_codegen import generate_intent_python
from .intent_hook import LsposedIntentHook
from .logging_utils import configure_logging
from .protocol import Capabilities, validate_package_name


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
    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="capture a screenshot with optional resizing and encoding",
    )
    screenshot_parser.add_argument("--output", type=Path, help="output image path")
    screenshot_parser.add_argument(
        "--format", choices=("png", "jpg", "jpeg"), help="image encoding format"
    )
    screenshot_parser.add_argument(
        "--quality", type=int, default=90, help="JPEG quality from 1 to 100"
    )
    screenshot_parser.add_argument("--max-width", type=int, default=0)
    screenshot_parser.add_argument("--max-height", type=int, default=0)
    uidump_parser = subparsers.add_parser(
        "uidump",
        aliases=["dump-ui"],
        help="capture and save the current UI hierarchy",
    )
    uidump_parser.add_argument("--output", type=Path, help="output dump path")
    uidump_parser.add_argument(
        "--format", choices=("xml", "json"), default="xml", help="dump format"
    )
    uidump_parser.add_argument(
        "--no-webview", action="store_true", help="use UIAutomator without WebView DOM"
    )
    uidump_parser.add_argument(
        "--include-invisible", action="store_true", help="include invisible UI nodes"
    )
    uidump_parser.add_argument(
        "--include-raw", action="store_true", help="include raw XML/HTML in JSON output"
    )

    locate_parser = subparsers.add_parser(
        "locate", help="locate visible text or an icon in a fresh screenshot"
    )
    locate_subparsers = locate_parser.add_subparsers(dest="locate_kind", required=True)
    text_parser = locate_subparsers.add_parser("text", help="locate OCR text")
    text_parser.add_argument("query", help="text to find")
    text_parser.add_argument("--min-score", type=float, default=0.6)
    text_parser.add_argument(
        "--tap", action="store_true", help="explicitly tap the match center"
    )
    text_parser.add_argument("--tap-duration", type=int, default=80)
    icon_parser = locate_subparsers.add_parser("icon", help="locate an image template")
    icon_parser.add_argument("template", type=Path, help="local template image")
    icon_parser.add_argument("--min-score", type=float, default=0.85)
    icon_parser.add_argument(
        "--region",
        type=int,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="limit search to a screen-pixel rectangle",
    )
    icon_parser.add_argument(
        "--tap", action="store_true", help="explicitly tap the match center"
    )
    icon_parser.add_argument("--tap-duration", type=int, default=80)

    adb_parser = subparsers.add_parser(
        "adb", help="pass a command through to ADB using configured device settings"
    )
    adb_parser.add_argument(
        "adb_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS
    )
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
        help="capture Activity Intents and generate a Nier Python launcher",
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
        help="force-stop and relaunch the target to activate the LSPosed hook",
    )
    spawn_group.add_argument(
        "--attach",
        dest="spawn",
        action="store_false",
        default=None,
        help="listen without restarting the target process",
    )
    intent_parser.add_argument(
        "--activity",
        help="Activity component to launch with --spawn instead of the launcher",
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
    try:
        package = validate_package_name(args.package or config.hook.target_package or "")
        spawn = config.hook.spawn if args.spawn is None else args.spawn
        if args.activity and not spawn:
            raise ValueError("--activity requires --spawn")
        hook = LsposedIntentHook(
            AdbClient(config.device),
            timeout_seconds=config.hook.timeout_seconds,
        )
        session = hook.attach(package, spawn=spawn, activity=args.activity)
    except KeyboardInterrupt:
        print("\nIntent hook stopped.", flush=True)
        return 0
    except (NierError, OSError, ValueError) as exc:
        raise SystemExit(f"nier intent-hook: {exc}") from exc

    if spawn:
        print(f"LSPosed hook active for {package}. Press Ctrl-C to stop.", flush=True)
    else:
        print(
            f"Listening for LSPosed Intent events from {package}. "
            "Make sure Nier is enabled for this package in LSPosed Manager.",
            flush=True,
        )
    captured = 0
    try:
        while True:
            event = session.next_event(timeout=0.5)
            if event is None:
                continue
            if event.kind == "error":
                raise SystemExit(
                    f"nier intent-hook: {event.payload.get('error', 'ADB logcat failed')}"
                )
            if event.kind == "module_ready":
                hook_sources = event.payload.get("hook_sources")
                installed_hooks = []
                if isinstance(hook_sources, Mapping):
                    installed_hooks = [
                        f"{source}={count}"
                        for source, count in hook_sources.items()
                        if isinstance(source, str) and isinstance(count, int)
                    ]
                hook_count = event.payload.get("hooks")
                details = []
                if isinstance(hook_count, int):
                    details.append(f"{hook_count} hooks")
                if installed_hooks:
                    details.append(", ".join(installed_hooks))
                diagnostic = "; " + "; ".join(details) if details else ""
                print(
                    f"LSPosed hook active for {package} "
                    f"(pid {event.payload.get('pid', 'unknown')}{diagnostic}).",
                    flush=True,
                )
                continue
            if event.kind in {"module_error", "capture_error"}:
                print(
                    f"Intent hook warning: {event.payload.get('error', event.payload)}",
                    flush=True,
                )
                continue
            if event.kind != "intent":
                continue

            intent = event.payload.get("intent")
            if not isinstance(intent, Mapping):
                print("Intent hook warning: received an invalid Intent payload", flush=True)
                continue
            captured += 1
            print(f"\nActivity launch #{captured} ({event.payload.get('source', 'unknown')}):")
            print(json.dumps(dict(intent), ensure_ascii=False, indent=2))
            print("\nReusable Nier Python launch code:")
            try:
                snippet = generate_intent_python(intent, config_path=str(args.config))
            except (TypeError, ValueError) as exc:
                print(f"Intent hook warning: cannot generate launch code: {exc}", flush=True)
                if args.once:
                    return 0
                continue
            print(snippet, end="", flush=True)
            if args.once:
                return 0
    except KeyboardInterrupt:
        print("\nIntent hook stopped.", flush=True)
        return 0
    finally:
        session.close()


def _run_locate(device: Device, args: argparse.Namespace) -> int:
    if args.locate_kind == "text":
        match = device.locate_text(args.query, min_score=args.min_score)
    else:
        region = None if args.region is None else tuple(args.region)
        match = device.locate_icon(
            args.template,
            min_score=args.min_score,
            region=region,
        )

    if match is None:
        print("No match found")
        return 1

    print("Match found:")
    print(f"  Bounds: {match.bounds}")
    print(f"  Center: ({match.center[0]:.1f}, {match.center[1]:.1f})")
    print(f"  Score: {match.score:.3f}")
    if args.tap:
        result = match.click(duration_ms=args.tap_duration)
        if not result.success:
            print(f"Tap failed: {result.message or result.error_code}")
            return 1
        print("Tapped match center")
    return 0


def _run_adb(args: argparse.Namespace, config: AppConfig) -> int:
    adb_args = list(args.adb_args)
    if adb_args[:1] == ["--"]:
        adb_args.pop(0)
    if not adb_args:
        raise SystemExit(
            "nier adb: provide an ADB command, for example: nier adb shell input keyevent 4"
        )
    # The ADB command owns stdout, which may carry binary data. Keep Nier's
    # Python-side logger disabled so it cannot corrupt a passthrough stream.
    configure_logging(0)
    try:
        return AdbClient(config.device).passthrough(*adb_args)
    except (NierError, OSError, ValueError) as exc:
        raise SystemExit(f"nier adb: {exc}") from exc


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
    if args.command == "adb":
        return _run_adb(args, config)

    device = connect(config)
    configure_logging(max(config.logging.verbosity, args.verbose))
    try:
        if args.command == "health":
            print(f"Device status: {'ready' if device.health() else 'not ready'}")
        elif args.command == "capabilities":
            _print_capabilities(device.capabilities())
        elif args.command == "screenshot":
            default_format = args.format or "png"
            target = args.output or (
                config.runtime.output_dir / f"screenshot.{default_format}"
            )
            screenshot = device.screenshot(
                target,
                format=args.format,
                quality=args.quality,
                max_width=args.max_width,
                max_height=args.max_height,
            )
            print(
                f"Screenshot saved to: {target} "
                f"({screenshot.width} × {screenshot.height}, "
                f"{screenshot.format.value})"
            )
        elif args.command in {"uidump", "dump-ui"}:
            dump = device.dump_ui(
                prefer_webview=not args.no_webview,
                include_invisible=args.include_invisible,
            )
            document = device.parse_uidump(dump)
            extension = args.format
            target = args.output or config.runtime.output_dir / f"ui.{extension}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if args.format == "json":
                contents = json.dumps(
                    document.to_dict(
                        include_raw=args.include_raw,
                        max_nodes=None,
                        max_text_length=None,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                contents = dump.xml
            target.write_text(contents, encoding="utf-8")
            print(f"UI dump saved to: {target}")
            print(f"Source: {dump.source.value}")
            if dump.warning:
                print(f"Note: {dump.warning}")
            print("UI hierarchy:")
            print(device.format_tree(document))
        elif args.command == "locate":
            result = _run_locate(device, args)
            device.save_run()
            return result
        device.save_run()
        return 0
    finally:
        device.close()
