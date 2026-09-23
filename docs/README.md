# Nier API documentation

The API documentation is organized by feature. Start with
[`getting-started.md`](getting-started.md), then open the page for the API you
are integrating.

| Page | Covers |
| --- | --- |
| [`getting-started.md`](getting-started.md) | Installation, configuration, sessions, CLI, errors, and authorization |
| [`backend.md`](backend.md) | Backend protocol and custom backend implementations |
| [`remote-adb.md`](remote-adb.md) | ADB-over-TCP devices and remote ADB servers |
| [`control.md`](control.md) | Click, swipe, text, key events, coordinates, and retry behavior |
| [`apps.md`](apps.md) | Installed package/Activity inspection and app/Activity launches |
| [`screenshot.md`](screenshot.md) | Screenshot options, encoding, dimensions, and digest |
| [`uidump.md`](uidump.md) | UIAutomator/WebView dump APIs and fallback behavior |
| [`webview-devtools.md`](webview-devtools.md) | Root/non-root WebView DevTools setup and CDP DOM dumps |
| [`models.md`](models.md) | OCR, decision, LLM, TypeSafe Jev, and Jev-driven goal APIs |

The normal Python entry point is `from nier import connect`. It returns a
script-friendly `Device` with `tap`, `tap_label`, `swipe`, `text`, `key`,
`list_apps`, `list_app_activities`, `open_app`, `start_activity`, `screenshot`,
`uidump`, and natural-language `run` methods. `tap_label` accepts exact text or
a compiled regex. `DeviceSession`, action dataclasses, and request dataclasses
remain available as lower-level extension APIs for custom backends and
transport adapters.

Use only authorized devices and applications, and keep provider credentials in
environment variables.

The old [`api-tutorial.md`](api-tutorial.md) path remains as a compatibility
entry point to this index.

Runnable scripts are collected in
[`../examples/README.md`](../examples/README.md).
