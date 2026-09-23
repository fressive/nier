# Nier examples

Run these scripts from the repository root after installing the package:

```bash
python -m pip install -e '.[dev]'
```

To browse and run them with a live execution trace, start:

```bash
nier web --scripts=./examples
```

The dashboard requires an explicit confirmation for each script run. Scripts
execute with the current user's permissions and may access an authorized device;
see the [web dashboard guide](../docs/web-dashboard.md).

| Example | Purpose | Device required |
| --- | --- | --- |
| [`01_basic_session.py`](01_basic_session.py) | Connect, health-check, inspect capabilities, and record a run | Yes |
| [`02_control_device.py`](02_control_device.py) | Find a visible label and submit a search flow | Yes |
| [`03_screenshot_uidump.py`](03_screenshot_uidump.py) | Capture evidence, save a structured UI tree, and inspect clickable nodes | Yes |
| [`04_agent.py`](04_agent.py) | Preview or execute an LLM-driven UI goal with validated tool calls | Yes; requires an LLM provider; `--execute` opts into actions |
| [`05_remote_ocr.py`](05_remote_ocr.py) | Use the configured OCR provider to recognize and tap a label | Yes; API provider required |
| [`06_jev_goal.py`](06_jev_goal.py) | Preview or run `phone.run_jev_goal()` with Jev-first candidate selection and bounded LLM recovery subgoals | Yes; requires configured Jev; actions require explicit opt-in |
| [`07_webview_uidump.py`](07_webview_uidump.py) | Print and save a readable node tree plus the raw dump, preferring WebView DOM extraction | Yes; requires a configured WebView target |

Copy the configuration before running device examples:

```bash
cp config/nier.example.yaml config/nier.yaml
PYTHONPATH=src python examples/01_basic_session.py
PYTHONPATH=src python examples/02_control_device.py --confirm
PYTHONPATH=src python examples/03_screenshot_uidump.py
PYTHONPATH=src python examples/04_agent.py
PYTHONPATH=src python examples/04_agent.py --execute
PYTHONPATH=src python examples/05_remote_ocr.py
PYTHONPATH=src python examples/06_jev_goal.py
PYTHONPATH=src python examples/06_jev_goal.py --execute
PYTHONPATH=src python examples/06_jev_goal.py --execute --allow-control 设置 --allow-control 向下滚动当前列表 --allow-control 关于本机
PYTHONPATH=src python examples/06_jev_goal.py --yolo
PYTHONPATH=src python examples/07_webview_uidump.py
```

Only run device-control examples against devices and applications you are
authorized to test. `02_control_device.py` requires `--confirm` because it taps
a label and submits text. `06_jev_goal.py` previews by default; `--execute`
explicitly enables host-validated Jev actions. It can tap visible controls
and scroll bounded lists, but cannot invent an app package. Add
`--allow-control` for every UI or scroll label you want to permit when
narrowing candidate choices. When an LLM provider is configured, Jev may
request recovery through `call_llm` or after a failure. The LLM creates a bounded
subgoal and executes it by selecting from host-validated safe controls; it
cannot invent coordinates or arbitrary device actions. After success the main
goal observes the device again and resumes. Failed subgoals may be replaced
using a fresh observation. Assist generation is unlimited by default; pass
`max_llm_assists` to cap it. Jev still chooses every main-goal action in this
explicit Jev-first example.
The example caps the main goal at eight actions but uses the runtime's default
unlimited wall-clock deadline. A Jev completion signal is reported as requiring
verification, not as a confirmed pass.
`--allow-control` limits UI, scroll, and system candidates to the exact labels
you pass. `--yolo` is an alias for `--execute`. Jev still
selects among host-validated candidates and the same confidence and execution
bounds apply. App launches remain unavailable without an explicit allowlist.
Model credentials stay in environment variables.

`04_agent.py` also previews by default; pass `--execute` to let the LLM Agent
perform validated actions on the connected device.

Edit the constants at the top of each script for the target package, labels,
remote endpoint, or whether an Agent plan should be executed. The examples
use the concise `from nier import connect` API. OCR examples call
`phone.screenshot().ocr()`; the first provider is loaded from
`models.ocr_providers` (or the singular `models.ocr` section).
