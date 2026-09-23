# AGENTS.md

This file is the working guide for agents and contributors. It describes how
to change the repository; it is not a replacement for the product intent or
the implementation specification.

## Read first

1. Read this file and the relevant component documentation.
2. Read [`INTENT.md`](INTENT.md) for product goals and non-goals.
3. Read [`SPEC.md`](SPEC.md) for normative runtime contracts.
4. Read the tests and the implementation before changing behavior.

The root documents apply to the whole repository. A component-level document,
such as [`backend/nier-uinput/INTENT.md`](backend/nier-uinput/INTENT.md), adds
detail for that component but must not silently contradict the root contract.

## Document roles

| Document | Role |
| --- | --- |
| `README.md` | User-facing overview and quick start |
| `INTENT.md` | Product purpose, design principles, scope, and non-goals |
| `SPEC.md` | Implementable contracts, invariants, API surface, and verification |
| `AGENTS.md` | Change workflow and repository conventions |
| `docs/README.md` | API documentation index |
| `docs/<feature>.md` | Hand-maintained feature guide with runnable examples |
| `docs/api-tutorial.md` | Compatibility entry point to the split API documentation |
| `examples/README.md` | Runnable feature examples and their prerequisites |
| `backend/**/README.md` | Component-specific usage and build instructions |

When documents disagree, use the user request first, then the normative rules
in `SPEC.md`, tests/current behavior, and finally explanatory text in
`INTENT.md` or `README.md`. Resolve a real conflict by updating the
implementation, tests, and the affected document together rather than hiding
the difference in prose.

## Repository rules

- Keep Python as the primary runtime language; use Kotlin/C++ only for the
  optional Android integrations and native input helper.
- Preserve the ADB-first default topology. It must not require a phone-side
  network server, listening socket, or port forwarding.
- Do not retry device actions automatically. Taps, text input, and key events
  can be non-idempotent; only read-style operations may use the retry policy in
  `SPEC.md`.
- Keep optional model dependencies optional. Import them lazily and keep the
  core runtime usable without PaddleOCR or an LLM SDK.
- Keep secrets in environment variables or local configuration. Do not add
  API keys, device identifiers, screenshots, generated artifacts, or build
  output to a change unless the user explicitly requests it.
- Use `jj` for repository status and diffs. Do not discard existing working
  copy changes or create a commit unless the task or user explicitly calls for
  it.

## API documentation and tutorial workflow

The Python signatures, type annotations, and docstrings under `src/nier/` are
the source for the host API. `src/nier/api.py` is the normal script-facing
entry point; session, protocol, and backend modules are lower-level extension
APIs.
`docs/README.md` indexes hand-maintained feature guides under `docs/`; these
guides are not generated output. `docs/api-tutorial.md` remains a compatibility
entry point. For the current repository, “API docs” means these maintained
guides plus the source docstrings; there is no generated API reference tree.

When a public API changes, the change MUST:

1. update the implementation docstring and type annotations;
2. update the relevant feature guide or add a new guide/example;
3. update focused tests for changed validation and behavior;
4. verify every example against the current import path and signature; and
5. update the relevant component README when a component interface changes.

Feature guides SHOULD prefer complete, copyable examples over lists of private
helpers. The relevant guide MUST explain device authorization, optional
dependencies, failure handling, and the fact that `DeviceSession` retries reads
but never retries device actions automatically.

If generated API reference pages are introduced later, they MUST be kept
separate from the tutorial, derive their Python reference from public
signatures/docstrings, and write only to a documented `docs/api/` output
location. Generated files MUST NOT be hand-edited; the exact generation command
and required dependencies MUST be documented in this file. The repository does
not currently require a docs-generation script. Adding one requires an explicit
task and must follow the rules above.

Examples under `examples/` are executable documentation. They MUST use the
public API, avoid credentials and hard-coded device identifiers, and avoid
contacting a device merely by being imported. Examples that mutate a device
MUST require an explicit confirmation flag or equivalent opt-in. When behavior
changes, update the matching example and run at least:

```bash
python -m compileall examples
PYTHONPATH=src python examples/04_custom_backend.py
PYTHONPATH=src python examples/05_model_decision.py
```

## Change workflow

1. Inspect the current implementation, tests, and working-copy status.
2. Make the smallest coherent change, including tests and documentation when
   a public contract changes.
3. Run focused tests first, then the full relevant test suite.
4. For backend or protocol changes, also run the C++ helper checks when the
   toolchain is available.
5. Review `jj diff` and `jj status`; verify that generated files, credentials,
   and unrelated user changes were not included.

Useful checks are:

```bash
python -m pytest
cmake -S backend/nier-uinput -B /tmp/nier-uinput-build
cmake --build /tmp/nier-uinput-build
ctest --test-dir /tmp/nier-uinput-build --output-on-failure
jj diff
jj status
```

The Android device smoke test requires an authorized, connected, and suitably
configured device; do not assume it is available in a normal development run.
