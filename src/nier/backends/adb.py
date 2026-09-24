"""Default host-side backend using direct ADB commands."""

from __future__ import annotations

import hashlib
import re
import shlex
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from io import BytesIO

from ..adb import AdbClient, PersistentRootShell
from ..config import DeviceConfig, HookConfig, HookMode, InputTextConfig
from ..errors import (
    BackendError,
    BackendUnavailable,
    HookUnavailable,
    NierError,
    ProtocolError,
)
from ..hooks import HookSession, WebViewHook, create_webview_hook
from ..input import TextInputBackend, create_text_input_backend
from ..logging_utils import step
from ..protocol import (
    PROTOCOL_VERSION,
    Action,
    ActionResult,
    ActivityInfo,
    Capabilities,
    Click,
    DumpUiRequest,
    ImageFormat,
    InputText,
    Key,
    KeyCode,
    Screenshot,
    ScreenshotRequest,
    Swipe,
    UiDump,
    UiSource,
    normalize_activity_component,
    normalize_intent,
    validate_package_name,
)
from ..webview import WebViewDevTools

_ANDROID_KEYCODES = {
    KeyCode.BACK: "4",
    KeyCode.HOME: "3",
    KeyCode.ENTER: "66",
    KeyCode.RECENTS: "187",
    KeyCode.POWER: "26",
    KeyCode.VOLUME_UP: "24",
    KeyCode.VOLUME_DOWN: "25",
}
_ACTIVITY_COMPONENT = re.compile(
    r"(?P<package>[A-Za-z0-9_.$-]+)/(?P<activity>[A-Za-z0-9_.$-]+)"
)
_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_.$-]+")
_PACKAGE_SECTION_HEADER = re.compile(r"^ {2}[A-Za-z][A-Za-z0-9 _-]*:\s*$")
_ACTIVITY_MARKERS = (
    ("mResumedActivity:", "resumed_activity"),
    ("topResumedActivity=", "top_resumed_activity"),
    ("mFocusedActivity:", "focused_activity"),
    ("mCurrentFocus=", "current_focus"),
    ("mFocusedApp=", "focused_app"),
)


def _parse_package_names(output: str) -> list[str]:
    """Parse the package identifiers emitted by ``pm list packages``."""
    packages: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        value = line.strip()
        if not value.startswith("package:"):
            continue
        value = value.removeprefix("package:").strip()
        # ``pm list packages -f`` emits ``path=package``. The default command
        # does not, but accepting it keeps the parser useful with compatible
        # package-manager output.
        if "=" in value:
            value = value.rsplit("=", 1)[1].strip()
        if not value or _PACKAGE_NAME.fullmatch(value) is None or value in seen:
            continue
        seen.add(value)
        packages.append(value)
    return packages


def _activity_class_name(package: str, activity: str) -> str:
    if activity.startswith("."):
        return f"{package}{activity}"
    if activity.startswith(f"{package}."):
        return activity
    return f"{package}.{activity}"


def _parse_app_activity_names(output: str, package: str) -> list[str]:
    """Parse Activity class names from a package ``dumpsys`` response.

    Android versions differ in how much detail they print under the
    ``Activities:`` section. Prefer that section so receivers and services are
    not mistaken for Activities, then use an Activity-labelled fallback for
    older/vendor-specific output.
    """
    names: list[str] = []
    seen: set[str] = set()
    in_activities = False
    saw_activities_section = False

    def add_from_line(line: str) -> None:
        match = _ACTIVITY_COMPONENT.search(line)
        if match is None or match.group("package") != package:
            return
        name = _activity_class_name(package, match.group("activity"))
        if name not in seen:
            seen.add(name)
            names.append(name)

    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "Activities:":
            in_activities = True
            saw_activities_section = True
            continue
        if in_activities and _PACKAGE_SECTION_HEADER.fullmatch(line):
            in_activities = False
        if in_activities:
            add_from_line(line)

    if names or saw_activities_section:
        return names

    # A few vendor builds expose only the resolver table. Its entries are
    # still package/activity components, but the class name itself need not
    # contain the word "Activity".
    in_activity_resolver = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "Activity Resolver Table:":
            in_activity_resolver = True
            continue
        if in_activity_resolver and stripped.endswith(" Resolver Table:"):
            in_activity_resolver = False
        if in_activity_resolver:
            add_from_line(line)
    if names:
        return names

    # Some releases omit both the package section and resolver-table marker.
    # Restrict this final fallback to lines mentioning Activity so that a
    # service or receiver with the same package is not returned accidentally.
    for line in output.splitlines():
        if "activity" not in line.lower():
            continue
        add_from_line(line)
    return names


