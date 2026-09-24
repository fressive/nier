# Model provider API

The model layer keeps OCR, decisions, and LLM calls behind small interfaces.
OCR coordinates stay attached to recognized text so a decision provider can
return a reliable screen position.

For normal scripts, OCR is created from the connection configuration and is
available directly from a screenshot:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    spans = phone.screenshot().ocr()
    print([(span.text, span.box) for span in spans])
```

The first entry in `models.ocr_providers` is loaded lazily on the first
`ocr()` call, then reused until the connection closes. If no named mapping is
present, the singular `models.ocr` section is used. Pass a provider name only
when an explicit selection is needed; user code does not need to create an
`OcrProvider` instance.

```python
from nier.models.base import BoundingBox, TextSpan
from nier.models.decision import TextMatchDecisionProvider


spans = [
    TextSpan(
        text="Settings",
        confidence=0.98,
        box=BoundingBox(left=40, top=80, right=220, bottom=140),
    )
]
decision = TextMatchDecisionProvider().decide(spans, "open Settings")
print(decision.action, decision.point, decision.confidence)
```

The stable provider interfaces are:

- `OcrProvider.recognize(image) -> Sequence[TextSpan]`;
- `DecisionProvider.decide(text, instruction) -> Decision`;
- `LlmProvider.complete(prompt, image=None) -> str` for ordinary free-form
  completions;
- `LlmProvider.complete_with_tools(prompt, tools, image=None) ->
  Sequence[LlmToolCall]` for Agent planning.

Local PaddleOCR, the PaddleOCR hosted API, and OpenAI-compatible providers are
optional. They are loaded only when configured, and missing packages,
credentials, or remote API failures raise typed errors.

For local PaddleOCR, install both the OCR package and its CPU inference
backend. On Linux x86_64 with Python 3.13, the official CPU wheel can be
installed before the models extra:

```bash
python -m pip install paddlepaddle==3.3.0 \\
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -e '.[models]'
```

For a local PaddleOCR-compatible HTTP service, use the `paddleocr-compatible`
provider. `base_url` may be the service root or its `/docs` URL; Nier posts a
JSON data URI to `/ocr` and accepts the service's `ocrResults` response:

```yaml
models:
  ocr:
    provider: paddleocr-compatible
    base_url: http://192.168.1.151:8080
    lang: ch
```

### PaddleOCR hosted API

Use `paddleocr-api` when screenshots should be recognized by PaddleOCR's
hosted service instead of loading local inference models. The current
PaddleOCR package provides `PaddleOCRClient`, which submits a local file and
waits for the OCR job result. Configure the token through the environment:

```bash
python -m pip install -e '.[models-online]'
export PADDLEOCR_ACCESS_TOKEN="..."
```

```yaml
models:
  ocr_providers:
    cloud:
      provider: paddleocr-api
      # api_key: put-your-token-here  # prefer api_key_env for shared files
      api_key_env: PADDLEOCR_ACCESS_TOKEN
      model: PP-OCRv6
      request_timeout_seconds: 300
      poll_timeout_seconds: 600
```

Then select it from an Agent or router:

```python
with connect("config/nier.yaml") as phone:
    run = phone.llm(
        "点击登录",
        ocr_provider="cloud",
        dry_run=True,
    )
```

Set `base_url` when using a compatible proxy or hosted endpoint. It may be
either the service root (`https://paddleocr.aistudio-app.com`) or the complete
jobs endpoint (`https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`); Nier
normalizes both forms for the official client. `PP-OCRv5`/`PP-OCRv6` use the
OCR endpoint. `PaddleOCR-VL`, `PaddleOCR-VL-1.5`, and `PaddleOCR-VL-1.6` use
the SDK's document-parsing endpoint and expose layout blocks as text spans
with their bounding boxes.

The API provider writes each screenshot to a temporary file only for
submission and deletes it after the request completes. Remote OCR sends screen
content to a third party and may incur service charges; configure it only for
authorized data. For all model providers, a non-empty `api_key` value written
in the local YAML takes precedence over `api_key_env`; never commit that value
or include it in an example.

## Natural-language Agent

