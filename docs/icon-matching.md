# Screenshot icon matching

`phone.locate_icon()` searches a fresh screenshot for a known image template.
It returns the best match rectangle and score without tapping the screen. This
is useful when an icon has no text label or accessible UI node.

Install the optional OpenCV dependency:

```bash
python -m pip install -e '.[vision]'
```

Crop a template from a screenshot of the target app and save it locally. For
best results, use the same device resolution, theme, and icon scale as the
screenshots you will search. Keep test screenshots and templates local rather
than adding device data to the repository. The crop should include enough
contrast and surrounding detail to distinguish the icon from the background.

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    match = phone.locate_icon(
        "artifacts/settings-icon.png",
        min_score=0.85,
    )
    if match is None:
        print("Icon not found with the configured threshold")
    else:
        print("bounds:", match.bounds)
        print("center:", match.center)
        print("matching score:", match.score)
        # Explicitly tap only when that is the intended action:
        # match.click()
```

The template can also be passed as encoded image bytes. `region=(x, y, width,
height)` optionally limits the search to a rectangle in the full screenshot;
returned coordinates remain screen-relative. `ImageMatch` exposes integer
`x`, `y`, `width`, and `height`, a `(left, top, right, bottom)` `bounds`, a
pixel-coordinate `center`, and the normalized OpenCV `score`. Matches returned
by `phone.locate_icon()` can be tapped with `match.click()`; this sends one
device action near the match center, within its bounds. The coordinates are
not revalidated, so use the match promptly if the screen may change.

Image matches also support an explicit long press or directional swipe:

```python
match.long_press(duration_ms=900)
match.swipe("left", distance=240, duration_ms=450)
```

The swipe direction can be `"up"`, `"down"`, `"left"`, or `"right"`. Gesture
methods add up to 2 pixels of human-like coordinate jitter by default; click
and long-press jitter stays inside the match bounds, and swipe paths receive
small random curvature on multipoint backends. The standard ADB shell fallback
uses jittered endpoints on a straight path. Pass `humanize=False` to disable
random offsets and curvature for one gesture; `jitter=0` has the same effect.
Pass a different `jitter=` value to adjust the maximum offset while
humanization is enabled.

`min_score` must be between `0` and `1` and defaults to `0.85`. It is a
similarity threshold, not a calibrated probability or a promised recognition
rate. Calibrate it against screenshots where the icon is both present and
absent. If matching does not meet the threshold, the method returns `None`;
invalid image bytes, thresholds, and regions raise `ValueError`. If OpenCV is
not installed, `VisionUnavailable` explains how to install the optional extra.

Run this only against an authorized device and app. `DeviceSession` may retry
the screenshot read after a transient backend failure; icon matching itself
does not issue a device action. Calls to `match.click()`, `match.long_press()`,
and `match.swipe()` are explicit actions and are never retried automatically.
For OCR-based text matching, see
[`text-matching.md`](text-matching.md).
