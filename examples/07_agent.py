"""Run a real UI goal with an LLM and Jev."""

from __future__ import annotations

import json
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
GOAL = "打开设置，进入关于手机"


with connect(CONFIG) as phone:
    result = phone.run(
        GOAL,
        max_steps=8,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    phone.save_run("agent-run.json")
