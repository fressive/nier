# Screenshot icon matching

`phone.locate_icon()` searches a fresh screenshot for a known image template.
It returns the best match rectangle and score; it never taps the screen. This
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
```

The template can also be passed as encoded image bytes. `region=(x, y, width,
height)` optionally limits the search to a rectangle in the full screenshot;
returned coordinates remain screen-relative. `ImageMatch` exposes integer
`x`, `y`, `width`, and `height`, a `(left, top, right, bottom)` `bounds`, a
pixel-coordinate `center`, and the normalized OpenCV `score`.

`min_score` must be between `0` and `1` and defaults to `0.85`. It is a
similarity threshold, not a calibrated probability or a promised recognition
rate. Calibrate it against screenshots where the icon is both present and
absent. If matching does not meet the threshold, the method returns `None`;
invalid image bytes, thresholds, and regions raise `ValueError`. If OpenCV is
not installed, `VisionUnavailable` explains how to install the optional extra.

Run this only against an authorized device and app. `DeviceSession` may retry
the screenshot read after a transient backend failure; icon matching itself
does not issue a device action. If you later use the returned center in
`phone.tap(*match.center)`, that tap is an action and is never retried
automatically.