def _parse_activity_info(output: str) -> ActivityInfo | None:
    lines = output.splitlines()
    for marker, source in _ACTIVITY_MARKERS:
        for line in lines:
            if marker not in line:
                continue
            match = _ACTIVITY_COMPONENT.search(line)
            if match is None:
                continue
            package = match.group("package")
            activity = match.group("activity")
            if activity.startswith("."):
                activity = f"{package}{activity}"
            return ActivityInfo(
                package=package,
                activity=activity,
                component=f"{package}/{activity}",
                source=source,
            )
    return None


def _launch_result(output: str, operation: str) -> ActionResult:
    """Convert ``am start`` output into a checked action result."""
    message = " ".join(output.split())
    normalized = message.lower()
    failure_markers = (
        "error:",
        "error type",
        "exception",
        "unable to start",
        "does not exist",
        "no activity",
        "aborted",
    )
    if any(marker in normalized for marker in failure_markers):
        detail = message[:512] or "Android reported a launch failure"
        raise BackendError(f"{operation} failed: {detail}")
    return ActionResult(success=True, message=message[:512] or "ok")


def _parse_ui_automator_xml(value: bytes | str) -> str:
    """Extract and validate XML returned by the UIAutomator shell command."""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = text.strip()
    if not text:
        raise BackendUnavailable("ADB UIAutomator dump returned no data")

    start = text.find("<")
    end = text.rfind(">")
    if start < 0 or end < start:
        raise ProtocolError("ADB UIAutomator dump did not contain XML")
    xml = text[start : end + 1].strip()
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ProtocolError(f"ADB UIAutomator dump returned malformed XML: {exc}") from exc
    return xml


class _PersistentUinputSession:
    """Reuse one rooted virtual touch device for an ADB backend session."""

    def __init__(
        self,
        adb: AdbClient,
        binary: str,
        device: str,
        width: int,
        height: int,
        *,
        timeout: float,
    ) -> None:
        self._shell: PersistentRootShell = adb.start_root_shell(
            binary,
            "--device",
            device,
            "--width",
            str(width),
            "--height",
            str(height),
            "serve",
            timeout=timeout,
        )

    def click(self, x: int, y: int, duration_ms: int, *, timeout: float) -> None:
        self._shell.request(f"CLICK {x} {y} {duration_ms}", timeout=timeout)

    def swipe(self, points: list[tuple[int, int]], duration_ms: int, *, timeout: float) -> None:
        fields = ["SWIPE", str(duration_ms), str(len(points))]
        fields.extend(str(value) for point in points for value in point)
        self._shell.request(" ".join(fields), timeout=timeout)

    def close(self) -> None:
        self._shell.close()


