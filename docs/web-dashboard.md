# Local execution dashboard

The local dashboard runs a Python script from a browser and streams its actual
execution steps into a path graph. Select a graph node to see its STEP fields
and any request/response entries associated with that step.

## Start the dashboard

Install Nier, then point the web command at a directory containing Python
scripts:

```bash
python -m pip install -e .
nier web --scripts=./examples
```

The command serves the bundled React and shadcn/ui interface through FastAPI
and Uvicorn at `http://127.0.0.1:8765`, then opens the browser. Use
`--no-browser` to print the address without opening it. The script directory is
scanned recursively for `.py` files. Press Ctrl+C in the serving terminal to
stop the dashboard; active live-log and screen-preview streams are closed as
part of shutdown.

The dashboard has a separate **UI Inspector** tab. Select an authorized ADB
device and choose **执行 uidump** to capture a screenshot and UI hierarchy using
the same device configuration as the CLI (`--config`, defaulting to
`config/nier.yaml`). The capture is read-only and held in memory; it does not
write screenshot or dump files. UIAutomator bounds are drawn over the screenshot:
hovering a box scrolls to and highlights its tree node, and hovering a tree node
highlights its screenshot bounds. The panel also exposes the human-readable CLI
tree and raw XML/HTML. **WebView** prefers DevTools DOM extraction; uncheck it to
request UIAutomator directly when you need Android view bounds. When the host
can map WebView DOM geometry to the native WebView viewport, the Inspector
draws the mapped `data-nier-screen-bounds` over the device screenshot and uses
the mapped clickability/visibility metadata when generating code. Unmapped DOM
nodes remain searchable in the tree but have no screenshot overlay or click.

Click a bounds rectangle or a tree row to select a component. The inspector then
generates a copyable Nier snippet that re-finds the selected node by its visible
text and available IDs/attributes. It includes `component.click()` only when the
dump marks the selected node clickable and provides usable screen bounds;
otherwise the generated snippet locates and prints the node without sending an
action. The snippet checks that the selector matches exactly one node before
using it, so ambiguous matches fail visibly instead of tapping an arbitrary
component.

The CLI config can be selected when starting the dashboard:

```bash
nier --config config/nier.yaml web --scripts=./examples
```

Screenshot and UI-dump reads use `DeviceSession`'s read retry policy. They are
separate sequential reads, so an app that changes itself during capture may
produce a slightly mismatched screenshot and hierarchy. The inspector does not
send clicks or other device actions; only inspect devices and apps you are
authorized to test.

The standalone **屏幕预览** panel can mirror an authorized ADB device through
scrcpy. On wide screens it sits beside the execution graph and **执行日志**;
on narrower screens it moves below them. Install `scrcpy`, `ffmpeg`, and Android
platform-tools (`adb`) on the host and make them available in `PATH`. Select a
device reported as `device`, then start the preview. The dashboard disables
scrcpy control and audio; the stream is view-only and stops when you stop it or
shut down the dashboard. The preview uses ADB's temporary local socket
forwarding and does not open a device network listener. It reads scrcpy's H.264
stream directly and converts frames to MJPEG locally; FIFO support is not
required. Click inside the displayed device frame to copy a ready-to-use
`phone.click(x, y)` call with absolute screen-pixel coordinates. Clicks in the
black letterbox area are ignored. Coordinates are scaled to the device's full
input resolution even when scrcpy downsizes the preview, and account for
portrait/landscape orientation. This only copies coordinates; it does not send
input to the device.

The interface lists each script using its module docstring. Press **运行脚本**
and confirm the prompt to start it. A script runs with the same Python
interpreter and working directory as `nier web`. **停止运行** sends a process
termination request.

The **源码** panel displays the selected or currently running Python file. As
the runner reports execution locations, the panel switches to that file,
syntax-highlights Python code, highlights the active line, and scrolls it into
view. On narrow screens, use the **源码** tab to open the panel; on wide screens
it appears alongside the graph, logs, and screen preview. Source is fetched on
demand only from Python files listed under the selected scripts directory. It
is not included in location events, and local variable values are never shown.

Choose **调试运行** to pause at the first Nier `STEP` event. The sidebar then
provides **继续**, **步入**, **单步**, and **步出** controls, plus the current
STEP details and call path. **单步** runs through exactly one STEP event and
pauses at the next one. **步入** waits for a STEP event at a deeper call level;
**步出** waits for one at a shallower level. These controls follow Nier STEP
events rather than Python source lines. Normal runs remain uninterrupted and
also stream the current script-relative Python file, line, and function to the
source panel. The runner samples location updates at up to 20 per second; it
does not send source text or local variable values in those events.

To rebuild the frontend from a source checkout:

```bash
cd web
npm ci
npm run build
```

The build writes static assets into `src/nier/web_static`, which are included
with the Python package.

## Execution trace and logs

The graph shows STEP events and model results in the order they occur. A
successful `read` result is attached to its read node instead of creating a
separate completion node. Nodes stay compact and show an indicator when response
data is available. The sidebar's separate **响应预览** panel follows the selected
node and shows its bounded response; the log list shows related requests and
responses alongside STEP details and recent script output.
`dump_ui` results appear as an expandable UI hierarchy with element attributes,
text, resource IDs, and bounds. Use **全屏预览** to inspect the tree across the
full viewport; the tree remains independently scrollable and expandable.

Debug events also travel over the dashboard event stream. The runner pauses
inside the STEP logger before execution continues past that event, then waits
for the selected control command. Stopping the run terminates the paused
process. STEP details retain structured-event redaction. Call paths show
script-relative paths or library file names, line numbers, and function names;
they omit source text and local variable values.

The current execution location is tracked only for Python files inside the
selected scripts directory. Line tracing runs in the dashboard child process
and may add execution overhead for heavily Python-bound scripts; dashboard UI
updates are sampled to keep the event stream compact. Source reads use a
separate same-origin endpoint restricted to available `.py` files under that
directory; responses are not cached.

The dashboard enables the existing `vvv` request/response logging level in the
child script and streams structured Nier events after applying the existing
secret redaction and payload limits. API keys, authorization headers, cookies,
passwords, and token fields are redacted. Text included in a request body may
still be visible. The human-readable stdout copies of Nier log events are
filtered from console output to avoid duplicates. Ordinary script stdout and
stderr are displayed as written by the script and are not sanitized, so use the
local dashboard only with scripts and data you are authorized to inspect.

## Device access and failures

The dashboard binds to `127.0.0.1` by default. While preview is active, scrcpy
runs a temporary capture process reached through ADB's temporary local socket
forward; the dashboard does not expose a device-side network listener or change
Nier's ADB-first device topology. Running a script can perform the same device
actions, provider calls, and filesystem writes as launching it from a terminal.
Only run scripts you trust and have permission to execute.

Device access still uses the configuration loaded by the script. Connect only
to an authorized device, and install optional model dependencies and configure
provider credentials when the selected script needs them. Missing configuration,
an unavailable device, or a provider error is shown as a failed script run; the
dashboard does not retry the script or device actions automatically. The
existing `DeviceSession` read retry policy remains in effect, while taps, text
input, key events, and app launches are never automatically retried.
