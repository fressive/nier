"""Find a visible UI label, open it, and submit a small search flow."""

from __future__ import annotations

from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
SEARCH_LABEL = "搜索"  # Change this label for the application under test.
SEARCH_TEXT = "nier"


def tap_label(phone, label: str) -> None:
    node = phone.parse_uidump(prefer_webview=False).find(text=label)
    if node is None or node.center is None:
        raise RuntimeError(f"could not find a UI node with text {label!r}")
    phone.tap(*node.center)


def main() -> int:
    with connect(CONFIG) as phone:
        tap_label(phone, SEARCH_LABEL)
        phone.text(SEARCH_TEXT)
        phone.enter()
        phone.save_run("search-flow.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
