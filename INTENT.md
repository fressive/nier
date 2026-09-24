# Nier product intent

Nier is an extensible Android automated-testing framework. The host-side
Python runtime orchestrates test operations and model providers; replaceable
backends acquire device state and apply input actions.

This document describes the product direction and boundary. The detailed,
testable behavior belongs in [`SPEC.md`](SPEC.md).

## Design principles

### Separate orchestration from device access

The host owns configuration, retries, recording, model integration, and
session orchestration. A backend owns device communication and implements the
common backend contract.

### Make the safe path the default

ADB is the default transport. The normal path communicates directly with the
device and does not require a phone-side network server, listening socket, or
ADB port forwarding.

### Keep the backend boundary small

ADB is the first-class transport. Custom backends may provide the same health,
capability, action, screenshot, UI-dump, and package/activity inspection
operations without changing the host domain types.

Remote ADB is an explicit opt-in deployment mode. It must not change the
local, ADB-first default or silently expose a device beyond the user's network
authorization.

### Preserve evidence and coordinates

Screenshots, UI dumps, action results, and run records should remain inspectable
after a test. OCR results must retain screen-space bounding boxes so a decision
provider can act on recognized controls without asking a model to guess their
locations again.

### Keep model assistance optional

The device-control foundation must remain useful without optional OCR or LLM
packages. Model providers are replaceable and must not weaken validation,
error reporting, or authorization boundaries.

## Current product boundary

The current foundation includes:

- a Python 3.10+ host runtime with configuration, sessions, retries, recording,
  protocol types, and typed backend errors;
- a direct ADB backend for health checks, capabilities, click/swipe/text/key
  actions, screenshots, UIAutomator dumps, installed package/Activity
  inspection, and explicit app/Activity launches;
- an optional rooted `nier-uinput` helper for persistent virtual touch input,
  with an Android shell-input fallback;
- an optional Android IME text backend for Unicode/Chinese `InputText` actions,
  while retaining shell input as the default;
- OCR, deterministic text-match decisions, TypeSafe SysOne `choice`, `noul`,
  and `score` decisions (including bounded UI widget-selection chains), provider
  routing, and an OpenAI-compatible text/vision/tool-call adapter;
- optional OpenCV screenshot-template matching and OCR fuzzy text locating,
  both returning screen-space matches that support explicit click, long-press,
  and directional swipe gestures with bounded, opt-out human-like jitter;
- a unified `Device.llm()` goal flow that uses the configured LLM as the
  primary planner, re-observes after each validated tool action, and accepts
  optional typed SysOne advice without letting SysOne failures block execution;
- a SysOne-first goal API for callers that need finite, host-validated UI/OCR
  candidates, with bounded LLM recovery subgoals;
- an LSPosed-backed `nier intent-hook` CLI subcommand that captures
  app-originated Activity Intents and prints reusable Nier Python launch code,
  plus CLI commands for screenshots, UI dumps, read-only locating, and ADB
  passthrough.

The following are intentionally outside the completed foundation:

- automatic retries of failed device actions; failed controls are excluded from
  subsequent recovery candidates;
- continuous post-action verification;
- autonomous WebView interaction beyond DOM extraction; the optional root
  Frida hook, LSPosed module, and cooperative non-root integration enable
  WebView DevTools DOM dumps. Root mode also has an explicit, best-effort
  configuration for bypassing common application-owned Back callbacks, while
  richer CDP actions remain a future extension.

These are future extensions, not reasons to change the default ADB topology.

In the explicit SysOne-first goal flow, recovery may generate any number of
subgoals by default, with each subgoal restricted to safe controls and bounded
to three actions and thirty seconds. The host executes only a current candidate
from the safe-control allowlist. Callers can cap the number of assists or set
an overall goal deadline.

## Documentation map

- `README.md` explains installation and first use.
- `SPEC.md` defines the runtime contracts and verification baseline.
- `AGENTS.md` defines the change workflow for agents and contributors.
- `docs/README.md` indexes the feature-oriented Python API documentation.
- `backend/` contains component-specific build instructions.
