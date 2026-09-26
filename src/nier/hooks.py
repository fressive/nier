"""Authorized WebView instrumentation with explicit root and module modes.

Root mode uses a Frida session attached to the target process. Non-root mode
never attempts to attach to an arbitrary process; it requires the target app
to opt in by calling the small Android WebView debug controller supplied with
the repository. Root mode can also opt into a best-effort system-Back policy.
LSPosed mode verifies that the installed Nier module enabled debugging in the
target process and does not use Frida.
"""

from __future__ import annotations

import json
import re
import shlex
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Protocol

from .adb import AdbClient
from .config import HookConfig, HookMode
from .errors import HookError, HookUnavailable
from .protocol import validate_package_name

DEFAULT_WEBVIEW_SCRIPT = """
'use strict';

const NIER_FORCE_SYSTEM_BACK = __NIER_FORCE_SYSTEM_BACK__;
const NIER_TARGET_PACKAGE = __NIER_TARGET_PACKAGE__;

function emit(type, details) {
  const payload = details || {};
  payload.type = type;
  send(payload);
}

function installForceSystemBack() {
  const installed = [];
  let activityOnBackPressed = null;

  let platformRegistrationHooked = false;
  let androidXRegistrationHooked = false;
  let androidXDispatchHooked = false;
  let resolvingApplicationClass = false;
  const hookedApplicationClasses = {};

  function isTargetClass(className) {
    return NIER_TARGET_PACKAGE &&
      (className === NIER_TARGET_PACKAGE ||
       className.startsWith(NIER_TARGET_PACKAGE + '.'));
  }

  function hookPlatformRegistration() {
    if (platformRegistrationHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('android.window.OnBackInvokedDispatcher');
      const register = dispatcher.registerOnBackInvokedCallback.overload(
        'int',
        'android.window.OnBackInvokedCallback'
      );
      register.implementation = function (priority, callback) {
        emit('back_callback_blocked', {
          framework: 'android.window.OnBackInvokedDispatcher',
          priority: priority,
        });
        return;
      };
      platformRegistrationHooked = true;
      installed.push('platform-registration');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'android.window.OnBackInvokedDispatcher',
        error: String(error),
      });
    }
  }

  function hookAndroidXRegistration() {
    if (androidXRegistrationHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('androidx.activity.OnBackPressedDispatcher');
      dispatcher.addCallback.overloads.forEach(function (overload) {
        overload.implementation = function () {
          emit('back_callback_blocked', {
            framework: 'androidx.activity.OnBackPressedDispatcher',
          });
          return;
        };
      });
      androidXRegistrationHooked = true;
      installed.push('androidx-registration');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'androidx.activity.OnBackPressedDispatcher',
        error: String(error),
      });
    }
  }

  function hookAndroidXDispatch() {
    if (androidXDispatchHooked) {
      return;
    }
    try {
      const dispatcher = Java.use('androidx.activity.OnBackPressedDispatcher');
      const onBackPressed = dispatcher.onBackPressed.overload();
      onBackPressed.implementation = function () {
        const fallbackFields = ['mFallbackOnBackPressed', 'fallbackOnBackPressed'];
        for (let index = 0; index < fallbackFields.length; index += 1) {
          try {
            const fallback = this[fallbackFields[index]].value;
            if (fallback) {
              fallback.run();
              emit('back_default_invoked', {
                framework: 'androidx.activity.OnBackPressedDispatcher',
              });
              return;
            }
          } catch (ignored) {
            // AndroidX field names vary between releases.
          }
        }
        // Keep the original behavior if this AndroidX revision does not
        // expose its fallback runnable to Frida.
        return onBackPressed.call(this);
      };
      androidXDispatchHooked = true;
      installed.push('androidx-dispatch');
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'androidx.activity.OnBackPressedDispatcher.onBackPressed',
        error: String(error),
      });
    }
  }

  function hookApplicationClass(className) {
    if (!isTargetClass(className) || hookedApplicationClasses[className]) {
      return 0;
    }
    hookedApplicationClasses[className] = true;
    let hooks = 0;
    try {
      const clazz = Java.use(className);
      if (clazz.onBackPressed) {
        clazz.onBackPressed.overloads.forEach(function (overload) {
          if (overload.argumentTypes.length !== 0) {
            return;
          }
          overload.implementation = function () {
            emit('back_callback_blocked', {
              framework: className + '.onBackPressed',
            });
            return activityOnBackPressed.call(this);
          };
          hooks += 1;
        });
      }
      if (clazz.dispatchKeyEvent) {
        clazz.dispatchKeyEvent.overloads.forEach(function (overload) {
          const argumentTypes = overload.argumentTypes;
          if (argumentTypes.length !== 1 ||
              String(argumentTypes[0].className) !== 'android.view.KeyEvent') {
            return;
          }
          overload.implementation = function (event) {
            let isBack = false;
            try {
              isBack = event !== null && event.getKeyCode() === 4;
            } catch (ignored) {
              isBack = false;
            }
            if (!isBack) {
              return overload.call(this, event);
            }
            emit('back_callback_blocked', {
              framework: className + '.dispatchKeyEvent',
            });
            activityOnBackPressed.call(this);
            return true;
          };
          hooks += 1;
        });
      }
    } catch (ignored) {
      // A class can disappear while the application is loading.
    }
    return hooks;
  }

  function handleLoadedClass(className) {
    if (className === 'android.window.OnBackInvokedDispatcher') {
      hookPlatformRegistration();
    } else if (className === 'androidx.activity.OnBackPressedDispatcher') {
      hookAndroidXRegistration();
      hookAndroidXDispatch();
    }
    if (isTargetClass(className) && activityOnBackPressed !== null &&
        !resolvingApplicationClass) {
      resolvingApplicationClass = true;
      try {
        const hooks = hookApplicationClass(className);
        if (hooks > 0 && installed.indexOf('application-legacy') === -1) {
          installed.push('application-legacy');
        }
      } finally {
        resolvingApplicationClass = false;
      }
    }
  }

  try {
    const Activity = Java.use('android.app.Activity');
    activityOnBackPressed = Activity.onBackPressed.overload();
  } catch (error) {
    emit('back_hook_warning', {
      framework: 'android.app.Activity',
      error: String(error),
    });
  }

  hookPlatformRegistration();
  hookAndroidXRegistration();
  hookAndroidXDispatch();

  if (NIER_TARGET_PACKAGE && activityOnBackPressed !== null) {
    try {
      Java.enumerateLoadedClassesSync().forEach(function (className) {
        handleLoadedClass(className);
      });
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'application legacy back callbacks',
        error: String(error),
      });
    }

    try {
      const ClassLoader = Java.use('java.lang.ClassLoader');
      let loaderHooks = 0;
      try {
        const loadClass = ClassLoader.loadClass.overload('java.lang.String');
        loadClass.implementation = function (className) {
          const result = loadClass.call(this, className);
          handleLoadedClass(String(className));
          return result;
        };
        loaderHooks += 1;
      } catch (ignored) {
        // Some runtimes expose only the overload with the resolve flag.
      }
      try {
        const loadClassWithResolve = ClassLoader.loadClass.overload(
          'java.lang.String',
          'boolean'
        );
        loadClassWithResolve.implementation = function (className, resolve) {
          const result = loadClassWithResolve.call(this, className, resolve);
          handleLoadedClass(String(className));
          return result;
        };
        loaderHooks += 1;
      } catch (ignored) {
        // The one-argument overload is sufficient on older runtimes.
      }
      if (loaderHooks > 0) {
        installed.push('application-class-loading');
      }
    } catch (error) {
      emit('back_hook_warning', {
        framework: 'java.lang.ClassLoader.loadClass',
        error: String(error),
      });
    }
  }

  emit('back_hook_installed', {frameworks: installed});
  return installed;
}

Java.perform(function () {
  try {
    if (!Java.available) {
      throw new Error('the target process has no Java VM');
    }

    try {
      const WebView = Java.use('android.webkit.WebView');
      const setter = WebView.setWebContentsDebuggingEnabled.overload('boolean');

      setter.implementation = function (enabled) {
        emit('webview_debugging_requested', {
          requested: !!enabled,
          enabled: true,
        });
        return setter.call(this, true);
      };

      // In spawn mode this runs before the app is resumed and before its first
      // WebView is constructed. In attach mode it enables debugging for future
      // WebViews and observes later setter calls.
      // Android requires this static setter to run on the application's main
      // thread. The replacement above still covers later app-side calls;
      // schedule the initial enablement separately for attach mode.
      Java.scheduleOnMainThread(function () {
        try {
          setter.call(WebView, true);
        } catch (error) {
          emit('webview_hook_warning', {error: String(error)});
        }
      });
    } catch (error) {
      // Back enforcement is useful for non-WebView apps as well. A missing or
      // incompatible WebView class must not prevent that requested behavior.
      emit('webview_hook_warning', {error: String(error)});
    }

    const backHooks = NIER_FORCE_SYSTEM_BACK ? installForceSystemBack() : [];
    send({
      type: 'ready',
      mode: 'root',
      force_system_back: NIER_FORCE_SYSTEM_BACK,
      back_hooks: backHooks,
    });
  } catch (error) {
    send({type: 'error', error: String(error)});
  }
});
""".strip()


