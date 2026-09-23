"""Check an authorized device before starting a test run."""

from __future__ import annotations

from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
RUN_RECORD = "basic-session.json"


with connect(CONFIG) as phone:
    if not phone.health():
        raise RuntimeError("the device backend is not ready")
    capabilities = phone.capabilities()
    print("Device status: ready")
    print(f"Device: {capabilities.model} ({capabilities.device_id})")
    print(
        f"Screen: {capabilities.screen_width} × {capabilities.screen_height}; "
        f"root access: {'yes' if capabilities.is_rooted else 'no'}"
    )
    print(f"Available actions: {', '.join(capabilities.action_names)}")
    phone.save_run(RUN_RECORD)