The public Agent API can compile a natural-language instruction into a
validated operation flow and execute it through the normal `Device` API:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    run = phone.llm(
        "打开设置，进入关于本机",
        dry_run=True,
    )
    print(f"Goal: {run.plan.goal}")
    print(f"Provider: {run.plan.provider or 'default'}")
    print("Planned actions:")
    for index, step in enumerate(run.plan.steps, start=1):
        reason = f" — {step.reason}" if step.reason else ""
        print(f"  {index}. {step.action}{reason}")
```

The Agent always executes one validated tool call, captures the new device
state, and asks the model for the next call until it returns `goal_complete` or
`goal_failed`. `dry_run=True` previews only the next action; omit it to execute
the goal loop.

For interactive debugging, use `agent.debug(goal)`. Each explicit `step()` call
makes one model request, executes at most one action, then returns the current
Activity, a bounded UI tree, screenshot metadata, and the action result. Inspect
the returned state before calling `step()` again:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    debug = phone.agent().debug("打开设置，进入关于本机")
    step = debug.step()
    print(step.to_dict())
    # Inspect the result and device state before advancing again.
    if not step.finished:
        next_step = debug.step()
        print(next_step.to_dict())
```

The returned `step.state.screenshot.data` contains the captured image bytes;
`step.to_dict()` includes only its format, dimensions, and SHA-256. Terminal
statuses include `goal_complete`, `goal_failed`, `action_failed`, `action_error`,
`planning_error`, and `max_steps`. Failed device actions are never retried.

When `provider`, `ocr_provider`, or `sysone_provider` is omitted, the first
configured entry of that provider type is selected.

The planner receives the current screenshot, foreground Activity, and parsed UI dump. In addition to
the raw dump and a compact compatibility summary, the LLM prompt contains a
bounded JSON UI tree. Each element keeps its hierarchy and may include
`bounds`, `center`, `clickable`, `visible`, source `attributes`, and nested
`children`. This gives the model stable fields to reason over instead of
requiring it to parse XML or HTML. The Agent sends native function/tool
definitions for `tap`, `swipe`, `text`, `key`, `back`, `home`, `enter`,
`list_apps`, `list_app_activities`, `open_app`, `start_activity`,
`goal_complete`, and `goal_failed`; when an OCR provider is configured it also
offers the read-only `inspect_ocr` tool. The model returns exactly one tool call
per iteration. There is no JSON operation-plan response to parse. Package names
and Activity targets, coordinates, key names, gesture durations, and the
maximum step count are validated before any device operation is sent. Read-only
tools, including `inspect_ocr`, return data for the next planning iteration;
app and Activity launches are state-changing device actions and are never
retried. Device actions are recorded in the same `RunRecorder` stream as
ordinary calls; goal failures and failed actions are recorded as unsuccessful
Agent records.

The foreground Activity is collected from ADB `dumpsys` output and is supplied
as bounded structured data in both the LLM prompt and SysOne state:
`package`, fully qualified `activity`, normalized `component`, and the source
field used (`resumed_activity`, `current_focus`, or similar). If the backend
cannot report it, the model receives an explicit unavailable warning instead
of a fabricated Activity.

OCR is not run automatically. When a provider is configured, the LLM can call
`inspect_ocr` if it needs text or text bounds that are missing or unclear in
the screenshot and UI tree. The tool reads the screenshot from that observation
and returns bounded spans, confidence, screen bounds, and the screenshot digest
to the next planning iteration. A failed OCR request is reported to the LLM and
the tool is disabled for the rest of that run. Configure a provider to make the
tool available:

```python
from nier.config import load_config
from nier.models.factory import create_model_router


config = load_config("config/nier.yaml")
router = create_model_router(config)
with connect(config) as phone:
    run = phone.llm(
        "点击登录",
        router=router,
        provider="planner",
        ocr_provider="default",
    )
```

The Agent is intentionally a bounded goal-execution primitive. It does not
yet perform multi-model voting or automatically retry a failed action. The
loop is bounded by `max_steps` and requires an explicit `goal_complete` tool
call.

### Letting the Agent call SysOne

