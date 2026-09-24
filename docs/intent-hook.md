# Activity Intent hook

The root-only `nier intent-hook` command observes Activity launch Intents made
by an authorized app process. For each launch it prints the captured fields
and a reusable Kotlin helper by default, or Java with `--format java`.

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
nier --config config/nier.yaml intent-hook --attach --format java
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

Output includes JSON for the captured fields and a helper such as:

```kotlin
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.net.Uri

fun launchCapturedIntent(activity: Activity) {
    val intent = Intent()
    intent.setComponent(ComponentName("com.example.authorized.app", "com.example.authorized.app.DetailActivity"))
    intent.setAction("com.example.OPEN_DETAIL")
    intent.putExtra("item_id", 42)
    activity.startActivity(intent)
}
```

Primitive and string extras preserve their Java types, including primitive
arrays. Strings are limited to 4096 characters, captures include up to 100
extra keys and 64 array values. Parcelable, custom Serializable, and other
unsupported values are shown by type; the generated helper includes TODO
comments for them because Nier does not invoke arbitrary app serialization
code. If Android still holds the extras in a parcelled Bundle, Nier leaves
them unread and marks them unavailable. The command prints results to the
terminal and does not save captured Intents.

The hook is read-only: it observes launches and does not call device action
APIs or retry an Activity launch. Missing Frida, an unrooted device, a missing
server, and attach/spawn failures are reported by the CLI.
