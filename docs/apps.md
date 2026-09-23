# Applications and Activities

The public `Device` API can inspect the packages and Activities visible to an
authorized Android shell session:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    packages = phone.list_apps()
    print(packages)

    activities = phone.list_app_activities("com.example.authorized.app")
    print(activities)
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
    print(result.success, result.message)

    result = phone.start_activity(
        "com.example.authorized.app",
        ".SettingsActivity",
    )
    print(result.success, result.message)
```

`start_activity()` accepts a short class name (`SettingsActivity`), a relative
class name (`.SettingsActivity`), a fully qualified class name, or a
`package/class` component. The host normalizes the target and rejects an
Activity from another package before sending it to the device. The aliases
`launch_app()` and `open_activity()` are also available.

Opening an app and starting an Activity change device state. They are sent
once and are never automatically retried, because repeating a launch after a
lost response could produce an unintended navigation.

The default ADB backend implements these calls with `pm list packages` and
`dumpsys package <package>`. No OCR, LLM, root, or other optional dependency is
needed. A configured remote ADB target uses the same commands through the
authorized ADB connection; launches use Android's `am start` command.

Use these APIs only with devices and applications you are authorized to inspect
and control.
An unavailable device or failed backend request raises `BackendError` (or its
`BackendUnavailable` subclass); an invalid package name raises `ValueError`.
An invalid Activity target also raises `ValueError`.
The lower-level `DeviceSession` treats both listing methods as read operations
and may retry transient backend failures. Device actions such as taps, text
input, key events, and app/Activity launches are never retried automatically.
