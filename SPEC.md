# Nier implementation specification

This is the normative implementation document for the host runtime and its
backends. `MUST` and `MUST NOT` are mandatory; `SHOULD` and `SHOULD NOT` are
defaults that may be changed only with an explicit reason and updated tests.

The specification describes both the current contract and planned extension
points. A planned item is not a claim that the feature already exists.

## 1. Scope and topology

Nier consists of a host-side Python runtime and replaceable Android device
backends. The host owns configuration, retry policy, recording, model
providers, and session orchestration. A backend owns device communication and
implements the interface in `src/nier/backend.py`.

The default topology is:

```text
Python host -> ADB -> Android device
                       ├─ screencap / UIAutomator
                       └─ rooted nier-uinput -> /dev/uinput
```

The default path MUST NOT require a phone-side network server or listening
socket. A WebView DevTools UI request MAY create a temporary host-local ADB
forward to the target application's abstract DevTools socket; this optional
forward MUST be removed when the request completes.

Remote ADB over TCP is an explicit optional mode and is specified in section
4. It may use the device's `adbd` TCP endpoint or a separately hosted ADB
server; it does not alter the default local topology.

## 2. Backend contract and lifecycle

Every backend MUST provide these synchronous operations:

| Operation | Result | Contract |
| --- | --- | --- |
| `health()` | `bool` | Confirm that the target is reachable and ready. |
| `capabilities()` | `Capabilities` | Return protocol version, device identity, display size, root/input/UI capabilities, and action names. |
| `execute(action)` | `ActionResult` | Execute one validated action; do not silently report a failed command as success. |
| `screenshot(request)` | `Screenshot` | Return encoded image bytes, format, dimensions, and SHA-256. `DeviceSession` also accepts keyword options. |
| `dump_ui(request)` | `UiDump` | Return XML, source, completeness, and any fallback warning. `DeviceSession` also accepts keyword options. |
| `current_activity()` | `ActivityInfo | None` | Return the foreground Android Activity when the backend can inspect it. |
| `list_apps()` | `list[str]` | Return installed Android package names visible to the backend. |
| `list_app_activities(package)` | `list[str]` | Return fully qualified Activity class names declared by `package`. |
| `open_app(package)` | `ActionResult` | Launch the package's launcher Activity once. |
| `start_activity(package, activity)` | `ActionResult` | Launch one Activity in the package once. |
| `close()` | `None` | Release persistent resources; repeated close calls SHOULD be safe. |

The domain types in `src/nier/protocol.py` are transport-independent. Backend
adapters MUST preserve their behavior and error semantics when communicating
with an authorized device.

The public script API MUST be available as `nier.connect(...) -> Device`.
Ordinary Python callers SHOULD be able to control a device, save screenshots,
and read/save UI dumps without constructing protocol dataclasses:

```python
with connect("config/nier.yaml") as phone:
    phone.tap(0.5, 0.5, normalized=True)
    phone.text("hello")
    packages = phone.list_apps()
    activities = phone.list_app_activities("com.android.settings")
    phone.open_app("com.android.settings")
    phone.start_activity("com.android.settings", ".Settings")
    phone.screenshot("artifacts/screen.png", max_width=1280)
    xml = phone.uidump("artifacts/ui.xml", prefer_webview=False)
```

`DeviceSession` is the lower-level session API and SHOULD accept keyword
options for screenshots and UI dumps. Action and request dataclasses remain
supported for backend adapters, transport mapping, and reusable structured
requests. A `DeviceSession` call MUST NOT mix a request object with keyword
options.

The public parser `nier.parse_uidump` MUST accept a `UiDump`, saved `Path`, or
raw XML/HTML string and return a searchable `UiDocument`. `Device.parse_uidump`
SHOULD capture and parse a fresh dump when called without input. Parsed nodes
MUST preserve source attributes, text, child order, UIAutomator bounds when
present, and the original dump metadata. Parsing MUST NOT execute a device
action; callers decide whether a matched node should be tapped.

Expected failures MUST use `NierError` subclasses. In particular:

- unavailable devices, failed backend calls, and timeouts use
  `BackendUnavailable` or an appropriate `BackendError`;
- malformed device responses, invalid image payloads, and unsupported wire
  values use `ProtocolError`;
