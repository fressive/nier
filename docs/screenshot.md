# Screenshot API

Pass a path to capture and save in one call. The extension selects PNG or JPEG:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    screenshot = phone.screenshot(
        "artifacts/screen.jpg",
        quality=85,
        max_width=1280,
        max_height=1280,
    )
    print(screenshot.width, screenshot.height, screenshot.sha256)
```

Without a path, the encoded bytes are returned in the same result:

```python
from nier import connect


with connect("config/nier.yaml") as phone:
    image = phone.screenshot(format="png")
    print(len(image.data))
```

OCR is available directly on the screenshot. It uses the first configured
provider (or the singular `models.ocr` section) and keeps each span's screen
coordinates:

```python
with connect("config/nier.yaml") as phone:
    spans = phone.screenshot().ocr()
    for span in spans:
        print(span.text, span.box.center)
```

The OCR provider is created lazily and cached by `phone`; scripts do not need
to construct or close a provider themselves.

`Screenshot` contains:

- `data`: encoded image bytes;
- `format`: `ImageFormat.PNG` or `ImageFormat.JPEG`;
- `width` and `height`: returned dimensions;
- `sha256`: lowercase SHA-256 of `data`.
- `ocr()`: recognize the image with the connection's configured OCR provider.

Transport adapters can still call
`DeviceSession.screenshot(ScreenshotRequest(...))`; ordinary scripts do not
need a request object.

An unrestricted PNG is returned without host-side re-encoding when possible.
JPEG conversion and resizing are handled by Pillow. A single call must not mix
a request object with keyword options.
