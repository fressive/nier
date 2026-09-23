# Remote ADB

Nier supports Android devices exposed through ADB over TCP and ADB servers
running on another host. Remote mode is opt-in; the normal local ADB path is
unchanged.

## ADB-over-TCP device

Set the remote device endpoint in `config/nier.yaml`:

```yaml
device:
  serial: null
  remote_host: 192.0.2.10
  remote_port: 5555
  auto_connect: true
  adb_server_host: null
  adb_server_port: 5037
```

With `auto_connect: true`, Nier runs this once before the first ADB command:

```bash
adb connect 192.0.2.10:5555
```

All subsequent commands target `192.0.2.10:5555`. Set `auto_connect: false` if
the endpoint is already connected and managed externally:

```bash
adb connect 192.0.2.10:5555
```

`device.serial` and `device.remote_host` cannot be set together. For Android
Wireless Debugging, pair the device first with `adb pair`; use the connection
endpoint, not the pairing endpoint, as `remote_host`/`remote_port`.

## Remote ADB server

If the ADB server itself runs on another host, configure it separately:

```yaml
device:
  serial: 192.0.2.10:5555
  adb_server_host: 192.0.2.20
  adb_server_port: 5038
```

Nier then invokes commands through:

```text
adb -H 192.0.2.20 -P 5038 -s 192.0.2.10:5555 ...
```

`adb_server_host`/`adb_server_port` can also be combined with `remote_host` if
the remote ADB server should perform the `adb connect` operation.

## Python usage

For normal scripts, pass the endpoint directly:

```python
from nier import connect


with connect(remote="192.0.2.10:5555") as phone:
    print(phone.health())
```

A separately hosted ADB server can also be selected without building config
objects:

```python
with connect(
    remote="192.0.2.10:5555", adb_server="192.0.2.20:5038"
) as phone:
    print(phone.capabilities())
```

For backend integrations, construct `DeviceConfig` directly:

```python
from nier.backends.adb import AdbBackend
from nier.config import DeviceConfig
from nier.session import DeviceSession


config = DeviceConfig(
    remote_host="192.0.2.10",
    remote_port=5555,
    auto_connect=True,
)
session = DeviceSession(AdbBackend(config))
try:
    print(session.health())
finally:
    session.close()
```

## Security

ADB-over-TCP may provide powerful device access and is not suitable for an
untrusted network. Use authenticated/pairing-capable Android Wireless
Debugging where available, restrict network exposure, and connect only to
devices you are authorized to control.
