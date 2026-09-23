"""Find a visible UI label, open it, and submit a small search flow."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
SEARCH_LABEL = re.compile(r"^搜索$")  # Change this label for the application under test.
SEARCH_TEXT = "nier"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm that this example may tap and submit text on the device",
    )
    args = parser.parse_args(argv)
    if not args.confirm:
        parser.error("device actions require --confirm")

    with connect(CONFIG) as phone:
        phone.tap_label(SEARCH_LABEL)
        phone.text(SEARCH_TEXT)
        phone.enter()
        phone.save_run("search-flow.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
