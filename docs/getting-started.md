# Getting started

## Install and configure

Nier requires Python 3.10 or newer:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp config/nier.example.yaml config/nier.yaml
```

Adjust `config/nier.yaml` for an authorized Android device. Keep model API keys
in environment variables; do not put them in tracked YAML files.

## Connect and automate

`connect` creates the ADB backend, session, retry policy, and recorder for you:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    print(phone.health())
    print(phone.capabilities())
    print(phone.list_apps())
    print(phone.list_app_activities("com.android.settings"))
    phone.open_app("com.android.settings")
    phone.start_activity("com.android.settings", ".Settings")
    phone.tap(0.5, 0.5, normalized=True)
    phone.text("hello")
    phone.screenshot("artifacts/screen.png")
    xml = phone.uidump("artifacts/ui.xml")
```

The context manager closes persistent input processes and transport channels.
Read operations may retry transient backend failures; device actions, including
app and Activity launches, are never retried automatically.

Configuration is optional. Common one-line targets are:

```python
usb = connect()                           # the only local ADB device
chosen = connect(serial="emulator-5554")
remote = connect(remote="192.168.1.20:5555")
```

Call `close()` when not using `with`. Use `save_run()` to write the recorded
operations to the configured artifact directory:

```python
phone = connect()
try:
    print(phone.health())
    phone.save_run()
finally:
    phone.close()
```

## Logging

Logging is disabled by default. Configure the verbosity in YAML or use the
CLI flags:

```yaml
logging:
  verbosity: v  # also accepts vv/vvv; 1/2/3 are equivalent
```

```bash
nier -v health
nier -vv capabilities
nier -vvv screenshot
```

Request and response payloads are bounded and sensitive headers such as
Authorization and API keys are redacted in `vvv` transport logs. At `vv`, OCR,
UI dump, Jev, and LLM results are logged with the same payload size limits.
Screenshot data sent to OCR is shown as a size marker rather than a Base64
payload.
Jev answers are shown by question and type; at `vvv`, Jev context logs render UI
summaries and OCR spans as readable lines.

Verbose terminal logs include local timestamps. Steps and OCR results are cyan,
tool calls and LLM results magenta, UI dumps yellow, Jev results green, requests
blue, and responses green. Colors are omitted when output is redirected or
`NO_COLOR` is set.

`DeviceSession`, `AdbBackend`, and the dataclasses in `nier.protocol` remain
available for custom backends and transport-level integrations. Ordinary
scripts do not need to construct `Click`, `ScreenshotRequest`, or
`DumpUiRequest` objects.

For package and Activity inspection, see the [applications guide](apps.md).

## CLI

After copying the example configuration, the basic commands are:

```bash
nier --config config/nier.yaml health
nier --config config/nier.yaml capabilities
nier --config config/nier.yaml screenshot
nier --config config/nier.yaml dump-ui
```

Artifacts are written to `runtime.output_dir` (default: `artifacts`).

## Errors and authorization

Expected failures use typed errors:

```python
from nier import connect
from nier.errors import BackendError, ConfigurationError


try:
    with connect("config/nier.yaml") as phone:
        phone.screenshot("artifacts/screen.png")
except BackendError as exc:
    print(f"device operation failed: {exc}")
except ConfigurationError as exc:
    print(f"configuration failed: {exc}")
```

Use Nier only on devices and applications that you are authorized to test.
Review generated actions, protect model credentials, and account for data
changes and external provider costs.
