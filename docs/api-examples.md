# Public API examples

This page collects the normal, script-facing Python API in one place. The
examples use `Device`, returned by `nier.connect()`, and the standalone
`nier.parse_uidump()` helper. For setup details and complete feature guides,
see the links in the [API documentation index](README.md).

Use only devices and applications you are authorized to inspect or control.
The examples that tap, type, launch apps, or run a goal can change device state.
Read operations may retry transient backend failures; device actions are sent
once and are never automatically retried.

## API map

| Area | Public methods and aliases | Guide |
| --- | --- | --- |
| Connection and lifecycle | `connect`, context manager, `close`, `save_run` | [Getting started](getting-started.md) |
| Device status | `health`, `capabilities`, `current_activity` | [Getting started](getting-started.md) |
| Apps and Activities | `list_apps` (`list_app`), `list_app_activities` (`list_app_activity`), `open_app` (`launch_app`), `start_activity` (`open_activity`), `start_intent` | [Apps](apps.md), [Intent hook](intent-hook.md) |
| Input | `click` (`tap`), `tap_label`, `swipe`, `text`, `key`, `back`, `home`, `enter` | [Control](control.md) |
| Screenshots and locating | `screenshot`, `Screenshot.ocr`, `locate_text`, `locate_icon`, `ImageMatch.click`, `long_press`, `swipe` | [Screenshots](screenshot.md), [Text matching](text-matching.md), [Icon matching](icon-matching.md) |
| UI trees and widgets | `dump_ui`, `uidump`, `parse_uidump`, `widgets`, `widget`, `format_tree`, `find`, `find_all`, `match`, `walk`, `to_dict`, `Widget.click`, `WidgetList.clickable`, `WidgetList.choice` | [UI dump](uidump.md), [WebView DevTools](webview-devtools.md) |
| Typed decisions | `choice`, `noul`, `score` | [Models](models.md) |
| Goal APIs | `agent`, `Agent.ask_sysone`, `Agent.run`, `Agent.debug`, `llm`, `sysone_goal`, `sysone`, `SysOneGoal.run` | [Models](models.md) |

The package also exports `Device`, `Agent`, `AgentRun`, `AgentPlan`, `AgentStep`,
`AgentDebugSession`, `AgentDebugState`, `AgentDebugStep`, `SysOneGoal`,
`SysOneGoalCandidate`, `SysOneAnswer`, `SysOneCriteria`,
`SysOneDecisionProvider`, `SysOneProvider`, `SysOneQuestion`, `SysOneResponse`,
`LlmToolCall`, `ImageMatch`, `ActivityInfo`, `UiDocument`, `UiNode`, `Widget`,
and `WidgetList`. Result objects are normally returned by the methods below;
you do not need to construct them yourself. Backend and transport integrations
can use `DeviceSession`, backend classes, and protocol dataclasses; see the
[backend guide](backend.md).

## Connect, inspect, and close

`connect()` uses local ADB defaults. You can pass a config path or an existing
`AppConfig`; `serial=`, `remote=`, `adb_server=`, `adb_path=`, `retries=`,
`output_dir=`, and `timeout=` are optional overrides. `serial` and `remote`
cannot be used together. See [remote ADB](remote-adb.md) for remote setup.

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    if not phone.health():
        raise RuntimeError("device is not ready")

    caps = phone.capabilities()
    print(f"Screen: {caps.screen_width} × {caps.screen_height}")
    print(f"Foreground Activity: {phone.current_activity()}")
    print(f"Installed packages: {len(phone.list_apps())}")
    phone.save_run("inspection.json")
```

The context manager calls `close()` when the block ends. For manual lifecycle
management, call `close()` in a `finally` block:

```python
from nier import connect


phone = connect("config/nier.yaml")
try:
    print(phone.health())
finally:
    phone.close()
```

## Inspect and launch apps

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    packages = phone.list_apps()
    activities = phone.list_app_activities("com.example.authorized.app")
    print(packages[:5], activities)

    phone.open_app("com.example.authorized.app")
    phone.start_activity("com.example.authorized.app", ".SettingsActivity")
```

