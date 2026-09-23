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

To rebuild the frontend from a source checkout:

```bash
cd web
npm ci
npm run build
```

The build writes static assets into `src/nier/web_static`, which are included
with the Python package.

## Execution trace and logs

The graph shows STEP events and model results in the order they occur. It
follows the selected run as it proceeds, marks the active step, and shows the
final script exit state. The log panel contains the selected STEP details and
its associated HTTP request/response details, plus recent script output.

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
