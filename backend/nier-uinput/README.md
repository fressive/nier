# nier-uinput

Root-only virtual touch backend for Android/Linux devices. It creates a
single-slot multitouch Protocol-B device through `/dev/uinput` and emits
click/swipe events with deterministic screen-coordinate validation. Nier's
default host backend starts this executable in `serve` mode once per ADB
backend session and sends commands over stdin/stdout; no phone-side network
server is required.

## Build

```bash
cmake -S backend/nier-uinput -B /tmp/nier-uinput-build -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/nier-uinput-build
ctest --test-dir /tmp/nier-uinput-build --output-on-failure
```

## Probe and operate

The target device must expose `/dev/uinput` and the process must run as root
or have equivalent access to that device:

```bash
/tmp/nier-uinput-build/nier-uinput probe
sudo /tmp/nier-uinput-build/nier-uinput \
  --width 1080 --height 1920 click 540 960 --duration-ms 80
sudo /tmp/nier-uinput-build/nier-uinput \
  --width 1080 --height 1920 --duration-ms 400 \
  swipe 100 100 300 300 600 500

# Persistent session protocol (stdin/stdout, no network socket):
sudo /tmp/nier-uinput-build/nier-uinput \
  --width 1080 --height 1920 serve
# READY
# CLICK 540 960 80
# OK
# CLOSE
# OK
```

The device is destroyed automatically on normal exit and best-effort on
signal/process teardown. The ADB backend creates it lazily and reuses it for
the backend session, then closes it when the backend closes. The process does
not listen on a network socket or require a long-running Android service.
