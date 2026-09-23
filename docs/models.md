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
    run = phone.run(
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
    run = phone.run(
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

When `provider`, `ocr_provider`, or `jev_provider` is omitted, the first
configured entry of that provider type is selected.

The planner receives the current screenshot, foreground Activity, and parsed UI dump. In addition to
the raw dump and a compact compatibility summary, the LLM prompt contains a
bounded JSON UI tree. Each element keeps its hierarchy and may include
`bounds`, `center`, `clickable`, `visible`, source `attributes`, and nested
`children`. This gives the model stable fields to reason over instead of
requiring it to parse XML or HTML. The Agent sends native function/tool
definitions for `tap`, `swipe`, `text`, `key`, `back`, `home`, `enter`,
`list_apps`, `list_app_activities`, `open_app`, `start_activity`,
`goal_complete`, and `goal_failed`; the model returns exactly one tool call per
iteration. There is no JSON operation-plan response to parse. Package names
and Activity targets, coordinates, key names, gesture durations, and the
maximum step count are validated before any device operation is sent. The list
tools are read-only and may use the session read retry policy; app and Activity
launches are state-changing device actions and are never retried. Device
actions are recorded in the same `RunRecorder` stream
as ordinary calls; goal failures and failed actions are recorded as
unsuccessful Agent records.

The foreground Activity is collected from ADB `dumpsys` output and is supplied
as bounded structured data in both the LLM prompt and Jev state:
`package`, fully qualified `activity`, normalized `component`, and the source
field used (`resumed_activity`, `current_focus`, or similar). If the backend
cannot report it, the model receives an explicit unavailable warning instead
of a fabricated Activity.

To add OCR text and coordinates to the planner context, provide a configured
router:

```python
from nier.config import load_config
from nier.models.factory import create_model_router


config = load_config("config/nier.yaml")
router = create_model_router(config)
with connect(config) as phone:
    run = phone.run(
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

### Letting the Agent call Jev

When Jev is configured, the Agent automatically uses the first configured
provider; pass `jev_provider` to select a named one explicitly. The Agent
sends one batched Jev request on each goal observation. Its `state["ui"]` field
contains the bounded semantic UI tree and `state["ui_summary"]` contains a
compact text summary. Jev receives no screenshot, screen dimensions, UI bounds,
or OCR boxes. OCR entries contain span IDs, text, and confidence. A Noul
question checks whether the current state is actionable, and when OCR is
enabled a Choice question picks the most relevant span. The typed result is
recorded in `run.plan.jev` and provided to the LLM as advisory context; every
action still goes through normal validation.

```python
with connect("config/nier.yaml") as phone:
    run = phone.run(
        "点击登录",
        dry_run=True,
    )
    print(run.plan.jev)
```

For a custom Jev client, pass `jev=` to `phone.agent()` or `phone.run()`. An
Agent can also make an explicit typed call from the goal flow:

```python
agent = phone.agent()
answer = agent.ask_jev(
    {"context": "..."},
    {"urgent": JevQuestion.noul("Does this require immediate attention?")},
)
print(answer.answer("urgent").noul)
```

If a configured Jev request fails, goal execution fails rather than silently
disabling the provider or falling back to an unverified decision.

### Jev-driven goals

Use `run_jev_goal()` when the task can be expressed as a sequence of visible
UI/OCR selections and small system keys, and you want Jev to be the goal
decision model without an LLM planner:

```python
with connect("config/nier.yaml") as phone:
    result = phone.run_jev_goal(
        "打开设置，进入关于本机",
        max_steps=8,
        max_seconds=45,
        allowed_apps={"设置": "com.android.settings"},
        allowed_controls=("关于本机", "返回上一页"),
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
OCR automatically. If Jev cannot choose from the semantic UI and visible
controls, it can select `inspect_ocr`; the host then runs one OCR read and asks
Jev again with the resulting text spans. Jev sees only each candidate's ID,
label, source, and semantic metadata; coordinates and executable actions stay
host-side. UI candidates must be visible clickable nodes with unique labels.
OCR candidates must have unique text. Jev chooses an ID such as `ui_0` or
`ocr_1`, and the host executes the already validated action behind it. `back` is
a fixed system candidate;
`home` is offered when the goal mentions the launcher/home screen. `enter` is
offered only when `allowed_controls` explicitly includes `提交当前输入`. Jev
never receives screenshots, screen dimensions, bounds, raw coordinates, shell
commands, or arbitrary action objects.

Use `allowed_controls` to constrain UI/OCR and fixed system-action labels;
`denied_controls` excludes matching labels. Matching ignores case and
surrounding or repeated whitespace; denied labels take precedence. If
`allowed_controls` is omitted, the host discovers unique visible clickable UI
controls and, after an OCR request, unique OCR labels. Candidate IDs are
regenerated for each observation and are never valid after the page changes.
OCR is optional; without a configured provider, UI candidates remain available
and `inspect_ocr` is not offered. With a provider configured, Jev can request
OCR at most once for the current observation.

Pass `allowed_apps` as an explicit mapping from a display label to an Android
package name to offer app-launch candidates, for example
`allowed_apps={"设置": "com.android.settings"}`. The host validates each
package and keeps it in the executable candidate; Jev sees a candidate such as
`打开应用：设置` with source `app`, never the package name. No app-launch
candidates are offered by default, and Jev cannot invent a package. App entries
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
  Low confidence or an unknown choice stops without dispatching an action.
  `inspect_ocr` is a read-only request; after OCR, Jev receives a new
  observation. `blocked` returns control immediately. `wait` waits 750 ms and
  observes again; three consecutive waits stop with `loading_timeout`;
- `progress` — an optional Score answer enabled with `use_score=True`. It is
  recorded for diagnostics/stuck detection and is not the success gate.

Immediately before an action, the host reads the device state again. If the UI,
candidate list, or host-side coordinates changed while Jev was deciding, it
discards that answer and asks again against the fresh observation. An OCR-based
tap also requires the screenshot digest to match the image used for that OCR
read; this check does not run OCR a second time. Three stale decisions stop the
run. The flow is bounded by `max_steps` and `max_seconds`
(45 seconds by default and maximum). The deadline prevents starting another
action after it expires; it cannot interrupt an in-flight provider or device
call. Device actions are not retried. Provider or observation failures stop the
run with an error. The caller should inspect a fresh screenshot or UI dump when
Jev returns `needs_verification`.

This keeps Jev in a mechanical selection role: it cannot type text or invent
coordinates and operations. Use `phone.run()` when the goal needs text
generation, free-form swipes, app discovery, or actions outside the finite
candidate set. Only run this flow on a connected device and for a goal whose
candidate actions you authorize; `allowed_controls` and `denied_controls` can
narrow that set. `DeviceSession` never retries taps or other device actions.

## TypeSafe Jev

Jev is the typed-decision provider. Its wire API follows the TypeSafe
[quickstart](https://docs.typesafe.ai/introduction/quickstart) and
[primitive definitions](https://docs.typesafe.ai/primitives). It is useful when the application needs a
bounded `choice`, `score`, or `noul` answer instead of another free-form plan.
It is separate from the LLM used by `phone.run(...)`: an LLM can write an
operation flow, while Jev can classify, route, or gate a decision in that flow.

Set the key in the environment and add an optional `models.jev` section:

```yaml
models:
  jev:
    provider: typesafe
    base_url: https://api.typesafe.ai/v1/systemone
    api_key_env: TYPESAFE_API_KEY
    model: jev-latest
    timeout_seconds: 30
    confidence_threshold: 0.75
```

The direct API is intentionally small:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    answer = phone.jev().choice(
        {"instruction": "find the account settings button"},
        ["account", "notifications", "help"],
        instructions="Which option best matches the instruction?",
    )
    print(answer.choice, answer.confidence, answer.probabilities)
```

`phone.jev()` loads the first provider from `models.jev_providers` on first use
and caches it for the connection lifetime. If no named mapping is present,
the singular `models.jev` section is used. Scripts do not need to construct
or close a `JevProvider` themselves. Use `provider="name"` only when selecting
a named entry explicitly.

For more than one question, use the typed request API:

```python
from nier import JevQuestion, connect


with connect("config/nier.yaml") as phone:
    response = phone.jev().ask(
        {"message": "The payment failed twice"},
        {
            "route": JevQuestion.choice(
                "Choose the support route",
                ["billing", "technical", "general"],
            ),
            "urgent": JevQuestion.noul("Is immediate attention needed?"),
            "severity": JevQuestion.score(
                "Rate the severity",
                ["low", "medium", "high"],
            ),
        },
    )
    print(f"Route: {response.answer('route').choice}")
    print(f"Urgency score: {response.answer('urgent').noul}")
    print(f"Severity score: {response.answer('severity').score}")
```

`JevAnswer` preserves the typed value, confidence, probabilities, and raw
answer. The client uses the standard library HTTP implementation; no Jev SDK
package is required. `phone.jev(provider="name")` selects a named provider
from `models.jev_providers`; omitting the argument selects the first one. A
configured router can be reused with `phone.jev(router=router)` or
`router.jev(provider="name")`.

When OCR coordinates are available, `JevDecisionProvider` can turn a Jev choice
of `span_0`, `span_1`, and so on into a safe `Decision` with the original screen
coordinates. Jev sees only span IDs, text, and confidence; coordinates remain
in the host-side `TextSpan` objects. The factory exposes this adapter as `jev` when a default Jev
provider is configured, or as `jev:<name>` for named providers:

```python
decision = router.decide(spans, "点击设置", provider="jev")
if decision.action == "tap" and decision.point is not None:
    phone.tap(*decision.point)
```

The API key is never put in configuration values or run records. Jev requests
are synchronous and failures raise `ModelError`; review any resulting action
before dispatching it.
