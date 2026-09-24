# OCR text matching

`phone.locate_text()` recognizes text in one fresh screenshot with the
connection's configured OCR provider, then fuzzy-matches each recognized text
span against the requested label. It returns the best match as the same
`ImageMatch` type used by `phone.locate_icon()`.

OCR must be configured under `models.ocr` or `models.ocr_providers`; providers
are loaded lazily. Local PaddleOCR needs the optional `models` dependencies,
while hosted OCR needs its configured client and credentials. See the
[model provider guide](models.md) for installation and configuration details.

```python
import argparse

from nier import connect


parser = argparse.ArgumentParser()
parser.add_argument(
    "--click",
    action="store_true",
    help="explicitly tap the center of a text match",
)
args = parser.parse_args()

with connect("config/nier.yaml") as phone:
    match = phone.locate_text("进入设置", min_score=0.6)
    if match is None:
        print("Text not found")
    else:
        print("bounds:", match.bounds)
        print("center:", match.center)
        print("similarity:", match.score)
        if args.click:
            match.click()
```

Text is normalized with Unicode NFKC, case-folding, and whitespace
normalization. Similarity is computed with Python's `SequenceMatcher` and is a
value from `0` to `1`, not a probability. The default `min_score` is `0.6`;
raise it to reduce false positives or lower it to accept noisier OCR. The best
OCR span below the threshold returns `None`. Empty text and invalid thresholds
raise `ValueError`; missing or invalid OCR configuration raises
`ConfigurationError`, and provider failures surface as `ModelError`.

`ImageMatch` exposes integer screen-pixel bounds and the match center. A match
returned by `phone.locate_text()` is bound to that `phone`, so calling
`match.click()` explicitly taps its center once. Matching only reads the
screenshot; the screenshot read may be retried by `DeviceSession`, but OCR
matching is not a device action. The click is a device action and is never
retried automatically. Coordinates are not revalidated after the match, so
click promptly if the screen could change.

Run against an authorized device and app. A call to `locate_text()` requires a
working configured OCR provider; no OpenCV dependency is needed for text
matching.
