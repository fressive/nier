
# Nier-uinput

`nier-uinput` is the rooted-device touch injection implementation used by
Nier's default ADB backend. It is a standalone executable with both direct
one-shot commands and a persistent stdin/stdout session mode; it is not a
phone-side network server.

## Requirements

- Android/Linux target with `/dev/uinput`;
- root privileges or equivalent access to the uinput device;
- valid positive screen width and height;
- screen-coordinate points within the configured display bounds.

## Input behavior

The helper creates a virtual single-slot multitouch Protocol-B device. It
supports `probe`, `click`, and multi-point `swipe` commands. In `serve` mode it
also accepts serialized click/swipe commands over stdin. After `UI_DEV_CREATE`,
it waits for Android InputReader to register the device before emitting events,
then destroys the device on `CLOSE` or EOF.

Swipe segments are linearly interpolated with a maximum dominant-axis spacing
of 16 pixels. The requested duration is distributed over the interpolated
samples, so sparse paths remain continuous to drawing applications while
keeping the original gesture timing.

## Host integration

The host invokes the executable through a rooted ADB shell, normally at
`/data/local/tmp/nier-uinput`, with `/dev/uinput` as the device path. One
virtual device is created lazily for each host backend session. If probing
fails, the host backend falls back to Android's `input` command.
