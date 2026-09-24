# Nier

Nier is an extensible Android automated-testing framework. It provides a
Python runtime for ADB-based device control, screenshots, UI dumps, optional
OpenCV icon matching, rooted `uinput` input, model providers, and replaceable
backend transports.

## Quick start

Requires Python 3.10 or newer. To set up the development environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

For a connected Android device, copy `config/nier.example.yaml` to
`config/nier.yaml`, adjust the device settings, and run:

```bash
nier health
nier capabilities
```

Or use the script-friendly Python API:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    phone.tap(0.5, 0.5, normalized=True)
    phone.text("hello")
    apps = phone.list_apps()
    print(f"Installed apps: {len(apps)}")
    activities = phone.list_app_activities("com.android.settings")
    print(f"Settings activities: {len(activities)}")
    phone.open_app("com.android.settings")
    phone.start_activity("com.android.settings", ".Settings")
    screenshot = phone.screenshot("artifacts/screen.png")
    spans = screenshot.ocr()
    xml = phone.uidump("artifacts/ui.xml")
```

`screenshot().ocr()` uses the first OCR provider from the loaded configuration.
The provider is created lazily and cached for the duration of the connection;
scripts do not need to instantiate an OCR provider.

Natural-language operation flows are available through `phone.llm(...)`. It
uses the configured LLM as the planner: it observes the current screenshot and
UI, then selects one validated tool action per step. Pass `sysone=` or
`sysone_provider=` when you want SysOne to supply advisory context. Use
`phone.sysone(...)` to explicitly request TypeSafe SysOne selection from
host-validated UI/OCR candidates. The two entry points are separate; `llm()`
does not fall back to SysOne. When an OCR provider is configured, the LLM can
request OCR with the read-only `inspect_ocr` tool; OCR does not run automatically.
Use `dry_run=True` to preview the next validated tool call. See the
[model and Agent guide](docs/models.md).

Typed decisions from the TypeSafe SysOne provider are available through
`phone.choice(...)`, `phone.noul(...)`, and `phone.score(...)`. To choose and tap
a UI control from a dump, use
`phone.widgets().clickable().choice("进入设置").click()`; the `clickable()`
filter is optional because `choice()` filters unsafe candidates itself.
`widgets()` prefers UIAutomator to retain screen bounds. The
provider is configured under `models.sysone` with `provider: typesafe`, created
on first use, and reused for the connection. The default credential variable is
`SYS_ONE_API_KEY`; `TYPESAFE_API_KEY` is also recognized. See the
[model guide](docs/models.md) and [UI dump guide](docs/uidump.md) for details.

For goals where SysOne should select only from host-generated UI/OCR actions,
`phone.sysone(...)` uses Noul for completion and Choice for the next candidate,
requests OCR only when SysOne chooses `inspect_ocr`, and rechecks the device state
before acting. SysOne receives semantic UI/OCR labels; the host keeps coordinates
and executes validated actions. `phone.sysone(...)` is the explicit
entry point for this flow.
`allowed_controls` and `denied_controls` can restrict visible labels, while
`allowed_apps={"设置": "com.android.settings"}` can explicitly allow app
launch candidates. SysOne sees the app label, while the package stays host-side.
`max_steps` bounds main-goal actions. For SysOne-first goals, `max_seconds` adds an
optional overall deadline and is disabled by default. A completion signal
returns `needs_verification` for caller review. If SysOne selects `call_llm`, the
LLM generates a bounded recovery subgoal (with no assist-count limit by
default), then executes it by selecting only safe, host-validated
dismiss/back/home controls; the main goal observes again and resumes. It cannot
provide coordinates or arbitrary operations. Set
`max_llm_assists` to a non-negative integer to cap generation, or to zero to
disable LLM recovery. If a recovery subgoal fails, the LLM may generate a
replacement from the updated UI state. Use `phone.agent().run(...)` to customize
the LLM Agent directly.

`connect(remote="192.168.1.20:5555")` connects to an authorized device over
ADB TCP. See the [feature-oriented API documentation](docs/README.md) and
[examples](examples/README.md) for more operations.

Logging is quiet by default. Add a `logging.verbosity` value of `1`, `2`, or
`3` (also accepted as `v`, `vv`, or `vvv`) to the YAML configuration. The CLI
also accepts `-v`, `-vv`, and `-vvv`; these increase the configured verbosity
for that command. `v` shows steps. `vv` adds OCR, UI dump, SysOne, and LLM results.
`vvv` adds bounded, sanitized ADB and HTTP request/response details.
SysOne answers are shown by question and type; `vvv` renders their UI summaries
and OCR spans as readable lines.
Nier terminal logs are written to stdout, and logs and CLI summaries use labeled
text rather than JSON output; machine-readable run records remain saved as JSON
files.

Verbose terminal logs include a local `HH:MM:SS.mmm` timestamp. Steps and OCR
results are cyan, tool calls and LLM results magenta, UI dumps yellow, SysOne
results green, requests blue, and responses green. Colors are omitted when
output is redirected or `NO_COLOR` is set.

The default backend communicates directly through ADB. Root access and the
optional `backend/nier-uinput` helper enable virtual touch input; otherwise the
runtime falls back to Android's shell input commands. Optional Android
integrations are documented in `backend/`.

`InputText` uses shell input by default. The optional Android module also
provides an IME text backend for Unicode/Chinese input; enable it with
`input_text.mode: ime` in the configuration.

Optional WebView instrumentation is documented in
[`backend/nier-frida`](backend/nier-frida). Root mode uses Frida injection;
non-root mode requires the target app to call the cooperative
`WebViewDebugController` before creating a WebView. When `hook.target_package`
is configured, `dump-ui` uses the WebView DevTools DOM through a temporary
host-local ADB forward and falls back to UIAutomator if the target is not
available. Root mode also supports the opt-in `hook.force_system_back` policy
for bypassing common application-owned Back callbacks on authorized targets.

Remote ADB over TCP is supported through `device.remote_host` and
`device.remote_port`; see the [remote ADB guide](docs/remote-adb.md).

See the [WebView DevTools guide](docs/webview-devtools.md) for hybrid apps.

## Local execution dashboard

Run Python scripts from a local browser dashboard to see the live execution
path and inspect STEP, request, and response details:

```bash
nier web --scripts=./examples
```

The dashboard binds to `127.0.0.1` by default. Select a script and confirm
each run in the browser. It streams bounded, sanitized Nier log events. See the
[web dashboard guide](docs/web-dashboard.md) for setup, live logs, and the
optional STEP-level debugger controls.

## Disclaimer

Nier is experimental software provided for authorized testing and research.
Use it only on devices, applications, and data you own or are permitted to
test. Device automation, root access, model-provider calls, and generated
actions may cause data loss, unintended changes, service costs, or other harm.
You are responsible for reviewing actions, protecting credentials, complying
with applicable laws and service terms, and accepting all risks before use.

## License

Released under the [MIT License](LICENSE).
