# WebView instrumentation

This optional component separates WebView instrumentation from the uinput
input backend.

Activity Intent capture is provided by the LSPosed module packaged in
`backend/nier-android`; it does not use this Frida component. See
[`docs/intent-hook.md`](../../docs/intent-hook.md).

## Root mode

Root mode uses a host-side `frida` package and a root-capable
`frida-server` running on the authorized device. It can attach to an existing
process or spawn the target package suspended, load the hook before resume,
and force `WebView.setWebContentsDebuggingEnabled(true)`.

Install the optional host dependency:

```bash
python -m pip install -e '.[hook]'
```

The extra currently pins Frida below 17 because this agent is intentionally a
plain JavaScript `create_script()` payload. Frida 17 moved the Java bridge out
of the automatically bundled runtime; a future compiler-based agent can relax
that pin after bundling `frida-java-bridge` explicitly.

Push a matching `frida-server` build to the device and configure:

```yaml
hook:
  mode: root
  target_package: com.example.authorized.app
  spawn: true
  frida_server_path: /data/local/tmp/frida-server
  auto_start_frida_server: false
  force_system_back: false
```

The server must be started separately when `auto_start_frida_server` is false.
Setting it to true lets Nier start the configured path through root ADB.

## Force the platform Back behavior

Some applications consume Back through `OnBackInvokedCallback`, AndroidX
`OnBackPressedDispatcher`, or legacy activity callbacks. For an authorized
rooted test target, opt in to the best-effort Frida override:

```yaml
hook:
  mode: root
  target_package: com.example.authorized.app
  spawn: true
  force_system_back: true
```

The hook blocks common platform/AndroidX callback registrations and redirects
loaded, and subsequently loaded, application `onBackPressed`/`dispatchKeyEvent`
handlers to the platform activity default. `spawn: true` is recommended
because attach mode cannot remove every callback that was already registered.
Native engines and custom navigation stacks may require a target-specific Frida
script. The option is disabled by default and is rejected in non-root mode.

## Non-root mode

Non-root mode does not use `su`, Frida injection, ptrace, or process attach. An
arbitrary third-party app cannot be hooked this way. The target application
must explicitly integrate and call:

```kotlin
WebViewDebugController.enable()
```

before creating its WebView. The helper is in the optional Android module at
`backend/nier-android/app/src/main/java/icu/rina/nier/backend/WebViewDebugController.kt`.

After debugging is enabled, `AdbBackend.dump_ui(prefer_webview=True)` uses
`src/nier/webview.py` to discover the target through the WebView abstract Unix
socket, create a temporary host-local ADB forward, and request the DOM with
Chrome DevTools Protocol. The forward is removed after each dump. Both root
and cooperative non-root modes use this same CDP extraction path; the only
difference is how debugging is enabled.