@dataclass(frozen=True)
class HookEvent:
    """One event emitted by an instrumentation agent."""

    type: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class HookCapabilities:
    """Capabilities and restrictions of the selected hook mode."""

    mode: HookMode
    can_inject: bool
    requires_app_integration: bool
    can_enable_webview_debugging: bool
    reason: str = ""


class HookSession(Protocol):
    """Common lifecycle for a loaded hook session."""

    def next_event(self, timeout: float | None = None) -> HookEvent | None:
        """Return the next agent event, or ``None`` when the timeout expires."""
        ...

    def close(self) -> None:
        """Detach the hook and release instrumentation resources."""
        ...


class WebViewHook(Protocol):
    """Mode-specific WebView hook controller."""

    @property
    def capabilities(self) -> HookCapabilities:
        ...

    def attach(self, package: str | None = None, *, spawn: bool | None = None) -> HookSession:
        ...


class _FridaHookSession:
    def __init__(self, frida_session: Any, script: Any, *, device: Any, pid: int) -> None:
        self._frida_session = frida_session
        self._script = script
        self._device = device
        self.pid = pid
        self._events: Queue[HookEvent] = Queue()
        self._pending: list[HookEvent] = []
        self._lock = threading.RLock()
        self._closed = False

    def load(self) -> None:
        self._script.on("message", self._on_message)
        self._script.load()

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HookUnavailable("Frida hook did not become ready before the timeout")
            try:
                event = self._events.get(timeout=remaining)
            except Empty:
                raise HookUnavailable("Frida hook did not become ready before the timeout")
            if event.type == "ready":
                return
            if event.type == "error":
                raise HookError(str(event.payload.get("error", "Frida agent failed")))
            self._pending.append(event)

    def next_event(self, timeout: float | None = None) -> HookEvent | None:
        if self._pending:
            return self._pending.pop(0)
        try:
            if timeout is None:
                return self._events.get()
            return self._events.get(timeout=timeout)
        except Empty:
            return None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._script.unload()
            except Exception:
                pass
            try:
                self._frida_session.detach()
            except Exception:
                pass

    def _on_message(self, message: Mapping[str, Any], _data: bytes | None) -> None:
        if message.get("type") == "send":
            payload = message.get("payload")
            if isinstance(payload, Mapping):
                event_type = str(payload.get("type", "message"))
                self._events.put(HookEvent(event_type, dict(payload)))
            else:
                self._events.put(HookEvent("message", {"payload": payload}))
            return
        if message.get("type") == "error":
            self._events.put(
                HookEvent(
                    "error",
                    {
                        "error": message.get("description") or message.get("stack") or "Frida agent error",
                    },
                )
            )


