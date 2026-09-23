"""Check an authorized device before starting a test run."""

from __future__ import annotations

from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
RUN_RECORD = "basic-session.json"


with connect(CONFIG) as phone:
    if not phone.health():
        raise RuntimeError("the device backend is not ready")
    print("device is ready")
    print(phone.capabilities())
    phone.save_run(RUN_RECORD)
