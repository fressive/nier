# Applications and Activities

The public `Device` API can inspect the packages and Activities visible to an
authorized Android shell session:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    packages = phone.list_apps()
    print(f"Installed packages ({len(packages)}):")
    for package in packages:
        print(f"  - {package}")

    activities = phone.list_app_activities("com.example.authorized.app")
    print(f"Activities in com.example.authorized.app ({len(activities)}):")
    for activity in activities:
        print(f"  - {activity}")
```

`list_apps()` returns package names such as `com.android.settings`.
`list_app_activities(package)` returns fully qualified Activity class names such
as `com.example.authorized.app.MainActivity`. The queries are read-only and do
not launch an application or change device state. `list_app()` and
`list_app_activity()` are compatibility aliases.

To launch an application through its launcher Activity, or jump directly to a
declared Activity:

```python
with connect("config/nier.yaml") as phone:
    result = phone.open_app("com.example.authorized.app")
    print(f"App launch: {'succeeded' if result.success else 'failed'}")
    if result.message:
        print(f"Details: {result.message}")

    # Stop the process, clear the Activity task, then launch the app fresh.
    # This does not clear the app's stored data.
    result = phone.open_app("com.example.authorized.app", restart=True)

    result = phone.start_activity(
        "com.example.authorized.app",
        ".SettingsActivity",
    )
    print(f"Activity launch: {'succeeded' if result.success else 'failed'}")
    if result.message:
        print(f"Details: {result.message}")
```

`start_activity()` accepts a short class name (`SettingsActivity`), a relative
class name (`.SettingsActivity`), a fully qualified class name, or a
`package/class` component. The host normalizes the target and rejects an
Activity from another package before sending it to the device. The aliases
`launch_app()` and `open_activity()` are also available.

Opening an app and starting an Activity change device state. They are sent
once and are never automatically retried, because repeating a launch after a
lost response could produce an unintended navigation. By default,
`open_app(package)` launches the app without stopping it first. Set
`restart=True` to run Android `am force-stop`, clear the app's Activity task,
and start the launcher Activity fresh. It preserves the app's stored data.
`launch_app()` accepts the same option as an alias. The `phone.llm()` agent
also exposes this option to its `open_app` tool and uses it only when the goal
explicitly asks to restart the app.

To relaunch an Intent captured by `nier intent-hook`, pass its printed mapping
to `start_intent()`:

```python
from nier import connect


captured_intent = {
    "component": {
        "package": "com.example.authorized.app",
        "class": "com.example.authorized.app.DetailActivity",
    },
    "action": "com.example.OPEN_DETAIL",
    "data": None,
    "type": None,
    "package": None,
    "flags": 268435456,
    "categories": [],
    "extras": {"item_id": {"type": "int", "value": 42}},
}

with connect("config/nier.yaml") as phone:
    result = phone.start_intent(captured_intent)
    print("Activity launch:", "succeeded" if result.success else "failed")
```

The `intent-hook` CLI prints this Python form after each capture. The ADB
backend preserves the captured fields and supports null, string, boolean, int,
long, float, URI, component, string-array, int-array, long-array, and float-array
extras when Android's `am start` supports them. It rejects unsupported,
truncated, or unavailable extras before sending a command; the generated snippet
omits those values and includes TODO comments. Review the comments before using
the snippet. Intents with unsupported Parcelable or Serializable values may
need app-specific reconstruction. Android encodes string arrays as
comma-separated values, so Nier rejects items that are empty or contain commas.
The quoted ADB command is limited to 64 KiB; trim extras if a large Intent
exceeds that limit. A launch is a device action and is never retried.

The default ADB backend implements these calls with `pm list packages` and
`dumpsys package <package>`. No OCR, LLM, root, or other optional dependency is
needed. A configured remote ADB target uses the same commands through the
authorized ADB connection; launches use Android's `am start` command.

Use these APIs only with devices and applications you are authorized to inspect
and control.
An unavailable device or failed backend request raises `BackendError` (or its
`BackendUnavailable` subclass); an invalid package name raises `ValueError`.
An invalid Activity target, malformed Intent, unsupported or incomplete extra,
or oversized launch command also raises `ValueError`.
The lower-level `DeviceSession` treats both listing methods as read operations
and may retry transient backend failures. Device actions such as taps, text
input, key events, and app/Activity launches are never retried automatically.