class _LsposedWebViewSession:
    """A handle for a target process managed by the LSPosed module."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def next_event(self, timeout: float | None = None) -> HookEvent | None:
        del timeout
        return None

    def close(self) -> None:
        """The LSPosed module lifetime follows the target app process."""


class LsposedWebViewHook:
    """Verify WebView debugging enabled by the scoped Nier LSPosed module."""

    _READY_TAG = "NierWebViewHook:I"

    def __init__(self, adb: AdbClient, config: HookConfig) -> None:
        self._adb = adb
        self._config = config

    @property
    def capabilities(self) -> HookCapabilities:
        return HookCapabilities(
            mode=HookMode.LSPOSED,
            can_inject=True,
            requires_app_integration=False,
            can_enable_webview_debugging=True,
            reason="requires the Nier LSPosed module enabled and scoped to the target app",
        )

    def attach(self, package: str | None = None, *, spawn: bool | None = None) -> HookSession:
        raw_target = package or self._config.target_package or ""
        target = validate_package_name(raw_target.strip())
        should_spawn = self._config.spawn if spawn is None else spawn
        if should_spawn:
            raise HookUnavailable(
                "LSPosed hooks run when the app process starts; enable Nier for this package "
                "in LSPosed, then restart the target app before dumping its WebView"
            )

        pid_output = self._adb.shell("pidof", target, check=False)
        pids = [int(value) for value in re.findall(r"\b\d+\b", pid_output)]
        if not pids:
            raise HookUnavailable(
                f"target process {target} is not running; start it after enabling the Nier LSPosed module"
            )
        log_output = self._adb.shell(
            "logcat",
            "-d",
            "-t",
            "2000",
            "-s",
            self._READY_TAG,
            check=False,
        )
        log_lines = log_output.splitlines()
        for pid in pids:
            ready_record = f"NIER_WEBVIEW_V1|READY|{target}|{pid}|"
            if any(ready_record in line for line in log_lines):
                return _LsposedWebViewSession(pid)

        for pid in pids:
            error_record = f"NIER_WEBVIEW_V1|ERROR|{target}|{pid}|"
            for line in log_lines:
                if error_record not in line:
                    continue
                error_kind = line.split(error_record, 1)[1].split("|", 1)[-1].strip()
                if error_kind:
                    raise HookUnavailable(
                        f"LSPosed WebView hook failed for {target} ({error_kind}); "
                        "check the Nier module status in LSPosed"
                    )

        raise HookUnavailable(
            f"LSPosed did not report WebView debugging for {target}; enable Nier in LSPosed, "
            "add the package to its scope, then force-stop and reopen the app"
        )


def _attach_root_frida_agent(
    adb: AdbClient,
    config: HookConfig,
    package: str,
    *,
    spawn: bool | None,
    source: str,
    agent_name: str,
) -> HookSession:
    """Attach a Frida agent with the shared root/process lifecycle."""
    target = package.strip()
    if not target:
        raise HookError(f"a target package is required for root {agent_name} hooking")
    if not adb.is_root():
        raise HookUnavailable(f"root {agent_name} hook mode requires a rooted device")

    frida = _load_frida()
    if config.auto_start_frida_server:
        _ensure_frida_server(adb, config)

    timeout_ms = int(config.timeout_seconds * 1000)
    try:
        device = frida.get_usb_device(timeout=timeout_ms)
        should_spawn = config.spawn if spawn is None else spawn
        if should_spawn:
            pid = int(device.spawn([target]))
            frida_session = device.attach(pid)
        else:
            pid = _find_process_pid(adb, device, target, timeout=config.timeout_seconds)
            frida_session = device.attach(pid)
        script = frida_session.create_script(source)
        hook_session = _FridaHookSession(frida_session, script, device=device, pid=pid)
        resume_attempted = False
        try:
            hook_session.load()
            hook_session.wait_ready(config.timeout_seconds)
            if should_spawn:
                resume_attempted = True
                device.resume(pid)
        except BaseException:
            hook_session.close()
            if should_spawn and not resume_attempted:
                try:
                    device.resume(pid)
                except Exception:
                    pass
            raise
        return hook_session
    except (HookError, HookUnavailable):
        raise
    except Exception as exc:
        raise HookUnavailable(f"root {agent_name} hook failed for {target}: {exc}") from exc


def _ensure_frida_server(adb: AdbClient, config: HookConfig) -> None:
    """Start the configured server if needed and wait for its process to appear."""
    server_path = shlex.quote(config.frida_server_path)
    missing_message = shlex.quote(
        f"frida-server is missing or not executable: {config.frida_server_path}"
    )
    command = (
        "if pidof frida-server >/dev/null 2>&1; then exit 0; fi; "
        f"if [ ! -x {server_path} ]; then "
        f"echo {missing_message} >&2; exit 1; fi; "
        f"{server_path} >/dev/null 2>&1 & "
        "attempt=0; "
        "while [ \"$attempt\" -lt 40 ]; do "
        "if pidof frida-server >/dev/null 2>&1; then sleep 0.2; exit 0; fi; "
        "sleep 0.1; attempt=$((attempt + 1)); "
        "done; "
        "echo 'frida-server did not start within 4 seconds' >&2; exit 1"
    )
    try:
        adb.root_shell("sh", "-c", command, timeout=6.0)
    except Exception as exc:
        raise HookUnavailable(f"could not start frida-server: {exc}") from exc


class RootFridaWebViewHook:
    """Inject WebView debugging and optional Back policy into a rooted process."""

    def __init__(self, adb: AdbClient, config: HookConfig) -> None:
        self._adb = adb
        self._config = config

    @property
    def capabilities(self) -> HookCapabilities:
        return HookCapabilities(
            mode=HookMode.ROOT,
            can_inject=True,
            requires_app_integration=False,
            can_enable_webview_debugging=True,
            reason="uses Frida and requires a root-capable frida-server",
        )

    def attach(self, package: str | None = None, *, spawn: bool | None = None) -> HookSession:
        target = (package or self._config.target_package or "").strip()
        return _attach_root_frida_agent(
            self._adb,
            self._config,
            target,
            spawn=spawn,
            source=_load_webview_script(
                force_system_back=self._config.force_system_back,
                target_package=target,
            ),
            agent_name="WebView",
        )


def _find_process_pid(adb: AdbClient, device: Any, package: str, *, timeout: float) -> int:
    """Resolve an Android package to a PID before asking Frida to attach.

    Frida's process ``name`` is not guaranteed to equal the Android package
    name (for example, Via reports ``Via`` while its package is ``mark.via``).
    Android's ``pidof`` is package-aware and also handles processes with a
    package suffix. The Frida name lookup remains a fallback for test doubles
    and devices where ``pidof`` is unavailable.
    """
    try:
        output = adb.shell("pidof", package, timeout=timeout, check=False)
    except AttributeError:
        output = ""
    pids = [int(value) for value in re.findall(r"\b\d+\b", output)]
    if pids:
        return pids[0]
    process = device.get_process(package)
    return int(process.pid)


class NonRootWebViewHook:
    """Safe non-root mode for apps that explicitly opt into the hook."""

    @property
    def capabilities(self) -> HookCapabilities:
        return HookCapabilities(
            mode=HookMode.NON_ROOT,
            can_inject=False,
            requires_app_integration=True,
            can_enable_webview_debugging=True,
            reason="the target app must call WebViewDebugController.enable() itself",
        )

    def attach(self, package: str | None = None, *, spawn: bool | None = None) -> HookSession:
        del package, spawn
        raise HookUnavailable(
            "non-root mode cannot inject into an arbitrary app; "
            "integrate WebViewDebugController.enable() into the target app "
            "before creating its WebView"
        )


def create_webview_hook(config: HookConfig, adb: AdbClient) -> WebViewHook:
    """Select the hook implementation without crossing the root boundary."""
    if config.mode is HookMode.ROOT:
        return RootFridaWebViewHook(adb, config)
    if config.mode is HookMode.NON_ROOT:
        return NonRootWebViewHook()
    if config.mode is HookMode.LSPOSED:
        return LsposedWebViewHook(adb, config)
    if adb.is_root():
        return RootFridaWebViewHook(adb, config)
    return NonRootWebViewHook()


def _load_frida() -> Any:
    try:
        import frida
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise HookUnavailable("Frida is not installed; install the hook extra") from exc
    return frida


def _load_webview_script(
    *,
    force_system_back: bool = False,
    target_package: str | None = None,
) -> str:
    """Load the Frida agent and inject the explicitly selected hook policy."""
    script_path = Path(__file__).resolve().parents[2] / "backend" / "nier-frida" / "scripts" / "webview_debug.js"
    try:
        script = script_path.read_text(encoding="utf-8")
    except OSError:
        # Keep an installed host package usable when the repository-side agent
        # file is not present in the wheel.
        script = DEFAULT_WEBVIEW_SCRIPT
    script = script.replace(
        "__NIER_FORCE_SYSTEM_BACK__",
        "true" if force_system_back else "false",
        1,
    )
    script = script.replace(
        "__NIER_TARGET_PACKAGE__",
        json.dumps(target_package or ""),
        1,
    )
    return script