- invalid configuration uses `ConfigurationError`;
- provider initialization or inference failures use `ModelError`.

`DeviceSession` MAY retry read-style operations (`health`, `capabilities`,
`screenshot`, `dump_ui`, `current_activity`, `list_apps`, and
`list_app_activities`) after `BackendUnavailable` or `TimeoutError`, using
bounded backoff. It MUST NOT retry `execute`, `open_app`, or
`start_activity`: repeating a tap, text input, key event, or launch can mutate
the application twice after a lost reply.

## 3. Domain and action rules

- `RequestContext.request_id` MUST be non-empty and `deadline_ms` MUST be
  positive.
- `Point` coordinates MUST be finite. A normalized point MUST use inclusive
  `[0, 1]` coordinates. An absolute point is expressed in screen pixels.
- ADB maps normalized coordinates to the display and clamps the final pixel to
  `[0, width - 1]` and `[0, height - 1]` (and the corresponding y range).
- A `Click` duration MUST be non-negative. A `Swipe` MUST contain at least two
  points and have a positive duration.
- `InputText` sends text as one logical action. `Key` uses the supported
  `KeyCode` values; unknown key codes MUST be rejected.
- `ScreenshotRequest.quality` is in `[1, 100]`; maximum dimensions are either
  zero (unrestricted) or non-negative pixel limits.
- `list_app_activities(package)` MUST reject an empty or malformed Android
  package name before sending a device command. It returns class names, not
  launch results, and MUST NOT start an Activity.
- `open_app(package)` MUST validate the package name, launch its Android
  `MAIN`/`LAUNCHER` entry point, and MUST NOT be automatically retried.
- `start_activity(package, activity)` MUST validate that the target belongs to
  `package`. It accepts a short class name, a relative `.ClassName`, a fully
  qualified class name, or a `package/class` component, normalizes it to
  `package/full.class`, and MUST NOT be automatically retried.

Actions operate in screen coordinates by default. Backends MUST preserve the
meaning of normalized and absolute coordinates when converting to a transport
or device-specific representation.

## 4. Default ADB backend

`AdbBackend` MUST:

1. verify that ADB reports a ready device for `health()`;
2. discover the display size with `wm size` and cache it for the backend
   session;
3. query root access and probe the configured uinput executable when needed;
4. lazily start at most one rooted `nier-uinput serve` session per backend
   session and reuse it for click/swipe actions;
5. fall back to Android `input` commands when rooted uinput is unavailable;
6. capture screenshots with `adb exec-out screencap -p`;
7. capture normal UI with `adb exec-out uiautomator dump --compressed
   /dev/stdout`; if streaming is unsupported, read a temporary device-side
   file and remove it even when reading fails;
8. inspect the foreground Activity from `dumpsys activity activities`, with
   `dumpsys window windows` as a fallback;
9. list installed packages with `pm list packages`;
10. list declared Activities with `dumpsys package <package>` without
    confusing receivers or services for Activities;
11. launch a package with `am start -a android.intent.action.MAIN -c
    android.intent.category.LAUNCHER -p <package>` and launch an explicit
    Activity with `am start -n <package>/<full.class>`;
12. release the persistent uinput session from `close()` and after a failed
    persistent command.

The default uinput path is `/data/local/tmp/nier-uinput` and the default
device is `/dev/uinput`; both MUST remain configurable through `DeviceConfig`.
The ADB path and optional device serial are configurable as well.

The default ADB backend MUST NOT start an Android service or open a device-side
socket. It MAY create and remove a temporary ADB forward only while handling
an explicit WebView DevTools UI request.

### Optional IME text backend

`InputText` MUST use the Android shell-input path by default. When
`input_text.mode=ime` is explicitly configured, the backend MAY use the
installed Nier `InputMethodService` through an exported, UID-gated content
provider and `adb shell content call`. The IME backend MUST support UTF-8 text,
MUST require the Nier IME to be selected unless `input_text.auto_enable=true`,
and MUST restore the previous selected IME on close when
`input_text.restore_previous=true` and the user has not changed it meanwhile.
It MUST work in both root and non-root host modes; root access MUST NOT be a
requirement for text submission.

### Optional remote ADB