Pass `sysone=` or `sysone_provider=` to enable SysOne as advisory context; configured
SysOne providers are not queried implicitly by the LLM Agent. The Agent sends one
batched SysOne request on each goal observation when explicitly enabled. Its
`state["ui"]` field contains the bounded semantic UI tree, while
`state["ui_summary"]` contains a compact text summary. SysOne receives no screenshot,
screen dimensions, UI bounds, or OCR boxes. The `state["ocr"]` field is empty
until the LLM has called `inspect_ocr` for the current screenshot; then OCR
entries contain span IDs, text, and confidence. A Noul question checks whether
the current state is actionable, and a Choice question picks the most relevant
span when OCR spans are available. The typed result is recorded in
`run.plan.sysone` and provided to the LLM as advisory context; every action
still goes through normal validation.

```python
with connect("config/nier.yaml") as phone:
    run = phone.llm(
        "点击登录",
        dry_run=True,
    )
    print(run.plan.sysone)
```

`phone.llm()` uses LLM-first planning. Pass `sysone=` or `sysone_provider=` to
add SysOne advisory context; SysOne does not choose or dispatch actions, and a
SysOne request failure is recorded without blocking the LLM. Use
`phone.sysone()` to explicitly request SysOne-first candidate selection.
An explicit Agent can also make a typed call from the goal flow:

```python
agent = phone.agent()
answer = agent.ask_sysone(
    {"context": "..."},
    {"urgent": SysOneQuestion.noul("Does this require immediate attention?")},
)
print(answer.answer("urgent").noul)
```

SysOne advisory failures are recorded in `run.plan.sysone`; the LLM still receives
the current screen observation and remains responsible for each action.

### SysOne-first unified goals

Use `phone.sysone()` when the task can be expressed as a sequence of visible
UI/OCR selections and small system keys. SysOne selects among the finite,
host-validated candidates:

```python
with connect("config/nier.yaml") as phone:
    result = phone.sysone(
        "打开设置，进入关于本机",
        max_steps=8,
        max_seconds=45,
        allowed_apps={"设置": "com.android.settings"},
        allowed_controls=("关于本机", "向下滚动当前列表", "返回上一页"),
        prefer_webview=False,
        dry_run=True,
    )
```

This example previews one next action. Set `dry_run=False` only when the
connected device and candidates authorized through `allowed_controls` or
`allowed_apps` are approved for execution.
Use `prefer_webview=False` for native screens such as Settings to skip the
WebView DevTools probe; keep it enabled when the target screen is a WebView.

The host initially creates candidates from the current UI dump. It does not run
OCR automatically. If SysOne cannot choose from the semantic UI and visible
controls, it can select `inspect_ocr`; the host then runs one OCR read and asks
SysOne again with the resulting text spans. SysOne sees only each candidate's ID,
label, source, and semantic metadata; coordinates and executable actions stay
host-side. UI candidates must be visible clickable nodes with unique labels.
OCR candidates must have unique text. SysOne chooses an ID such as `ui_0` or
`ocr_1`, and the host executes the already validated action behind it. `back` is
a fixed system candidate. When the UI marks a bounded viewport as scrollable,
SysOne may also choose
`向下滚动当前列表` or `向上滚动当前列表`. The host keeps the swipe path private,
rechecks the viewport before dispatch, and counts the swipe as a main-goal
action. Include these labels in `allowed_controls` when using an allowlist.
`home` is offered when the goal mentions the launcher/home screen. `enter` is
offered only when `allowed_controls` explicitly includes `提交当前输入`. SysOne
never receives screenshots, screen dimensions, bounds, raw coordinates, shell
commands, or arbitrary action objects.

Use `allowed_controls` to constrain UI/OCR and fixed system-action labels;
`denied_controls` excludes matching labels. Matching ignores case and
surrounding or repeated whitespace; denied labels take precedence. If
`allowed_controls` is omitted, the host discovers unique visible clickable UI
controls and, after an OCR request, unique OCR labels. Candidate IDs are
regenerated for each observation and are never valid after the page changes.
OCR is optional; without a configured provider, UI candidates remain available
and `inspect_ocr` is not offered. With a provider configured, SysOne can request
OCR at most once for the current observation.
If the optional OCR provider is unavailable at that point (for example,
PaddleOCR is configured but not installed), the agent reports the OCR error
to SysOne, disables further OCR requests for this run, and continues using UI
candidates. It does not retry the failed OCR read.