class AdbBackend:
    """Implement the backend contract without a phone-side network server.

    Screenshots and normal UI dumps are copied directly over ADB. An explicit
    WebView UI request may use a temporary host-local ADB forward. Touch
    actions use a rooted persistent ``nier-uinput serve`` session when it is
    installed on the phone; ordinary Android ``input`` commands remain the
    portable fallback.
    """

    def __init__(
        self,
        config: DeviceConfig,
        *,
        hook_config: HookConfig | None = None,
        input_text_config: InputTextConfig | None = None,
    ) -> None:
        self.config = config
        self.hook_config = hook_config or HookConfig()
        self.input_text_config = input_text_config or InputTextConfig()
        self.adb = AdbClient(config)
        self._screen_size: tuple[int, int] | None = None
        self._rooted: bool | None = None
        self._uinput: bool | None = None
        self._uinput_session: _PersistentUinputSession | None = None
        self._webview_hook: WebViewHook | None = None
        self._webview_hook_session: HookSession | None = None
        self._webview_pid: int | None = None
        self._text_input: TextInputBackend = create_text_input_backend(
            self.adb,
            self.input_text_config,
        )

    def health(self) -> bool:
        self.adb.ensure_device()
        return True

    def capabilities(self) -> Capabilities:
        width, height = self._read_screen_size()
        rooted = self._is_rooted()
        return Capabilities(
            protocol_version=PROTOCOL_VERSION,
            device_id=self._read_setting("secure", "android_id"),
            model=self._read_property("ro.product.model"),
            screen_width=width,
            screen_height=height,
            is_rooted=rooted,
            supports_uinput=self._supports_uinput() if rooted else False,
            supports_ui_automator=True,
            supports_webview_debugging=bool(self.hook_config.target_package),
            action_names=(
                "click",
                "swipe",
                "input_text",
                "key",
                "screenshot",
                "dump_ui",
                "list_apps",
                "list_app_activities",
                "open_app",
                "start_activity",
                "start_intent",
            ),
        )

    def execute(self, action: Action) -> ActionResult:
        width, height = self._read_screen_size()
        if isinstance(action, Click):
            x, y = self._coordinates(action.point.x, action.point.y, action.point.normalized, width, height)
            if self._supports_uinput():
                self._run_uinput_click(
                    x,
                    y,
                    action.duration_ms,
                    width=width,
                    height=height,
                    timeout=max(self.config.connect_timeout_seconds, action.duration_ms / 1000 + 2),
                )
            else:
                if action.duration_ms > 0:
                    # `input tap` has no duration argument; a stationary swipe
                    # keeps the touch down for the requested hold time.
                    self.adb.shell(
                        "input",
                        "swipe",
                        str(x),
                        str(y),
                        str(x),
                        str(y),
                        str(action.duration_ms),
                    )
                else:
                    self.adb.shell("input", "tap", str(x), str(y))
        elif isinstance(action, Swipe):
            points = [
                self._coordinates(point.x, point.y, point.normalized, width, height)
                for point in action.points
            ]
            if self._supports_uinput():
                self._run_uinput_swipe(
                    points,
                    action.duration_ms,
                    width=width,
                    height=height,
                    timeout=max(self.config.connect_timeout_seconds, action.duration_ms / 1000 + 2),
                )
            else:
                start = points[0]
                end = points[-1]
                self.adb.shell(
                    "input",
                    "swipe",
                    str(start[0]),
                    str(start[1]),
                    str(end[0]),
                    str(end[1]),
                    str(action.duration_ms),
                )
        elif isinstance(action, InputText):
            self._text_input.send(action.text)
        elif isinstance(action, Key):
            if action.key_code is KeyCode.BACK and self.hook_config.force_system_back:
                self._ensure_root_hook_for_back()
            try:
                key_code = _ANDROID_KEYCODES[action.key_code]
            except KeyError as exc:
                raise ProtocolError(f"unsupported key code: {action.key_code}") from exc
            self.adb.shell("input", "keyevent", key_code)
        else:
            raise ProtocolError(f"unsupported action type: {type(action).__name__}")
        return ActionResult(success=True, message="ok")

    def screenshot(self, request: ScreenshotRequest | None = None) -> Screenshot:
        request = request or ScreenshotRequest()
        raw = self.adb.exec_out("screencap", "-p")
        if not raw:
            raise BackendUnavailable("ADB screencap returned no data")

        if request.format is ImageFormat.PNG and request.max_width <= 0 and request.max_height <= 0:
            width, height = self._png_dimensions(raw)
            data = raw
        else:
            data, width, height = self._encode_image(raw, request)
        return Screenshot(
            data=data,
            format=request.format,
            width=width,
            height=height,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def dump_ui(self, request: DumpUiRequest | None = None) -> UiDump:
        request = request or DumpUiRequest()
        if request.prefer_webview and self.hook_config.target_package:
            try:
                xml = self._dump_webview()
            except (NierError, OSError, TimeoutError) as exc:
                warning = f"WebView DevTools unavailable ({exc}); used UIAutomator fallback"
            else:
                return UiDump(
                    xml=xml,
                    source=UiSource.WEBVIEW_DEVTOOLS,
                    complete=True,
                )
        else:
            warning = "WebView target package is not configured; used UIAutomator fallback"

        xml = self._dump_ui_automator()
        source = UiSource.UIAUTOMATOR
        if request.prefer_webview:
            source = UiSource.UIAUTOMATOR_FALLBACK
        else:
            warning = ""
        return UiDump(xml=xml, source=source, complete=bool(xml), warning=warning)

    def _dump_ui_automator(self) -> str:
        """Capture UIAutomator XML without depending on shared device storage."""
        direct_error: BackendError | None = None
        try:
            raw = self.adb.exec_out(
                "uiautomator",
                "dump",
                "--compressed",
                "/dev/stdout",
            )
            return _parse_ui_automator_xml(raw)
        except (BackendUnavailable, TimeoutError) as exc:
            direct_error = exc if isinstance(exc, BackendError) else BackendUnavailable(str(exc))

        # Some older/OEM adb implementations do not support exec-out for the
        # uiautomator command. Keep the file-based path as a compatibility
        # fallback, but always remove the temporary device-side file.
        remote_path = "/sdcard/nier-ui.xml"
        try:
            self.adb.shell("uiautomator", "dump", "--compressed", remote_path)
            return _parse_ui_automator_xml(self.adb.shell("cat", remote_path))
        except (BackendError, TimeoutError) as fallback_error:
            if direct_error is None:
                raise
            raise BackendUnavailable(
                "UIAutomator dump failed via exec-out "
                f"({direct_error}); file fallback failed ({fallback_error})"
            ) from fallback_error
        finally:
            self.adb.shell("rm", "-f", remote_path, check=False)

    def current_activity(self) -> ActivityInfo | None:
        """Read the foreground Activity from standard Android dumpsys output."""
        last_error: BackendError | None = None
        for command in (("activity", "activities"), ("window", "windows")):
            try:
                output = self.adb.shell("dumpsys", *command)
            except BackendError as exc:
                last_error = exc
                continue
            info = _parse_activity_info(output)
            if info is not None:
                step(
                    "current-activity",
                    available=True,
                    component=info.component,
                    source=info.source,
                )
                return info
        if last_error is not None:
            raise last_error
        step("current-activity", available=False, reason="not-reported")
        return None

    def list_apps(self) -> list[str]:
        """Return installed package names from Android's package manager."""
        packages = _parse_package_names(self.adb.shell("pm", "list", "packages"))
        step("list-apps", count=len(packages))
        return packages

    def list_app(self) -> list[str]:
        """Compatibility alias for :meth:`list_apps`."""
        return self.list_apps()

    def list_app_activities(self, package: str) -> list[str]:
        """Return fully qualified Activity class names declared by ``package``."""
        package = validate_package_name(package)
        activities = _parse_app_activity_names(
            self.adb.shell("dumpsys", "package", package),
            package,
        )
        step("list-app-activities", package=package, count=len(activities))
        return activities

    def list_app_activity(self, package: str) -> list[str]:
        """Compatibility alias for :meth:`list_app_activities`."""
        return self.list_app_activities(package)

    def open_app(self, package: str, *, restart: bool = False) -> ActionResult:
        """Open the package's launcher Activity, optionally restarting it.

        Restarting force-stops the app process and clears its Activity task
        before launch, but does not clear its stored data. The operation is
        sent once and is never automatically retried.
        """
        package = validate_package_name(package)
        if restart:
            self.adb.shell("am", "force-stop", package)
        start_arguments = ["am", "start"]
        if restart:
            start_arguments.append("--activity-clear-task")
        start_arguments.extend(
            [
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
                "-p",
                package,
            ]
        )
        output = self.adb.shell(*start_arguments)
        operation = "restart" if restart else "open"
        return _launch_result(output, f"{operation} app {package!r}")

    def launch_app(self, package: str, *, restart: bool = False) -> ActionResult:
        """Compatibility alias for :meth:`open_app`."""
        return self.open_app(package, restart=restart)

    def start_activity(self, package: str, activity: str) -> ActionResult:
        """Start one Activity identified by a class name or component."""
        package = validate_package_name(package)
        component = normalize_activity_component(package, activity)
        output = self.adb.shell("am", "start", "-n", component)
        return _launch_result(output, f"start Activity {component!r}")

    def start_intent(self, intent: Mapping[str, object]) -> ActionResult:
        """Start a validated captured Intent once through Android's ``am``."""
        value = normalize_intent(intent)
        arguments = ["am", "start"]
        component = value["component"]
        if component is not None:
            assert isinstance(component, Mapping)
            arguments.extend(
                ["-n", f"{component['package']}/{component['class']}"]
            )
        for option, field_name in (
            ("-a", "action"),
            ("-d", "data"),
            ("-t", "type"),
            ("-p", "package"),
        ):
            field_value = value[field_name]
            if field_value is not None:
                arguments.extend([option, str(field_value)])
        flags = value["flags"]
        if flags is not None:
            arguments.extend(["-f", str(flags)])
        categories = value["categories"]
        assert isinstance(categories, list)
        for category in categories:
            arguments.extend(["-c", category])

        extras = value["extras"]
        assert isinstance(extras, Mapping)
        extra_options = {
            "null": "--esn",
            "string": "--es",
            "boolean": "--ez",
            "int": "--ei",
            "long": "--el",
            "float": "--ef",
            "uri": "--eu",
            "component": "--ecn",
            "string_array": "--esa",
            "int_array": "--eia",
            "long_array": "--ela",
            "float_array": "--efa",
        }
        for name, extra in extras.items():
            assert isinstance(extra, Mapping)
            kind = str(extra["type"])
            option = extra_options[kind]
            extra_value = extra["value"]
            arguments.extend([option, name])
            if kind == "null":
                continue
            if kind == "component":
                assert isinstance(extra_value, Mapping)
                rendered = f"{extra_value['package']}/{extra_value['class']}"
            elif kind.endswith("_array"):
                assert isinstance(extra_value, list)
                rendered = ",".join(str(item) for item in extra_value)
            elif kind == "boolean":
                rendered = "true" if extra_value else "false"
            else:
                rendered = str(extra_value)
            arguments.append(rendered)

        # ``adb shell`` parses one remote command string. Quote each token so
        # captured values with spaces or shell metacharacters remain data.
        command = shlex.join(arguments)
        if len(command.encode("utf-8")) > 64 * 1024:
            raise ValueError("captured Intent exceeds the 64 KiB ADB command limit")
        output = self.adb.shell(command)
        _launch_result(output, "start captured Activity Intent")
        return ActionResult(success=True, message="captured Activity Intent started")

    def open_activity(self, package: str, activity: str) -> ActionResult:
        """Compatibility alias for :meth:`start_activity`."""
        return self.start_activity(package, activity)

    def close(self) -> None:
        """Close persistent input, hook, and rooted uinput resources."""
        self._text_input.close()
        hook_session = self._webview_hook_session
        self._webview_hook_session = None
        self._webview_pid = None
        if hook_session is not None:
            hook_session.close()
        session = self._uinput_session
        self._uinput_session = None
        if session is not None:
            session.close()

    def _dump_webview(self) -> str:
        target_package = self.hook_config.target_package
        if not target_package:
            raise BackendUnavailable("hook.target_package is required for WebView DevTools")

        hook = self._get_webview_hook()
        try:
            if hook.capabilities.mode is HookMode.ROOT:
                self._ensure_root_hook_session(target_package)
            return WebViewDevTools(
                self.adb,
                package=target_package,
                pid=self._webview_pid,
                timeout=self.hook_config.timeout_seconds,
            ).dump_dom()
        except Exception:
            # A dead target must not leave a stale Frida session attached for
            # the next read attempt. The outer dump_ui method still provides
            # the normal UIAutomator fallback.
            self._discard_webview_hook()
            raise

    def _get_webview_hook(self) -> WebViewHook:
        if self._webview_hook is None:
            self._webview_hook = create_webview_hook(self.hook_config, self.adb)
        return self._webview_hook

    def _ensure_root_hook_for_back(self) -> None:
        target_package = self.hook_config.target_package
        if not target_package:
            raise HookUnavailable(
                "hook.target_package is required when hook.force_system_back is enabled"
            )
        hook = self._get_webview_hook()
        if hook.capabilities.mode is not HookMode.ROOT:
            raise HookUnavailable(
                "hook.force_system_back requires root Frida mode; "
                "non-root mode cannot intercept an arbitrary application"
            )
        try:
            self._ensure_root_hook_session(target_package)
        except Exception:
            self._discard_webview_hook()
            raise

    def _ensure_root_hook_session(self, target_package: str) -> HookSession:
        if self._webview_hook is None:
            raise BackendError("WebView hook has not been initialized")
        if self._webview_hook_session is None:
            session = self._webview_hook.attach(target_package)
            pid = getattr(session, "pid", None)
            if not isinstance(pid, int) or pid <= 0:
                session.close()
                raise BackendError("root Frida hook did not return a process id")
            self._webview_hook_session = session
            self._webview_pid = pid
        return self._webview_hook_session

    def _discard_webview_hook(self) -> None:
        session = self._webview_hook_session
        self._webview_hook_session = None
        self._webview_pid = None
        if session is not None:
            session.close()

    def _read_screen_size(self) -> tuple[int, int]:
        if self._screen_size is not None:
            return self._screen_size
        output = self.adb.shell("wm", "size")
        matches = re.findall(r"(\d+)x(\d+)", output)
        if not matches:
            raise BackendError(f"unable to determine device screen size: {output.strip()}")
        self._screen_size = int(matches[-1][0]), int(matches[-1][1])
        return self._screen_size

    def _read_property(self, name: str) -> str:
        return self.adb.shell("getprop", name).strip()

    def _read_setting(self, namespace: str, name: str) -> str:
        value = self.adb.shell("settings", "get", namespace, name).strip()
        return "" if value == "null" else value

    def _is_rooted(self) -> bool:
        if self._rooted is None:
            self._rooted = self.adb.is_root()
        return self._rooted

    def _supports_uinput(self) -> bool:
        if self._uinput is not None:
            return self._uinput
        if not self.config.use_uinput or not self.config.uinput_binary or not self._is_rooted():
            self._uinput = False
            return False
        result = self.adb.root_shell(
            self.config.uinput_binary,
            "probe",
            "--device",
            self.config.uinput_device,
            check=False,
        )
        output = AdbClient._decode(result.stdout)
        fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        self._uinput = (
            result.returncode == 0
            and fields.get("root") == "true"
            and fields.get("writable") == "true"
            and fields.get("persistent") == "true"
        )
        return self._uinput

    def _ensure_uinput_session(self, width: int, height: int, *, timeout: float) -> _PersistentUinputSession:
        if self._uinput_session is None:
            self._uinput_session = _PersistentUinputSession(
                self.adb,
                self.config.uinput_binary,
                self.config.uinput_device,
                width,
                height,
                timeout=timeout,
            )
        return self._uinput_session

    def _run_uinput_click(
        self,
        x: int,
        y: int,
        duration_ms: int,
        *,
        width: int,
        height: int,
        timeout: float,
    ) -> None:
        try:
            self._ensure_uinput_session(width, height, timeout=timeout).click(
                x,
                y,
                duration_ms,
                timeout=timeout,
            )
        except BackendError:
            self._discard_uinput_session()
            raise

    def _run_uinput_swipe(
        self,
        points: list[tuple[int, int]],
        duration_ms: int,
        *,
        width: int,
        height: int,
        timeout: float,
    ) -> None:
        try:
            self._ensure_uinput_session(width, height, timeout=timeout).swipe(
                points,
                duration_ms,
                timeout=timeout,
            )
        except BackendError:
            self._discard_uinput_session()
            raise

    def _discard_uinput_session(self) -> None:
        session = self._uinput_session
        self._uinput_session = None
        if session is not None:
            session.close()

    @staticmethod
    def _coordinates(x: float, y: float, normalized: bool, width: int, height: int) -> tuple[int, int]:
        if normalized:
            x = x * width
            y = y * height
        return (
            max(0, min(width - 1, int(x))),
            max(0, min(height - 1, int(y))),
        )

    @staticmethod
    def _encode_input_text(text: str) -> str:
        return text.replace("%", "%25").replace(" ", "%s")

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ProtocolError("ADB screencap did not return a valid PNG")
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")

    @staticmethod
    def _encode_image(data: bytes, request: ScreenshotRequest) -> tuple[bytes, int, int]:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - packaging/environment failure
            raise BackendUnavailable("Pillow is required for JPEG or resized screenshots") from exc

        try:
            with Image.open(BytesIO(data)) as image:
                image.load()
                scale = min(
                    1.0,
                    request.max_width / image.width if request.max_width > 0 else 1.0,
                    request.max_height / image.height if request.max_height > 0 else 1.0,
                )
                if scale < 1.0:
                    image = image.resize(
                        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                if request.format is ImageFormat.JPEG:
                    image = image.convert("RGB")
                output = BytesIO()
                save_options = {"quality": request.quality} if request.format is ImageFormat.JPEG else {}
                image.save(output, format=request.format.value, **save_options)
                encoded = output.getvalue()
                return encoded, image.width, image.height
        except (OSError, ValueError) as exc:
            raise ProtocolError(f"failed to encode ADB screenshot: {exc}") from exc
