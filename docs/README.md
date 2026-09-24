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
| [`icon-matching.md`](icon-matching.md) | Optional screenshot template matching for locating UI icons |
| [`text-matching.md`](text-matching.md) | OCR-based fuzzy matching of visible text and explicit match actions |
| [`uidump.md`](uidump.md) | UIAutomator/WebView dumps, widget choice chains, and fallback behavior |
| [`webview-devtools.md`](webview-devtools.md) | Root/non-root WebView DevTools setup and CDP DOM dumps |
| [`intent-hook.md`](intent-hook.md) | Root Frida capture and reusable Nier Python Intent launches |
| [`models.md`](models.md) | OCR, LLM, TypeSafe Choice/Noul/Score, and SysOne-driven goal APIs |
| [`web-dashboard.md`](web-dashboard.md) | Local script runner, live execution path, request/response logs, and step debugger |

The normal Python entry point is `from nier import connect`. It returns a
script-friendly `Device` with `tap`, `tap_label`, `swipe`, `text`, `key`,
`list_apps`, `list_app_activities`, `open_app`, `start_activity`, `start_intent`,
`screenshot`, `locate_icon`, `locate_text`, `uidump`, typed `choice`, `noul`,
and `score` methods, chainable `widgets`, and natural-language `llm` and
`sysone` methods. `tap_label` accepts exact text or a compiled regex.
`DeviceSession`, action dataclasses, and request dataclasses remain available as
lower-level extension APIs for custom backends and transport adapters.

Use only authorized devices and applications, and keep provider credentials in
environment variables.

The old [`api-tutorial.md`](api-tutorial.md) path remains as a compatibility
entry point to this index.

Runnable scripts are collected in
[`../examples/README.md`](../examples/README.md).
