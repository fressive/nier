# UI dump API

## Script API

`uidump` returns the XML/HTML text and can save it in the same call:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    xml = phone.uidump(
        "artifacts/ui.xml",
        prefer_webview=False,
    )
    print(xml)
```

Use `dump_ui` when source and fallback metadata are needed:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    dump = phone.dump_ui(prefer_webview=True)
    print(dump.xml, dump.source, dump.complete, dump.warning)
```

Transport adapters can still call
`DeviceSession.dump_ui(DumpUiRequest(...))`; ordinary scripts do not need a
request object.

## Parse and query nodes

Use `parse_uidump` to turn a saved dump or raw XML/HTML into searchable nodes:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    ui = phone.parse_uidump()
    login = ui.find(resource_id="com.example:id/login")
    if login is not None and login.center is not None:
        phone.tap(*login.center)
```

The same parser works offline:

```python
from pathlib import Path

from nier import parse_uidump


ui = parse_uidump(Path("artifacts/ui.xml"))
print(ui.find(text="设置"))
```

Available queries include exact `text`, substring `text_contains`,
`resource_id`, `class_name`, `content_desc`, `tag`, `clickable`, and `visible`:

```python
buttons = ui.find_all(
    class_name="android.widget.Button",
    clickable=True,
    visible=True,
)
```

Each `UiNode` exposes `tag`, `attributes`, `text`, `text_content`,
`resource_id`, `class_name`, `content_desc`, `bounds`, `center`, and
`children`. `walk()` returns the node and all descendants in document order.

## Choose and click a UI widget

`Device.widgets()` binds parsed nodes to the current device so a typed Choice
can select a candidate and the host can safely tap its center. The explicit
`.clickable()` filter is optional; `.choice()` itself filters out nodes not
marked clickable, explicitly hidden nodes, or nodes without usable bounds:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    # Optional narrowing step:
    selected = phone.widgets().clickable().choice("进入设置")
    selected.click()

    # Or let choice() filter the original widget list:
    phone.widgets().choice("打开通知设置").click()
```

The configured TypeSafe provider sees bounded candidate IDs and labels, not
coordinates. Selection failures raise `ModelError`; if there are no safely
clickable candidates, `UiElementNotFound` is raised without tapping. A WebView
DOM dump can still be searched, but DOM elements without screen-space `bounds`
are not eligible for this click chain; use UIAutomator when screen bounds are
needed. `Device.widgets()` prefers UIAutomator by default for this reason. Run
this only against an authorized device. `DeviceSession` can retry
read-style UI dumps, but the final tap is a device action and is never retried
automatically.

Use `to_dict()` when a UI tree must be passed to a model or serialized as
JSON. `UiDocument.to_dict()` returns source/completeness metadata and a
bounded `root` tree by default; `max_nodes=None` and
`max_text_length=None` opt into the complete parsed tree. `include_raw=True`
adds the original XML/HTML when a consumer needs it:

```python
import json
from pathlib import Path

from nier import parse_uidump


ui = parse_uidump("<hierarchy><node text='登录' clickable='true' /></hierarchy>")
payload = ui.to_dict(max_nodes=100)
target = Path("artifacts/ui.json")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Structured UI saved to: {target} ({len(ui.walk())} nodes)")
```

The structured form is JSON-ready and keeps element hierarchy, normalized
fields such as `resource_id` and `content_desc`, geometry (`bounds` and
`center`), interaction flags, and original `attributes`. Truncated trees
contain a `truncated` marker so a model can distinguish missing descendants
from an empty subtree.

`UiDump` has these fields:

- `xml`: raw UIAutomator XML or WebView DOM HTML;
- `source`: `UIAUTOMATOR`, `WEBVIEW_DEVTOOLS`, or
  `UIAUTOMATOR_FALLBACK`;
- `complete`: whether a usable dump was obtained;
- `warning`: fallback or diagnostic information.

## Convenience provider

`UiDumpProvider` returns an equivalent `UiSnapshot`:

```python
from nier.ui import UiDumpProvider


snapshot = UiDumpProvider(backend).capture(
    prefer_webview=True,
    include_invisible=False,
)
```

## Current implementation

The ADB backend normally uses:

```text
adb exec-out uiautomator dump --compressed /dev/stdout
```

This avoids relying on a shared device-storage path. If an older or OEM ADB
implementation cannot stream the dump, Nier falls back to a temporary
`/sdcard/nier-ui.xml` file and removes it after reading, including when the
read fails. When
`hook.target_package` is configured, `prefer_webview=True` first uses the
WebView DevTools Protocol and returns `WEBVIEW_DEVTOOLS` with the current DOM.
The host temporarily forwards the app's abstract DevTools socket through ADB
and removes that forward after the request. If the target is not debug-enabled,
not running, or CDP fails, the backend returns `UIAUTOMATOR_FALLBACK` with a
warning. Use `prefer_webview=False` to request UIAutomator directly.

Root mode enables debugging with Frida. LSPosed mode uses the installed Nier
module and requires it to be enabled and scoped to the target package. Non-root
mode does not inject into an arbitrary application; the target app must call
`WebViewDebugController.enable()` before creating its WebView. See the
[WebView DevTools guide](webview-devtools.md) for setup and examples.

The runnable [`07_webview_uidump.py`](../examples/07_webview_uidump.py) example
calls `phone.uidump(..., prefer_webview=True)`, formats the parsed tree through
`phone.format_tree(document)`, and saves both that tree and the complete raw
HTML/XML. The formatter shortens text, shows only true-valued boolean
attributes by name without appending `=True`, and uses ANSI colors by default.
Pass `color=False` for plain text such as a file. Use the raw dump for exact
source data and `dump_ui()` when source and fallback warnings are needed.

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    document = phone.parse_uidump(prefer_webview=True)
    print(phone.format_tree(document))
    print(phone.format_tree(document.root, color=False))
```

The `include_invisible` field is part of the domain contract. The ADB
implementation currently accepts it but does not yet alter its dump command
based on that flag.

The parser intentionally returns source nodes and coordinates; it does not
automatically click a matching node. Use `node.center` with `phone.tap` after
reviewing the match.
