# WebView DevTools

Nier can dump the DOM of a debug-enabled Android WebView through Chrome
DevTools Protocol (CDP). The result is returned by the normal
`dump_ui(prefer_webview=True)` API with source `WEBVIEW_DEVTOOLS`.

## Configuration

Set the target application package in `config/nier.yaml`:

```yaml
hook:
  mode: lsposed
  target_package: com.example.authorized.app
  spawn: false
  force_system_back: false
  timeout_seconds: 10
```

`auto` selects root mode only when ADB can execute a root shell. Set
`mode: root` to require Frida injection, `mode: non-root` to require
cooperative application integration, or `mode: lsposed` to use the installed
Nier LSPosed module without Frida.

Root detection accepts an already-root `adbd` shell, `su -M -c`, or standard
`su -c`. When root comes from `su`, its manager must grant root access to the
ADB shell.

## Root mode

Install the optional host dependency and run a matching root-capable
`frida-server` on the authorized device:

```bash
python -m pip install -e '.[hook]'
```

Nier can attach to an existing process or spawn the package before resume. The
Frida agent enables `WebView.setWebContentsDebuggingEnabled(true)`. The host
then finds `webview_devtools_remote_<pid>`, temporarily forwards it through
ADB, and queries the CDP page target.

For an authorized rooted target whose app consumes Back callbacks, set
`force_system_back: true`. This installs the same Frida session before a Back
action, blocks common platform/AndroidX callback registrations, and redirects
loaded Java activity handlers to the platform default. Use `spawn: true` when
possible so the hook is installed before the app registers callbacks. This is
best-effort and does not guarantee behavior for native or application-specific
navigation code; it is unavailable in non-root and LSPosed modes.

## LSPosed mode

Build and install the Nier Android APK, enable **Nier Backend** in LSPosed
Manager, and add only authorized target packages to its scope. Set
`hook.mode: lsposed`. The module enables WebView debugging during application
startup and overrides later calls that attempt to disable it. The host checks
the module's readiness record for the running process before requesting the
DOM through CDP. This mode does not use Frida or root shell access.

LSPosed applies hooks when an application process starts. After enabling the
module, changing its scope, or installing an updated APK, force-stop and reopen
the target app before running `uidump`. Nier does not restart the app
automatically in LSPosed mode.

## Non-root mode

Non-root mode does not inject into arbitrary applications. The target app must
call the supplied helper before constructing its first WebView:

```kotlin
WebViewDebugController.enable()
```

Once the app has opted in, the host uses the exact same CDP and DOM extraction
path as root mode. No phone-side network service is started.

## Python API

```python
from nier.backends.adb import AdbBackend
from nier.config import load_config
from nier.session import DeviceSession

config = load_config("config/nier.yaml")
backend = AdbBackend(config.device, hook_config=config.hook)
session = DeviceSession(backend)
try:
    dump = session.dump_ui(prefer_webview=True)
    print(dump.source, dump.complete, dump.warning)
    print(dump.xml)
finally:
    session.close()
```

If the target is not running, debugging is not enabled, the WebView has not
created its DevTools socket yet, or CDP fails, Nier returns UIAutomator XML
with source `UIAUTOMATOR_FALLBACK` and a warning. The temporary ADB forward is
removed on both success and failure.