When `DeviceConfig.remote_host` is set, the target serial is
`remote_host:remote_port` (default port `5555`). With `auto_connect=true`, the
client MUST issue `adb connect` once before the first ADB operation and then
run all commands with `-s remote_host:remote_port`. With `auto_connect=false`,
the target MUST already be known to the selected ADB server.

`DeviceConfig.serial` and `remote_host` are mutually exclusive. An optional
`adb_server_host`/`adb_server_port` pair selects a remote ADB server through
`adb -H ... -P ...` and may be combined with `serial` or `remote_host`.
Connection failures MUST surface as `BackendUnavailable`; credentials,
pairing data, and device addresses MUST NOT be written to logs or tracked
configuration unless the user explicitly chooses to do so.

## 5. Screenshot contract

`Screenshot` contains the encoded `data`, `format`, `width`, `height`, and
lowercase SHA-256 digest of the returned bytes.

- An unrestricted PNG request SHOULD return the original ADB PNG without
  re-encoding.
- JPEG conversion and dimension limiting are host-side operations using
  Pillow. The aspect ratio MUST be preserved and each requested limit MUST be
  respected.
- An empty or malformed image payload MUST raise a backend/protocol error.
## 6. UI dump contract

UIAutomator is the normal source for Android views. When
`hook.target_package` is configured, a request with `prefer_webview=True`
first attempts a WebView DevTools DOM dump. On success:

- `source` is `WEBVIEW_DEVTOOLS`;
- `complete` is `true` when non-empty DOM HTML is returned;
- `warning` is empty.

The host resolves the target process, forwards
`localabstract:webview_devtools_remote_<pid>` to a temporary loopback port,
queries `/json/list`, and uses CDP `DOM.getDocument` plus
`DOM.getOuterHTML`. The forward MUST be removed after the dump. A failed
connection, missing target, or malformed CDP response MUST fall back to
UIAutomator with a warning:

- `source` is `UIAUTOMATOR_FALLBACK`;
- `complete` reflects whether XML was obtained;
- `warning` explains why WebView DevTools was unavailable.

`parse_uidump` MUST return a `UiDocument` whose `to_dict()` method produces
JSON-ready structured data. The default representation MUST include source,
completeness, warning, a hierarchical `root`, normalized element fields, and
source attributes. It MUST be bounded by node and text limits by default;
`max_nodes=None` and `max_text_length=None` MAY request the complete parsed
tree. Raw XML/HTML MUST be opt-in through `include_raw=True`.

`AdbBackend.capabilities().supports_webview_debugging` is `true` when a target
package is configured and `false` otherwise. The optional hook controller in
`src/nier/hooks.py` implements the instrumentation boundary:

- `root` mode MUST require a rooted device, a root-capable `frida-server`, and
  the optional `frida` host dependency; it may attach to an existing process
  or spawn the target package before resuming it;
- `non-root` mode MUST NOT call `su`, ptrace, or Frida attach. It is cooperative
  only: the target application must call
  `WebViewDebugController.enable()` before creating its WebView;
- `auto` mode selects root mode only after an ADB root check and otherwise
  selects the cooperative non-root mode.

When `hook.force_system_back=true`, root Frida mode additionally installs the
Back policy hook before the first configured Back action. This option MUST be
disabled by default, MUST require `hook.target_package`, and MUST reject
explicit `non-root` mode. The hook blocks common AndroidX and platform Back
callback registrations and routes supported legacy Java callbacks to the
platform `Activity` default. `spawn=true` SHOULD be used so callbacks are
blocked before the application registers them. This is an authorized,
best-effort Java hook; native engines, already-registered callbacks in attach
mode, and application-specific navigation layers may require a target-specific
Frida script.

The hook enables `WebView.setWebContentsDebuggingEnabled(true)`, and
`src/nier/webview.py` performs the separate CDP extraction. Root and non-root
therefore share the same DOM extraction path after debugging is enabled.

## 7. Rooted uinput helper

`backend/nier-uinput` is a root-only standalone executable. It MUST:

- require positive screen dimensions and a usable uinput path;
- create a single-slot multitouch Protocol-B virtual device through
  `/dev/uinput` (or the configured path);
