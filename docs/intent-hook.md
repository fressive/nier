# Activity Intent hook

The root-only `nier intent-hook` command observes Activity launch Intents made
by an authorized app process. For each launch it prints the captured fields
and a reusable Python snippet that calls Nier's `phone.start_intent()` API.

## Requirements and configuration

Install the optional Frida host dependency and configure a rooted ADB device
with a matching root-capable `frida-server`:

```bash
python -m pip install -e '.[hook]'
```

```yaml
hook:
  mode: root
  target_package: com.example.authorized.app
  spawn: true
  frida_server_path: /data/local/tmp/frida-server
  auto_start_frida_server: false
  timeout_seconds: 10
```

When `auto_start_frida_server` is false, start the configured server on the
device before running the command. Set it to true to let Nier start it through
root ADB. Use the hook only on apps and devices you are authorized to inspect;
captured extras can contain credentials or other private data.

## Capture launches

Spawn the app with the hook installed before it resumes, then stop after the
first captured launch:

```bash
nier --config config/nier.yaml intent-hook --spawn --once
```

For an already running process, attach instead:

```bash
nier --config config/nier.yaml intent-hook --attach
```

The package comes from `hook.target_package`, or can be supplied as
`--package com.example.authorized.app`. Without `--once`, the command keeps
listening until Ctrl-C. The default spawn/attach behavior comes from
`hook.spawn`. This command always uses root Frida; it rejects an explicit
`hook.mode: non-root` setting and never falls back to cooperative mode.

The hook captures app-process Java launches through Android
`Instrumentation` and `ContextImpl`. It reports the component, action, data
URI, MIME type, package, flags, categories, and supported extras. It does not
capture an incoming launch made by another process or infer the original
Intent that started the hooked process.

## Generated code and capture limits

Output includes JSON for the captured fields and a runnable Nier Python
snippet such as:

```python
from nier import connect

intent = {
    'component': {
        'package': 'com.example.authorized.app',
        'class': 'com.example.authorized.app.DetailActivity',
    },
    'action': 'com.example.OPEN_DETAIL',
    'data': None,
    'type': None,
    'package': None,
    'flags': 268435456,
    'categories': [],
    'extras': {'item_id': {'type': 'int', 'value': 42}},
}

with connect('config/nier.yaml') as phone:
    result = phone.start_intent(intent)
    print('Activity launch:', 'succeeded' if result.success else 'failed')
```

The generated snippet uses the `--config` path passed to the CLI. The ADB
backend restores the component, action, data URI, MIME type, package, flags,
categories, and these extras: null, string, boolean, int, long, float, URI,
component, string-array, int-array, long-array, and float-array. The Android
`am start` interface does not preserve every Java type. For example, byte,
short, char, double, boolean-array, and custom Parcelable extras cannot be
reconstructed exactly; those extras are omitted from the generated snippet and
reported in TODO comments. Truncated values are also omitted. Review the TODOs
before running the snippet. Android encodes string arrays as comma-separated
values, so string-array items that are empty or contain commas are also omitted.
Direct `phone.start_intent()` calls reject unsupported, truncated, or unavailable
extras before sending any device command. A quoted ADB launch command is limited
to 64 KiB; remove extras if a large captured Intent exceeds that limit.

Strings are limited to 4096 characters, captures include up to 100 extra keys
and 64 array values. If Android still holds the extras in a parcelled Bundle,
Nier leaves them unread and marks them unavailable. The hook command prints
results to the terminal and does not save captured Intents. Calling
`phone.start_intent()` launches an Activity and changes device state; it is
sent once and is never automatically retried.

The hook is read-only: it observes launches and does not call device action
APIs or retry an Activity launch. Missing Frida, an unrooted device, a missing
server, and attach/spawn failures are reported by the CLI.
