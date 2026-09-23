"""Run the same script against an authorized Android device over TCP ADB."""

from __future__ import annotations

from nier import connect

REMOTE_DEVICE = ("192.168.1.20", 5555)


def main() -> int:
    with connect(remote=REMOTE_DEVICE, retries=1) as phone:
        capabilities = phone.capabilities()
        print(f"Remote device: {capabilities.model} ({capabilities.device_id})")
        print(f"Device status: {'ready' if phone.health() else 'not ready'}")
        phone.screenshot("artifacts/remote-screen.png")
        phone.save_run("remote-session.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
