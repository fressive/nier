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
- OCR, deterministic text-match decisions, TypeSafe Jev typed decisions,
  provider routing, and an OpenAI-compatible text/vision/tool-call adapter;
- a unified `Device.run()` goal flow that uses TypeSafe Jev as the primary
  decision-maker when configured, selecting only host-validated actions and
  optionally asking an LLM to generate and execute bounded recovery subgoals
  by selecting only safe, host-validated controls;
- an explicit LLM-first Agent API for goals that need free-form text or actions
  outside Jev's bounded candidate set, with validated native tool calls.

The following are intentionally outside the completed foundation:

- automatic retries of failed device actions; failed controls are excluded from
  subsequent recovery candidates;
- continuous post-action verification;
- autonomous WebView interaction beyond DOM extraction; the optional root
  Frida hook and cooperative non-root integration now enable WebView DevTools
  DOM dumps. Root mode also has an explicit, best-effort configuration for
  bypassing common application-owned Back callbacks, while richer CDP actions
  remain a future extension.

These are future extensions, not reasons to change the default ADB topology.

Jev recovery may generate any number of recovery subgoals by default, with each
subgoal still restricted to safe controls and bounded to three actions and
thirty seconds. The LLM cannot provide arbitrary coordinates, text, app
launches, or task operations; the host executes only a current candidate from
the safe-control allowlist. Callers can cap the number of LLM assists or set
an overall goal deadline.

## Documentation map

- `README.md` explains installation and first use.
- `SPEC.md` defines the runtime contracts and verification baseline.
- `AGENTS.md` defines the change workflow for agents and contributors.
- `docs/README.md` indexes the feature-oriented Python API documentation.
- `backend/` contains component-specific build instructions.
