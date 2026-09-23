# Nier examples

Run these scripts from the repository root after installing the package:

```bash
python -m pip install -e '.[dev]'
```

| Example | Purpose | Device required |
| --- | --- | --- |
| [`01_basic_session.py`](01_basic_session.py) | Connect, health-check, inspect capabilities, and record a run | Yes |
| [`02_control_device.py`](02_control_device.py) | Find a visible label and submit a search flow | Yes |
| [`03_screenshot_uidump.py`](03_screenshot_uidump.py) | Capture evidence, save a structured UI tree, and inspect clickable nodes | Yes |
| [`04_remote_adb.py`](04_remote_adb.py) | Run a session against a remote ADB device | Yes; TCP ADB |
| [`05_model_decision.py`](05_model_decision.py) | OCR a screen and tap a matching label | Yes; configured OCR provider |
| [`07_agent.py`](07_agent.py) | Run a UI goal with an LLM and Jev | Yes; requires configured models |
| [`08_jev.py`](08_jev.py) | Ask a typed TypeSafe Jev decision | No device action; requires `TYPESAFE_API_KEY` |
| [`09_remote_ocr.py`](09_remote_ocr.py) | Use the configured OCR provider to recognize and tap a label | Yes; API provider required |
| [`10_jev_goal.py`](10_jev_goal.py) | Preview or run a bounded UI goal with Jev candidate selection | Yes; requires configured Jev; the Settings app is allowlisted, and UI actions require explicit labels |
| [`11_webview_uidump.py`](11_webview_uidump.py) | Print and save a readable node tree plus the raw dump, preferring WebView DOM extraction | Yes; requires a configured WebView target |

Copy the configuration before running device examples:

```bash
cp config/nier.example.yaml config/nier.yaml
PYTHONPATH=src python examples/01_basic_session.py
PYTHONPATH=src python examples/03_screenshot_uidump.py
PYTHONPATH=src python examples/07_agent.py
TYPESAFE_API_KEY=... PYTHONPATH=src python examples/08_jev.py
PYTHONPATH=src python examples/09_remote_ocr.py
PYTHONPATH=src python examples/10_jev_goal.py
PYTHONPATH=src python examples/10_jev_goal.py --execute --allow-control 关于本机
PYTHONPATH=src python examples/10_jev_goal.py --yolo
PYTHONPATH=src python examples/11_webview_uidump.py
```

Only run device-control examples against devices and applications you are
authorized to test. `10_jev_goal.py` previews by default and allowlists
`com.android.settings` in its `allowed_apps` argument and limits UI targets to
`关于本机` by default. `--allow-control` replaces that label with the exact
labels you pass. `--execute` runs with the default control allowlist; `--yolo`
runs immediately and offers all discovered UI/OCR control labels. App launches
remain limited to the explicit allowlist. Model credentials stay in environment
variables.

Edit the constants at the top of each script for the target package, labels,
remote endpoint, or whether an Agent plan should be executed. The examples
use the concise `from nier import connect` API. OCR examples call
`phone.screenshot().ocr()`; the first provider is loaded from
`models.ocr_providers` (or the singular `models.ocr` section).