`list_app()` and `list_app_activity(package)` are compatibility aliases for
`list_apps()` and `list_app_activities(package)`. `launch_app()` aliases
`open_app()`; `open_activity()` aliases `start_activity()`. Set
`restart=True` on `open_app()` to stop the process and clear its Activity task
before relaunching it; this preserves app data. For an Intent printed by
`nier intent-hook`, pass the mapping to `phone.start_intent(intent)`; see the
[apps guide](apps.md) for a complete Intent example and root-mode details.

## Send input

Coordinates are screen pixels unless `normalized=True`, in which case each
coordinate is between `0` and `1`. A string passed to `tap_label()` matches
exactly; a compiled regular expression uses search semantics against UI text
and content descriptions.

```python
import re

from nier import connect


with connect("config/nier.yaml") as phone:
    phone.click(540, 960)
    phone.tap(0.5, 0.5, normalized=True)
    phone.tap_label(re.compile(r"^搜索.*$"))
    phone.swipe((0.25, 0.75), (0.25, 0.25), normalized=True)
    phone.text("search phrase")
    phone.enter()
    phone.key("volume_down")
    phone.back()
    phone.home()
```

`click()` is the canonical name for `tap()`. `swipe()` accepts `(x, y)` pairs
or flat coordinate numbers. See [control](control.md) for durations, bounds,
and optional Unicode IME input.

## Capture screenshots and locate content

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    screenshot = phone.screenshot(
        "artifacts/screen.jpg",
        format="jpeg",
        quality=85,
        max_width=1280,
    )
    print(screenshot.width, screenshot.height, screenshot.sha256)

    # OCR uses the configured OCR provider and requires its optional setup.
    spans = screenshot.ocr()
    print([(span.text, span.box) for span in spans])

    # Locate text in a new screenshot. Matching is read-only until you act.
    match = phone.locate_text("Continue", min_score=0.7)
    if match is not None:
        print(match.bounds, match.center, match.score)
        # This is a device action. Run it only for an authorized task.
        match.click(humanize=False)
```

`phone.locate_icon("artifacts/icon.png")` searches a fresh screenshot for an
image template and returns an `ImageMatch` or `None`. Install the optional
`vision` extra for icon matching. A device-bound match also supports
`long_press()` and `swipe("up")`:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    match = phone.locate_icon("artifacts/icon.png", min_score=0.9)
    if match is not None:
        print(match.bounds, match.score)
        # Choose the gesture required by the authorized task.
        match.long_press()
        # Alternatively, start a swipe from this match:
        # match.swipe("up")
```

See the [text](text-matching.md) and [icon](icon-matching.md) guides for
thresholds, bounds, and further examples.

## Read and query UI trees

`dump_ui()` returns the raw dump and source metadata. `uidump()` returns its
XML/HTML text and can save it. `parse_uidump()` captures a fresh dump when
called on `phone` without an argument; the package-level `parse_uidump()` can
parse a raw string, `Path`, or `UiDump` offline.

```python
from pathlib import Path

from nier import connect, parse_uidump


with connect("config/nier.yaml") as phone:
    dump = phone.dump_ui(prefer_webview=False)
    xml = phone.uidump("artifacts/ui.xml", prefer_webview=False)
    document = phone.parse_uidump(dump)

    # Find by Android class, text, resource ID, content description, or flags.
    node = document.find(class_name="android.webkit.WebView")
    if node is not None:
        print(node.text, node.attributes, node.bounds, node.center)

    buttons = document.find_all(
        class_name="android.widget.Button",
        clickable=True,
        visible=True,
    )
    print(phone.format_tree(document, color=False))

    # UiNode -> Widget binds the node to this device for a checked click.
    if buttons and buttons[0].center is not None:
        button = phone.widget(buttons[0])
        print(button.label, button.bounds)
        # button.click() sends one tap.

    # WidgetList is iterable and supports indexing, slicing, and filters.
    choices = phone.widgets(document).clickable()
    if choices:
        selected = choices.choice("Open the account settings")
        print(selected.label)
        # selected.click() sends one tap after you inspect the selection.

# Parsing saved output does not contact the device.
saved = parse_uidump(Path("artifacts/ui.xml"))
print(saved.find(text_contains="Continue"))
```

