"""Find a visible UI label, open it, and submit a small search flow."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
SEARCH_LABEL = re.compile(r"^搜索*$")  # Change this label for the application under test.
SEARCH_TEXT = "nier"

with connect(CONFIG) as phone:
    phone.tap_label(SEARCH_LABEL)
    phone.text(SEARCH_TEXT)
    phone.enter()
    phone.save_run("search-flow.json")
        