- support direct `probe`, `click`, and multi-point `swipe` commands;
- support persistent `serve` mode over stdin/stdout, not a network socket;
- wait until Android's input reader can observe the newly created device before
  emitting the first event;
- validate every touch point against `[0, width) × [0, height)`;
- destroy the virtual device on normal close and best-effort during teardown;
- linearly interpolate swipe segments so adjacent samples are at most 16 pixels
  apart in the dominant axis, while preserving the requested total duration.

The persistent protocol is line-oriented:

```text
startup: READY
PING
CLICK X Y DURATION_MS
SWIPE DURATION_MS POINT_COUNT X1 Y1 X2 Y2 ...
CLOSE
responses: one OK or ERR <message> per command
```

`SWIPE` requires 2–4096 points. `CLOSE` ends the session; EOF MUST also clean
up the virtual device. The host keeps this process alive for the backend
session and falls back to `adb shell input` if probing fails.

## 8. Configuration and model providers

Configuration is loaded from YAML into immutable dataclasses in
`src/nier/config.py`. Device, runtime, OCR, LLM, and Jev settings MUST be
validated before use. API keys are read from environment variables named by
`api_key_env` by default. A non-empty direct `api_key` value MAY be supplied
in local configuration and MUST take precedence over the environment value.
Direct keys MUST NOT be stored in tracked configuration or logs.

The optional `logging.verbosity` configuration MUST accept levels `0` through
`3` (and the aliases `v`, `vv`, and `vvv`): level 1 logs high-level steps,
level 2 additionally logs sanitized request metadata, and level 3 additionally
logs bounded, sanitized response payloads. The CLI flags `-v`, `-vv`, and
`-vvv` MUST select at least the corresponding level for that invocation.
Authorization headers, API keys, and screenshot data URIs MUST NOT appear in
logs. Terminal logs and CLI command summaries MUST use labeled, human-readable
text rather than print JSON-encoded event objects. Persisted run records and
wire-protocol payloads remain structured data and are not changed by this rule.

The model layer exposes these stable interfaces:

- `OcrProvider.recognize(image) -> Sequence[TextSpan]`;
- `DecisionProvider.decide(text, instruction) -> Decision`;
- `LlmProvider.complete(prompt, image=None) -> str`;
- `LlmProvider.complete_with_tools(prompt, tools, image=None) ->
  Sequence[LlmToolCall]` for native Agent planning.

The TypeSafe Jev integration exposes a typed `JevProvider.ask(state, questions)`
API plus `choice`, `score`, and `noul` convenience methods. Jev requests MUST
preserve the question ids and typed answer values, and responses MUST retain
confidence/probability data when supplied by the service. Jev is a decision
provider, not an `LlmProvider`; it MUST NOT be used as the free-form planner for
`Device.agent()`.

OCR providers MUST preserve each recognized text span's screen bounding box.
Decision providers SHOULD consume those coordinates instead of asking an LLM to
localize an already recognized control. The current implementations are
local PaddleOCR, the PaddleOCR hosted API adapter, deterministic OCR text
matching, TypeSafe Jev, provider routing, an OpenAI-compatible completion and
native tool-call adapter, and a validated natural-language Agent. The hosted
OCR adapter MUST read its token
from `api_key_env`, submit the screenshot through the PaddleOCR client, and
normalize the returned text, confidence, and polygon/rectangle coordinates
into `TextSpan` values. Remote OCR failures MUST raise `ModelError` and MUST
not silently fall back to local OCR.

`Device.agent()` MUST provide the LLM-first Agent flow: it sends native tool
definitions with the current screenshot/UI state and natural-language goal,
then compiles returned tool calls into validated `AgentStep` values before
executing. `Device.run(instruction)` MUST use the Jev-first goal flow whenever
a direct Jev client, an explicit Jev provider, a Jev-containing router, or a
configured Jev provider is available. In that flow, Jev selects from the
host-validated finite candidate set; an optional LLM can provide a bounded
recovery subgoal when Jev selects `call_llm` or failure recovery is needed.
The nested recovery goal does not return free-form strategy text to the main
Jev loop. If Jev is not configured and no Jev-specific option
is requested, `Device.run()` MUST preserve the LLM-first Agent flow. The model
context MUST include a bounded foreground Activity object when available, and
an explicit unavailable warning otherwise. The same Activity object MUST be
included in Jev state. Neither flow MUST require a free-form JSON
operation-plan response. The Agent MUST re-observe the device after each action,
accept exactly one next action or goal-control tool call per iteration, and
stop only on `goal_complete`, `goal_failed`, an action failure, or the
`max_steps` limit.
Only the allowlisted tap, swipe, text, key, back, home, enter, list_apps,
list_app_activities, open_app, and start_activity operations may be executed.
The list tools are read-only; the launch tools change device state. Package
names, Activity targets, coordinates, key names, durations, and the maximum
step count MUST be validated before dispatch. `dry_run=True` MUST return a
validated next-action `AgentPlan` without dispatching actions. The Agent MUST
write its goal progress and outcome to the same `RunRecorder` used by the
session.

