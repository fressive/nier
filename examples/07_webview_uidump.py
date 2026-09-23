"""Capture a UI dump, preferring the current WebView DOM.

For WebView DOM extraction, set ``hook.target_package`` in
``config/nier.yaml`` and make WebView debugging available to Nier. Root mode
can enable it through the optional Frida hook; a cooperating non-root app can
call ``WebViewDebugController.enable()``. If DevTools is unavailable, Nier
falls back to a UIAutomator XML dump. Use ``dump_ui()`` to inspect the source
and any fallback warning.
"""

from __future__ import annotations

from pathlib import Path

from nier import connect

CONFIG = Path("config/nier.yaml")
OUTPUT_DIR = Path("artifacts/webview-ui")
OUTPUT_PATH = OUTPUT_DIR / "current-screen.ui.txt"
TREE_OUTPUT_PATH = OUTPUT_DIR / "current-screen.tree.txt"


def main() -> int:
    with connect(CONFIG) as phone:
        raw_dump = phone.uidump(OUTPUT_PATH, prefer_webview=True)
        document = phone.parse_uidump(raw_dump)
        tree = phone.format_tree(document, color=False)
        colored_tree = phone.format_tree(document)

    TREE_OUTPUT_PATH.write_text(tree + "\n", encoding="utf-8")

    print(f"saved raw WebView-preferred dump: {OUTPUT_PATH}")
    print(f"saved readable node tree: {TREE_OUTPUT_PATH}")
    print(f"parsed nodes: {len(document.walk())}")
    print("Use dump_ui() when you need source and fallback details.")
    print("\nUI node tree:\n")
    print(colored_tree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