If an LLM is configured, `next` offers `call_llm` by default without an
assist-count limit. SysOne can select it when progress is stuck; failed runs can also
request recovery. The LLM receives bounded semantic state and returns one
concise recovery subgoal—not advice to inject into the main SysOne loop. It then
executes the subgoal through native tool calls that select only current,
host-validated safe dismiss/cancel, Back, and explicitly requested Home
controls. Coordinates and arbitrary actions are never accepted. Recovery is
limited to three actions and thirty seconds (never beyond the main goal's
deadline when one is set). On
successful recovery,
the main goal re-observes the device and resumes. If a recovery subgoal fails,
the LLM can generate a different one from a fresh observation. Set
`max_llm_assists` to a non-negative integer to cap recovery-goal generations;
zero disables LLM recovery. Each generated subgoal remains limited to three
actions and thirty seconds. Repeated recovery on the same stalled screen
terminates even without an assist cap. Failed controls are excluded so device
actions are not retried automatically. The LLM may mark only its recovery subgoal complete
or failed; SysOne remains responsible for the main goal. It cannot provide
coordinates, text, packages, or arbitrary operations. `phone.sysone()` is the
explicit SysOne-first entry point.

Pass `allowed_apps` as an explicit mapping from a display label to an Android
package name to offer app-launch candidates, for example
`allowed_apps={"设置": "com.android.settings"}`. The host validates each
package and keeps it in the executable candidate; SysOne sees a candidate such as
`打开应用：设置` with source `app`, never the package name. No app-launch
candidates are offered by default, and SysOne cannot invent a package. App entries
are separate from `allowed_controls` and `denied_controls`. `open_app` changes
device state and is not retried automatically. If the goal should offer only
app launches, also pass `allowed_controls=()`; otherwise omitting
`allowed_controls` keeps the default discovery of visible UI/OCR and system
candidates.

Each observation sends one batched request containing:

- `done` — a required Noul completion predicate. A result at or above
  `done_threshold` stops the loop with `termination="needs_verification"`.
  The caller must check a fresh screenshot or UI dump independently before
  reporting a pass. `success=True` means the bounded run stopped normally;
  `needs_verification` does not mean the goal has been independently verified;
- `next` — a Choice over candidate IDs plus `blocked` and `wait`, and
  `inspect_ocr` when OCR is configured and has not run for this observation.
  Low confidence or an unknown choice never dispatches that selected
  candidate; it can enter bounded recovery when LLM is configured.
  `inspect_ocr` is a read-only request; after OCR, SysOne receives a new
  observation. `blocked` does not dispatch a main-goal action and may trigger
  bounded recovery. `wait` waits 750 ms and observes again; three consecutive
  waits trigger recovery and stop with `loading_timeout` if it fails;
- `progress` — an optional Score answer enabled with `use_score=True`. It is
  recorded for diagnostics/stuck detection and is not the success gate.

Immediately before an action, the host reads the device state again. If the UI,
candidate list, or host-side coordinates changed while SysOne was deciding, it
discards that answer and asks again against the fresh observation. An OCR-based
tap also requires the screenshot digest to match the image used for that OCR
read; this check does not run OCR a second time. Three stale decisions trigger
recovery and stop the run if recovery fails. Main-goal actions are bounded by
`max_steps`; recovery uses a separate bounded action budget. The overall
`max_seconds` deadline is disabled by default. Pass a positive value up to 60
seconds to enable it; it includes recovery and prevents starting another
action after it expires. It cannot interrupt an in-flight provider or device
call. Recovery keeps its separate 30-second cap when the main deadline is
disabled. Failed device actions are excluded from later candidates, not retried.
Provider or observation failures request bounded recovery when configured; if
recovery is unavailable or fails, the run stops with an error (and unexpected
exceptions remain surfaced to the caller). The caller should inspect a fresh
screenshot or UI dump when SysOne returns `needs_verification`.

`phone.llm()` uses the LLM-first Agent flow. The LLM can use screenshots, UI
state, OCR, app discovery, and validated native tools to choose each action.
It does not fall back to SysOne; use `phone.sysone()` for that flow. Use
`phone.agent().run()` when you want to customize the LLM Agent directly. Only run device actions on
an authorized device; `DeviceSession` never retries taps or other device actions.