When a direct `jev` client is supplied, or when `jev_provider` is omitted and a
configured Jev provider exists, the LLM-first Agent MUST make one typed Jev
observation call per goal iteration containing the current goal, UI state, and OCR spans.
The Jev request MUST NOT include screenshots, screen dimensions, or spatial
coordinates. Its bounded `ui` tree MUST preserve source/completeness metadata,
hierarchy, semantic source attributes, text/content descriptions, resource
identifiers, and interaction/visibility flags, while omitting bounds and
centers. The tree MUST contain at most 128 nodes and clip text fields to 240
characters. OCR entries MUST contain text and confidence without bounding
boxes; at most 64 spans, each clipped to 240 characters, may be sent. A compact
semantic `ui_summary` MAY accompany it and MUST be bounded to 6,000 characters.
When parsing fails, `ui` MUST remain a JSON object describing the unavailable
structured state rather than raw XML/HTML. The request MUST contain a Noul
readiness question and a Choice target question when OCR spans exist. Jev answers
MUST be preserved in the current `AgentPlan.jev` and supplied to the LLM as
advisory context.
The LLM prompt MUST contain the bounded structured UI tree and MAY include
geometry and raw XML/HTML as supplementary context. Jev answers MUST NOT bypass
AgentStep validation or directly dispatch device actions. A Jev request
failure MUST fail goal execution instead of silently disabling the configured
provider. If no Jev provider is configured and no direct client is supplied,
the Agent proceeds without Jev context.

`Device.jev_goal()` creates the Jev-first goal runner used by
`Device.run(instruction)`. `Device.run_jev_goal(instruction)` MUST remain a
backward-compatible wrapper to that same flow. This flow MUST NOT ask Jev to
generate arbitrary device operations. For each observation, the host MUST
expose the goal, bounded
foreground Activity, a bounded semantic UI tree, optional OCR text/confidence,
bounded recent action history, and a finite candidate list. Jev MUST NOT receive
screenshots, screen dimensions, bounds, centers, coordinates, executable action
objects, or raw UI markup. Candidate IDs and concise labels are sent to Jev;
the corresponding coordinates and host-validated `AgentStep` remain host-side.
The UI tree MUST contain at most 128 nodes with text clipped to 240 characters;
OCR MUST include at most 64 spans clipped to 240 characters, the summary MUST
be at most 6,000 characters, candidate labels MUST be at most 160 characters,
and only the eight most recent action outcomes may be included.
UI candidates MUST come from visible, uniquely labelled clickable nodes; OCR
candidates MUST have unique text labels. `allowed_controls` and
`denied_controls` MUST filter labels by exact match after case/whitespace
normalization, with denied labels taking precedence, for UI/OCR and fixed
system candidates. `allowed_apps` MUST be an explicit mapping of non-empty
display labels to validated Android package names. Each mapping entry MAY add
one bounded `open_app` candidate; no app candidate may be offered by default,
and a Jev response MUST NOT supply or alter a package name. Jev MUST see only
the app candidate ID and display label, not the package or executable action.
`allowed_controls` MUST NOT implicitly authorize app launches. When
`allowed_controls` is omitted, the host MAY discover all unique visible UI/OCR
candidates subject to `denied_controls`; when it is supplied, only listed
UI/OCR/system labels may be offered. Candidate IDs MUST be regenerated after
an observation and MUST NOT be trusted as coordinates or commands.

