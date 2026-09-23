# Nier

Nier is an extensible Android automated-testing framework. It provides a
Python runtime for ADB-based device control, screenshots, UI dumps, optional
rooted `uinput` input, model providers, and replaceable backend transports.

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

Natural-language operation flows are available through `phone.run(...)`. When
Jev is configured, Jev is the primary decision-maker and selects only from
host-validated UI/OCR candidates; it can ask an optional LLM for high-level
direction when stuck, while Jev remains responsible for choosing actions. When
Jev is not configured, `phone.run(...)` keeps the LLM Agent flow. Use
`phone.agent().run(...)` explicitly for LLM-first tool planning, and
`dry_run=True` to preview the next validated action. See the
[model and Agent guide](docs/models.md).

Typed TypeSafe Jev decisions are available through `phone.jev()` for bounded
choice, score, and noul questions. The client is created from configuration on
first use and reused for the connection; keep `TYPESAFE_API_KEY` in the
environment (`JEV_API_KEY` is accepted as a compatibility alias). See the
[model guide](docs/models.md) for configuration and examples.

For goals where Jev should select only from host-generated UI/OCR actions,
`phone.run(...)` uses Noul for completion and Choice for the next candidate,
requests OCR only when Jev chooses `inspect_ocr`, and rechecks the device state
before acting. Jev receives semantic UI/OCR labels; the host keeps coordinates
and executes validated actions. `phone.run_jev_goal(...)` remains as a
compatibility wrapper for this flow.
`allowed_controls` and `denied_controls` can restrict visible labels, while
`allowed_apps={"设置": "com.android.settings"}` can explicitly allow app
launch candidates. Jev sees the app label, while the package stays host-side.
`max_steps` bounds main-goal actions. For Jev-first goals, `max_seconds` adds an
optional overall deadline and is disabled by default. A completion signal
returns `needs_verification` for caller review. If Jev selects `call_llm`, the
LLM generates a bounded recovery subgoal (up to two assists by default); a nested
Jev run carries it out using only safe, host-validated dismiss/back/home
controls, then the main goal observes again and resumes. If a recovery subgoal
fails, the LLM may generate a replacement from the updated UI state. The LLM
cannot choose or execute actions directly. Use `phone.agent().run(...)` when
the goal needs free-form text or LLM-generated actions.

`connect(remote="192.168.1.20:5555")` connects to an authorized device over
ADB TCP. See the [feature-oriented API documentation](docs/README.md) and
[examples](examples/README.md) for more operations.

Logging is quiet by default. Add a `logging.verbosity` value of `1`, `2`, or
`3` (also accepted as `v`, `vv`, or `vvv`) to the YAML configuration. The CLI
also accepts `-v`, `-vv`, and `-vvv`; these increase the configured verbosity
for that command. `v` shows steps. `vv` adds OCR, UI dump, Jev, and LLM results.
`vvv` adds bounded, sanitized ADB and HTTP request/response details.
Jev answers are shown by question and type; `vvv` renders their UI summaries
and OCR spans as readable lines.
Terminal logs and CLI summaries use labeled text rather than JSON output;
machine-readable run records remain saved as JSON files.

Verbose terminal logs include a local `HH:MM:SS.mmm` timestamp. Steps and OCR
results are cyan, tool calls and LLM results magenta, UI dumps yellow, Jev
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

## Disclaimer

Nier is experimental software provided for authorized testing and research.
Use it only on devices, applications, and data you own or are permitted to
test. Device automation, root access, model-provider calls, and generated
actions may cause data loss, unintended changes, service costs, or other harm.
You are responsible for reviewing actions, protecting credentials, complying
with applicable laws and service terms, and accepting all risks before use.

## License

Released under the [MIT License](LICENSE).