## TypeSafe SysOne

SysOne is the typed-decision provider. Its wire API follows the TypeSafe
[quickstart](https://docs.typesafe.ai/introduction/quickstart) and
[primitive definitions](https://docs.typesafe.ai/primitives). It is useful when the application needs a
bounded `choice`, `score`, or `noul` answer. In the explicit SysOne-first
`phone.sysone(...)` flow, SysOne selects each action and can ask an LLM for
bounded recovery; `phone.llm(...)` uses LLM-first operation planning when an
LLM is available.

Set the key in the environment and configure `models.sysone` with the TypeSafe
provider. `model: jev-latest` is the upstream TypeSafe wire identifier and stays
unchanged; `sysone` names Nier's model role, while `typesafe` names its provider:

```yaml
models:
  sysone:
    provider: typesafe
    base_url: https://api.typesafe.ai/v1/systemone
    api_key_env: SYS_ONE_API_KEY
    model: jev-latest
    timeout_seconds: 30
    confidence_threshold: 0.75
```

The default key variable is `SYS_ONE_API_KEY`; the TypeSafe-specific
`TYPESAFE_API_KEY` variable is also recognized.

The direct Device API exposes one method per typed question:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    route = phone.choice(
        {"instruction": "find the account settings button"},
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
    print(route.choice, route.confidence, route.probabilities)
    print(urgent.noul, severity.score)
```

These methods return `SysOneAnswer` and lazily create/cache the first configured
TypeSafe provider for the connection. Pass `provider="name"` to select a named
entry, or `router=router` to reuse a `ModelRouter`. If no named provider mapping
is present, the singular `models.sysone` section is used. The standard-library
client needs no SysOne SDK; missing credentials and remote failures raise typed
errors. Only call them for a task the user has authorized.

For a UI task, `phone.widgets()` parses the current UI dump into device-bound
widgets. `clickable()` is optional: it can narrow the list explicitly, while
`choice()` always considers clickable widgets not marked hidden and with usable
screen bounds. The model receives labels and semantic attributes, not coordinates.
WebView DOM nodes without screen bounds are therefore not eligible for a tap.
See [the UI dump guide](uidump.md#choose-and-click-a-ui-widget) for the fluent
selection-and-click example. `DeviceSession` retries reads according to its
configured policy, but never automatically retries the eventual tap.

Scripts that need a single request with several questions can use the lower-
level `SysOneProvider.ask()` extension API via a configured router. This
requires a named entry under `models.sysone_providers`:

```yaml
models:
  sysone_providers:
    typed:
      provider: typesafe
      base_url: https://api.typesafe.ai/v1/systemone
      api_key_env: SYS_ONE_API_KEY
      model: jev-latest
```

```python
from nier.config import load_config
from nier.models.factory import create_model_router


config = load_config("config/nier.yaml")
router = create_model_router(config)
response = router.sysone(provider="typed").ask(
    {"message": "The payment failed twice"},
    {
        "urgent": {"type": "noul", "instructions": "Is immediate attention needed?"},
        "severity": {
            "type": "score",
            "instructions": "Rate the severity",
            "criteria": ["low", "medium", "high"],
        },
    },
)
print(f"Urgency score: {response.answer('urgent').noul}")
print(f"Severity score: {response.answer('severity').score}")
```

`SysOneAnswer` preserves the typed value, confidence, probabilities, and raw
answer. `router.sysone(provider="name")` selects a named low-level client.

When OCR coordinates are available, `SysOneDecisionProvider` can turn a SysOne choice
of `span_0`, `span_1`, and so on into a safe `Decision` with the original screen
coordinates. SysOne sees only span IDs, text, and confidence; coordinates remain
in the host-side `TextSpan` objects. The factory exposes this adapter as `sysone` when a default SysOne
provider is configured, or as `sysone:<name>` for named providers:

```python
decision = router.decide(spans, "点击设置", provider="sysone")
if decision.action == "tap" and decision.point is not None:
    phone.tap(*decision.point)
```

The API key is never put in configuration values or run records. SysOne requests
are synchronous and failures raise `ModelError`; review any resulting action
before dispatching it.
