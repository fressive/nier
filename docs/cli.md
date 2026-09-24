# Command-line device tools

Place global options such as `--config` and `-v` before the subcommand. Device
commands use the selected Nier configuration and its authorized ADB target.

## Screenshot

Capture to the configured `runtime.output_dir` (default `artifacts`) or choose
an output path. PNG is the default; the output suffix selects JPEG when no
format is supplied.

```bash
nier --config config/nier.yaml screenshot
nier --config config/nier.yaml screenshot \
  --output artifacts/current.jpg --quality 85 --max-width 1280
```

`--format` accepts `png`, `jpg`, or `jpeg`. JPEG `--quality` must be from 1 to
100. `--max-width` and `--max-height` are optional pixel limits; zero means no
limit.

## OCR

`ocr` recognizes text in one fresh screenshot with the configured OCR provider.
It prints each span's text, confidence, and screen-pixel bounds without issuing
device actions. A configured provider under `models.ocr` or
`models.ocr_providers` is required. Local PaddleOCR requires the optional
`models` extra; hosted providers may require a credential environment variable.

```bash
nier --config config/nier.yaml ocr
```

If no text is recognized, the command prints `No text recognized.` and exits
successfully. Missing OCR configuration or provider failures are reported as
errors without substituting another provider. Screenshot reads may follow the
session read retry policy; OCR is not retried automatically.

## UI dump

`uidump` saves XML by default. `dump-ui` remains an alias for compatibility.
The command also prints the parsed hierarchy to stdout using the built-in
readable tree formatter, regardless of whether the saved file is XML or JSON.

```bash
nier --config config/nier.yaml uidump --output artifacts/ui.xml
nier --config config/nier.yaml uidump --format json --output artifacts/ui.json
```

JSON contains the parsed tree, source, completeness, and warnings. Add
`--include-raw` to include the original XML or HTML string. `--no-webview`
skips the WebView DOM path, and `--include-invisible` requests invisible nodes
where the selected dump source supports them.

## Locate text and icons

Text locating uses the configured OCR provider. Local PaddleOCR requires the
optional `models` extra; hosted OCR requires a configured provider and its
credential environment variable. Icon locating uses an image template and
requires the optional OpenCV dependency from `nier[vision]`.

```bash
nier --config config/nier.yaml locate text "进入设置" --min-score 0.7
nier --config config/nier.yaml locate icon artifacts/settings-icon.png \
  --min-score 0.88 --region 0 100 1080 1600
```

Both commands report the best match's screen-pixel bounds, center, and score.
They exit with status 1 when no match meets the threshold. They only read the
screen unless `--tap` is provided. `--tap-duration` sets the explicit click
duration in milliseconds:

```bash
nier --config config/nier.yaml locate text "进入设置" --tap
```

A screenshot read may be retried after a transient backend failure. OCR and
matching do not issue device actions. A requested tap is one device action and
is never retried automatically. Coordinates are not revalidated after the
match, so tap promptly if the screen may change. Run these commands only on an
authorized device and app.

## ADB passthrough

`nier adb` forwards an arbitrary ADB command to the configured ADB executable.
Unless the arguments contain an explicit ADB device selector, device-scoped
commands use the configured device. Explicit `-s`, `-t`, `-d`, or `-e`
selectors take precedence. The configured ADB server is used unless the command
supplies its own server options. A configured remote target is auto-connected
before device-scoped commands that use it by default. Server-management
commands such as `devices`, `connect`, and `kill-server` are passed through
without selecting the configured device.

Standard input, output, and error are inherited directly by ADB. This supports
interactive commands, long-running output, and binary streams. The CLI returns
ADB's exit status and suppresses Nier logs for this command so they cannot
corrupt standard output.

```bash
nier --config config/nier.yaml adb shell dumpsys activity activities
nier --config config/nier.yaml adb exec-out screencap -p > artifacts/raw.png
nier --config config/nier.yaml adb logcat
```

Expected device and configuration failures use Nier's typed errors. ADB
passthrough returns ADB's nonzero exit status directly. Device actions are
never retried automatically.
