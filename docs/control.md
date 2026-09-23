# Device control API

Use direct methods for ordinary scripts. Absolute coordinates are screen
pixels; normalized coordinates range from `0.0` to `1.0`.

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    phone.tap(540, 960)
    phone.tap_label("搜索")
    phone.swipe(100, 300, 300, 500, 700, 500, duration_ms=600)
    phone.swipe((0.25, 0.5), (0.75, 0.5), normalized=True)
    phone.text("hello world")
    phone.back()
    phone.home()
    phone.enter()
    phone.key("volume_down")
    print(phone.current_activity())
```

`tap_label` captures a fresh UIAutomator dump, finds the first matching node
with bounds in document order, and taps its center. It matches node text or
content descriptions. A plain string is an exact match. Pass a compiled Python
regex for regex search:

```python
import re

from nier import connect


with connect("config/nier.yaml") as phone:
    phone.tap_label(re.compile(r"^搜索$"))
```

It uses only Python's standard-library `re` module. If no node matches or no
matching node has screen bounds, it raises `UiElementNotFound` from
`nier.errors`. Use it only with a device and app you are authorized to test.
The tap is a device action and is never retried automatically.

Action validation happens during construction:

- a swipe needs at least two points and a positive duration;
- a click duration may be zero but cannot be negative;
- normalized coordinates must be in `[0, 1]`;
- unsupported key codes are rejected.

Actions are deliberately not retried automatically. Repeating a tap, text input,
or key event after a lost reply can mutate the application twice.

### Applications that consume Back

`phone.back()` sends the normal Back action by default. For an authorized rooted
target that consumes Back in Java callbacks, enable the opt-in Frida policy:

```yaml
hook:
  mode: root
  target_package: com.example.authorized.app
  spawn: true
  force_system_back: true
```

This is best-effort and covers common platform/AndroidX callbacks plus loaded
and subsequently loaded legacy activity handlers. It is disabled by default,
unavailable in non-root mode, and does not guarantee behavior for native or
application-specific navigation code. See the [Frida guide](webview-devtools.md)
for setup.

For backend or protocol integrations, the equivalent immutable `Click`,
`Swipe`, `InputText`, and `Key` types remain in `nier.protocol` and can be sent
with `DeviceSession.execute`.

## Text input backend

`InputText` uses `adb shell input text` by default. For reliable Unicode and
Chinese input, install the optional Android module and configure:

```yaml
input_text:
  mode: ime
  auto_enable: true
  restore_previous: true
```

The IME backend sends Base64-encoded text through an ADB `content call` to the
Nier input method. It requires a focused editable field and a current
`InputConnection`; otherwise the action fails with a backend error. It works
in both root and non-root modes and does not start a network service.
`auto_enable` is opt-in because switching the device's current IME changes
device state; the previous IME is restored on session close when possible. On
a rooted device, `auto_enable` uses `su` when Android rejects IME management
from the normal shell UID. On a non-root device, the Nier IME must already be
selected.
