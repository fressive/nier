# Activity Intent hook

`nier intent-hook` listens for Activity launch Intents captured by Nier's
LSPosed module. For each launch it prints the captured fields and reusable
Python code that calls `phone.start_intent()`.

## Requirements and setup

The authorized Android device must have LSPosed installed. Build and install
the Nier Android APK, then enable **Nier Backend** in LSPosed Manager and add
the app you want to inspect to the module's scope. Apply any reboot request
shown by LSPosed, then start the target app again.

```bash
cd backend/nier-android
gradle :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Do not add packages to the module scope unless you are authorized to inspect
them. Captured extras can contain credentials or other private data; the CLI
prints captures to the terminal and does not save them. The Base64 event
payloads also remain temporarily in Android's logcat ring buffer until rotated.

## Capture launches

Restart the app and stop after the first app-originated Activity launch:

```bash
nier --config config/nier.yaml intent-hook \
  --package com.example.authorized.app --spawn --once
```

By default `--spawn` launches the package's launcher Activity. Use `--activity`
to launch a specific component:

```bash
nier --config config/nier.yaml intent-hook \
  --package com.example.authorized.app \
  --spawn --activity com.example.authorized.app/.DetailActivity --once
```

The launcher or explicit Activity selected with `--spawn` is only used to start
the app. Its incoming launch Intent is issued by Android shell and is outside
the target app's hook scope; captures are app-originated Activity launches
made afterward.

For an already running process, use `--attach`. The LSPosed module must have
been enabled for that package when its current process started:

```bash
nier --config config/nier.yaml intent-hook \
  --package com.example.authorized.app --attach
```

The package defaults to `hook.target_package`. If neither `--spawn` nor
`--attach` is supplied, behavior follows `hook.spawn`, which defaults to false.
Without `--once`, the command listens until Ctrl-C. The configured ADB
serial/server is used for logcat and launch commands. No Frida package,
`frida-server`, port forwarding, or device-side Nier server is used by this
command.

The module observes successful app-process Activity launches through Android
`Instrumentation`, `ContextImpl`, and the framework ActivityTaskManager binder
proxy. An `ActivityThread` delivery hook provides a fallback only when no
launch-side hook method is available. It skips the process's first Activity so
the initial launcher Intent is not reported. Captures include the component,
action, data URI, MIME type, package, flags, categories, and bounded extras.
The CLI matches events by their app process as well as their loaded package,
which handles Android WebView code running inside the target app process. It
prints the installed hook count by source after LSPosed loads the module.

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
`am start` interface cannot reconstruct every Java value type. Unsupported or
truncated extras and fields are omitted from generated code and called out in
TODO comments. Review those comments before running the snippet. Android
encodes string arrays as comma-separated values, so string-array items that
are empty or contain commas are also omitted. Direct `phone.start_intent()`
calls reject unsupported, truncated, or unavailable extras before sending a
device command.
A quoted ADB launch command is limited to 64 KiB.

When the LSPosed module can read the target Activity's manifest entry, captured
component metadata includes its `exported` value. Generated code uses
`phone.start_intent(intent, root=True)` for a non-exported Activity; this
requires a rooted device with working `su` and launches the Activity as root.
For a manually constructed Intent mapping, pass `root=True` explicitly when
Android reports that the Activity is not exported. Nier sends that launch once
and does not retry it.

Strings are limited to 4096 characters, captures include up to 100 extras and
64 array values, and each event is bounded before it is split into logcat
records. If Android still holds the extras in a parcelled Bundle, Nier leaves
them unread and marks them unavailable. `phone.start_intent()` changes device
state and is sent once; Nier does not automatically retry it.

The capture itself only reads app-process Intent data. `--spawn` force-stops
and launches the selected app so the LSPosed module is active from process
start.
