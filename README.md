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
    print(phone.list_apps())
    print(phone.list_app_activities("com.android.settings"))
    phone.open_app("com.android.settings")
    phone.start_activity("com.android.settings", ".Settings")
    screenshot = phone.screenshot("artifacts/screen.png")
    spans = screenshot.ocr()
    xml = phone.uidump("artifacts/ui.xml")
```

`screenshot().ocr()` uses the first OCR provider from the loaded configuration.
The provider is created lazily and cached for the duration of the connection;
scripts do not need to instantiate an OCR provider.

Natural-language operation flows are available through `phone.run(...)`; its
native tools include package/Activity inspection and app/Activity launches. Use
`dry_run=True` to review the validated model plan before executing it. See the
[model and Agent guide](docs/models.md). The Agent passes a bounded,
structured UI tree and foreground Activity to both the LLM prompt and optional
Jev decision context and re-observes the device after every action.

Typed TypeSafe Jev decisions are available through `phone.jev()` for bounded
choice, score, and noul questions. The client is created from configuration on
first use and reused for the connection; keep `TYPESAFE_API_KEY` in the
environment (`JEV_API_KEY` is accepted as a compatibility alias). See the
[model guide](docs/models.md) for configuration and examples.

For goals where Jev should select only from host-generated UI/OCR actions, use
`phone.run_jev_goal(...)`. It uses Noul for completion, Choice for the next
candidate, and rechecks the device state before acting. Jev receives semantic
UI/OCR labels; the host keeps coordinates and executes validated actions.
`allowed_controls` and `denied_controls` can restrict visible labels, while
`max_steps` and `max_seconds` bound the loop. A completion signal returns
`needs_verification` for caller review. Use `phone.run(...)` when the goal needs
free-form text or LLM-generated actions.

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