When an OCR provider is configured, the host MUST expose `ocr_available` and
MUST NOT run OCR before Jev requests it. The initial observation MUST omit OCR
spans and MUST offer `inspect_ocr` as a non-action Choice option. If Jev selects
it, the host MUST re-read the UI state, run OCR once, and ask Jev again with the
recognized spans. `inspect_ocr` MUST be removed after that read and MAY be
offered again only for a new observation. When no OCR provider is configured,
the option MUST NOT be offered.

The Jev goal request MUST contain a `done` Noul question and a `next` Choice
question. `done` MUST use a configurable threshold; reaching it MUST return
`needs_verification` and MUST NOT be reported as an independently verified
pass. The caller is responsible for checking a fresh screenshot or UI dump.
`next` MUST contain generated candidate IDs and the `blocked` and `wait`
signals. It MUST contain `inspect_ocr` only when available for the current
observation. If an LLM provider is configured and the `max_llm_assists` cap has
not been reached, `next` MUST also contain `call_llm`; otherwise that option
MUST be absent. `max_llm_assists` MUST accept `None` or a non-negative integer,
and default to `None`, which allows any number of LLM recovery-goal generations
per run. Zero disables LLM recovery assistance. An unknown or below-threshold candidate
choice MUST NOT dispatch that candidate; it MAY enter the bounded recovery
flow. `blocked` MUST NOT dispatch a candidate from the failed main observation;
it MAY enter the bounded recovery flow. `wait` MUST trigger a bounded wait and
fresh observation; three consecutive waits MUST trigger recovery and, if that
recovery fails, stop with a loading timeout.
When selected, `call_llm` MUST pass the user goal, bounded semantic
observation, and stop reason to `LlmProvider.complete`. The response MUST be one
bounded recovery subgoal, not strategic text returned to the main Jev loop.
Recoverable blocked, low-confidence, stale-state, loading-timeout, action
failure, and action/planning exception outcomes MUST also request a recovery
subgoal when an LLM is configured and time remains. The LLM MUST NOT select or
dispatch an action, supply coordinates/packages/commands, request task
submission/deletion/purchase/permission changes, or declare completion. Each
response MUST be bounded to 1,200 characters.

Every recovery subgoal MUST run as a nested Jev goal with LLM assistance
disabled. It MUST NOT inherit `allowed_apps`; its UI/OCR/system candidates MUST
be restricted to the fixed safe dismiss/close/cancel/skip/back controls, plus
Home only when requested by the recovery instruction, and MUST still honor the
caller's `allowed_controls` and `denied_controls`. A recovery run MUST be
bounded to at most three device actions and thirty seconds, further limited by
the remaining main-goal deadline when one is set. It MUST NOT repeat any
control whose action failed or raised during the current run. On nested-goal
completion, the parent
MUST take a new observation and resume the original main goal if its main
action and time budgets permit; otherwise it MUST terminate with the applicable
main-goal limit. The generated recovery text MUST NOT be added to the parent
Jev context as strategy advice.

If a nested recovery subgoal fails, the host MUST pass its outcome and a fresh
bounded semantic observation to the LLM to generate a different subgoal while
the `max_llm_assists` cap has remaining allowance, or without a count limit
when it is `None`. Exhausting a configured cap MUST terminate recovery as
failed without returning an action suggestion to the main Jev. If the LLM
provider fails to generate a recovery goal, recovery MUST fail. Other
provider/observation failures MAY resume only after a successful nested
recovery; otherwise they MUST fail the run (unexpected exceptions remain
surfaced to the caller). Dry-run mode MUST NOT execute recovery actions.
`max_steps` bounds
main-goal actions; recovery has its separate bounded action budget. The parent
`max_seconds` deadline MUST also bound recovery, and no recovery action may
start after it expires. An in-flight provider or device call need not be
interrupted.
The initial candidate implementation MUST limit execution to bounded UI/OCR
taps, app launches from `allowed_apps`, and fixed safe system keys; free-form
text, shell commands, Activity launches, and unbounded gestures MUST remain
outside this flow. App package names MUST be validated on the host. Device
actions, including `open_app`, MUST never be retried automatically. Pressing
Enter MUST require the corresponding explicit `allowed_controls` label.

