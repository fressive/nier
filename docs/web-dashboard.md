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
scanned recursively for `.py` files.

The interface lists each script using its module docstring. Press **运行脚本**
and confirm the prompt to start it. A script runs with the same Python
interpreter and working directory as `nier web`. **停止运行** sends a process
termination request.

Choose **调试运行** to pause at the first Nier `STEP` event. The sidebar then
provides **继续**, **步入**, **单步**, and **步出** controls, plus the current
STEP details and call path. **单步** runs through exactly one STEP event and
pauses at the next one. **步入** waits for a STEP event at a deeper call level;
**步出** waits for one at a shallower level. These controls follow Nier STEP
events rather than Python source lines. Normal script runs keep their existing
uninterrupted behavior.

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
separate completion node. Nodes show a short response preview; selecting one
shows the associated response or result details in the sidebar alongside its
STEP details and recent script output.
`dump_ui` results appear as an expandable UI hierarchy with element attributes,
text, resource IDs, and bounds.

Debug events also travel over the dashboard event stream. The runner pauses
inside the STEP logger before execution continues past that event, then waits
for the selected control command. Stopping the run terminates the paused
process. STEP details retain structured-event redaction. Call paths show
script-relative paths or library file names, line numbers, and function names;
they omit source text and local variable values.

The dashboard enables the existing `vvv` request/response logging level in the
child script and streams structured Nier events after applying the existing
secret redaction and payload limits. API keys, authorization headers, cookies,
passwords, and token fields are redacted. Text included in a request body may
still be visible. Ordinary script stdout and stderr are displayed as written
by the script and are not sanitized, so use the local dashboard only with
scripts and data you are authorized to inspect.

## Device access and failures

The dashboard binds to `127.0.0.1` by default and does not start a phone-side
server or change Nier's ADB-first device topology. Running a script can perform
the same device actions, provider calls, and filesystem writes as launching it
from a terminal. Only run scripts you trust and have permission to execute.

Device access still uses the configuration loaded by the script. Connect only
to an authorized device, and install optional model dependencies and configure
provider credentials when the selected script needs them. Missing configuration,
an unavailable device, or a provider error is shown as a failed script run; the
dashboard does not retry the script or device actions automatically. The
existing `DeviceSession` read retry policy remains in effect, while taps, text
input, key events, and app launches are never automatically retried.