`find()` returns the first node or `None`; `find_all()` returns all matching
nodes in document order. UI nodes expose `children`, `walk()`, `attr()`,
`to_dict()`, text and attribute properties, and parsed screen bounds when
available. To bind a node from the current device dump to a safe click helper,
use `phone.widget(node)`. For a chain of candidates, use
`phone.widgets(document).clickable()`; its `choice(instruction)` uses the
configured TypeSafe provider to select a visible clickable widget. A widget's
`click()` checks that it is clickable, not explicitly hidden, and has usable
bounds. See the [UI dump guide](uidump.md) for complete examples.

## Ask typed questions or run a goal

`choice()`, `noul()`, and `score()` use the configured TypeSafe provider and
return a `SysOneAnswer`:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    route = phone.choice(
        {"instruction": "find account settings"},
        ["account", "notifications", "help"],
        instructions="Which option best matches the instruction?",
    )
    urgent = phone.noul(
        {"message": "The payment failed twice"},
        instructions="Does this need immediate attention?",
    )
    severity = phone.score(
        {"message": "The payment failed twice"},
        ["low", "medium", "high"],
        instructions="Rate the severity",
    )
    print(route.choice, urgent.noul, severity.score)
```

For an LLM-first flow, `llm()` plans through validated tools and re-observes
after each action. `dry_run=True` previews the next action:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    preview = phone.llm("Open Settings and show About phone", dry_run=True)
    print(preview.plan.goal, preview.plan.steps)
```

`agent()` creates an `Agent` for repeated runs or manual, one-step debugging.
Each call to `debug.step()` may execute at most one validated device action;
inspect its state before requesting another step:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    debug = phone.agent().debug("Open Settings and show About phone")
    step = debug.step()
    print(step.status, step.state.activity)
    if not step.finished:
        next_step = debug.step()
        print(next_step.status)
```

For a single bounded model-assisted run, `Agent.run()` has the same
`dry_run=True` preview option. `Agent.ask_sysone()` makes a typed SysOne call
from an Agent; its question construction is shown in the
[models guide](models.md).

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    agent = phone.agent()
    preview = agent.run("Open Settings", dry_run=True)
    print(preview.plan.goal, preview.plan.steps)
```

`sysone()` runs a SysOne-first goal from finite, host-validated UI/OCR
candidates. `sysone_goal()` creates the runner when its configuration should be
reused or inspected:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    preview = phone.sysone(
        "Open Settings and show About phone",
        allowed_controls=("About phone", "Back"),
        prefer_webview=False,
        dry_run=True,
    )
    print(preview.termination, preview.plan.steps)

    runner = phone.sysone_goal(max_steps=6, prefer_webview=False)
    next_preview = runner.run(
        "Open Settings and show About phone",
        dry_run=True,
    )
    print(next_preview.termination, next_preview.plan.steps)
```

OCR, LLM, and SysOne provider settings are optional and loaded lazily. See
[models](models.md) for provider configuration, error behavior, typed questions,
debugging, goal limits, and execution controls. A completion decision from
SysOne requires independent verification.

## Errors, optional dependencies, and lower-level APIs

Expected runtime failures use `NierError` subclasses. Device/backend failures
are reported as `BackendError` or a more specific backend error; provider
failures use `ModelError`. Catch only the errors your script can handle, and
keep provider credentials in environment variables. OCR, LLM, SysOne, and
OpenCV-based icon matching each require their respective optional provider or
dependency setup.

The methods above are the recommended script API. `DeviceSession`, backend
implementations, action/request dataclasses, model provider interfaces, and
transport protocol types are lower-level extension APIs. See
[backend](backend.md), [models](models.md), and [remote ADB](remote-adb.md)
before using those directly.