An optional `use_score=True` setting MAY add one progress Score question. Its
answer MUST be recorded for diagnostics or future stuck detection and MUST
NOT independently establish success. The default implementation MUST batch
`done` and `next` in one Jev request per observation and MUST re-observe after
each action. Immediately before dispatch, the host MUST take a fresh
observation and discard the decision if the UI candidate list or its
host-side coordinates have changed. For an OCR candidate, the host MUST also
compare the fresh screenshot digest with the image used for OCR, without running
OCR again. Stale decisions MUST be bounded; after three consecutive stale
decisions the goal MUST attempt bounded recovery and, if recovery fails, stop.
`max_steps` bounds main-goal actions; each recovery subgoal has its own smaller
action budget. `max_seconds` MUST default to `None`, which disables the overall
wall-clock deadline. Callers MAY set it to a positive value up to 60 seconds;
when set, it MUST include recovery. The time limit MUST prevent
starting a new action after expiry; it need not interrupt an in-flight provider
or device call. Recovery retains its own 30-second cap when the main deadline
is disabled.
The Jev goal MUST use the same `RunRecorder`, dry-run semantics, provider
selection rule (first configured provider when omitted), and bounded action
limit as the regular Agent.

Multi-model voting and automatic post-action verification remain planned
extensions.

## 9. API surface and documentation

API documentation MUST be derived from the actual public Python interfaces:

- Python source and docstrings: `src/nier/`, especially `api.py`, `backend.py`,
  `protocol.py`, `config.py`, `session.py`, `ui.py`, `results.py`, and
  `models/`;
- user-facing setup: `README.md` and component READMEs.

The hand-maintained usage guides are indexed by
[`docs/README.md`](docs/README.md). Documentation maintenance and
the rules for any future generated reference pages are defined in
[`AGENTS.md`](AGENTS.md); `SPEC.md` does not require a documentation generator.
Public API changes MUST update the implementation docstrings, relevant feature
guide, and tests in the same change.

## 10. Verification baseline

Every change MUST keep the relevant Python tests passing:

```bash
python -m pytest
```

Changes to `backend/nier-uinput` SHOULD also run:

```bash
cmake -S backend/nier-uinput -B /tmp/nier-uinput-build
cmake --build /tmp/nier-uinput-build
ctest --test-dir /tmp/nier-uinput-build --output-on-failure
```

An authorized rooted-device smoke test may additionally verify uinput probing,
an interpolated swipe, screenshot retrieval, and UI dumping. That smoke test is
environment-dependent and is not a prerequisite for ordinary unit tests.

## 11. Technology and compatibility constraints

- Python 3.10+ is the supported host runtime.
- Kotlin/C++ are limited to optional Android integrations and native input
  code.
- Use `jj` for version control. Version-control operations are workflow
  concerns and do not change the runtime contract.

## 12. Local web execution dashboard

The `nier web --scripts=<directory>` command MUST serve a local execution
dashboard using FastAPI and MUST bind to `127.0.0.1` by default. It MUST NOT
change the ADB-first device topology or start a phone-side server. The dashboard
MUST list Python scripts from the requested directory and MUST reject script
paths that resolve outside it. Starting a script MUST require an explicit
browser confirmation and MUST run at most one script at a time. Stopping a run
MAY terminate the script process; script and device actions MUST NOT be
automatically retried.

The dashboard MUST offer optional STEP-boundary controls without changing
normal script runs. A debug run MUST pause at the first Nier `STEP` event and
support continue, single STEP, step into, and step out controls. Single STEP
MUST resume through exactly one subsequent `STEP` event and pause at the next
one. Step into MUST pause at a subsequent STEP event with a deeper call path;
step out MUST pause at one with a shallower call path. These controls MUST NOT
advance by Python source lines. STEP details and call paths MAY be shown in the
browser using the same bounded, redacted event fields. Stopping a paused debug
run MUST terminate its child process.

The dashboard MUST visualize received STEP events in execution order and MUST
allow the user to inspect STEP details and related request/response logs.
Structured Nier events MUST pass through the existing bounded redaction policy
before leaving the child script process. Ordinary script stdout and stderr MAY
be displayed as emitted by the script and MUST be identified as unsanitized.
Static web assets MUST be bundled with the Python package; frontend dependencies
MUST NOT be required at runtime.
