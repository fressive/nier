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

from nier import UiNode, connect, parse_uidump

CONFIG = Path("config/nier.yaml")
OUTPUT_DIR = Path("artifacts/webview-ui")
OUTPUT_PATH = OUTPUT_DIR / "current-screen.ui.txt"
TREE_OUTPUT_PATH = OUTPUT_DIR / "current-screen.tree.txt"

_DISPLAY_ATTRIBUTES = (
    "resource-id",
    "id",
    "class",
    "content-desc",
    "aria-label",
    "role",
    "href",
    "src",
    "name",
    "type",
    "value",
    "placeholder",
    "bounds",
    "clickable",
    "visible",
    "visible-to-user",
    "enabled",
    "checked",
    "selected",
)


def _short(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _format_node(node: UiNode) -> str:
    details = []
    if node.text:
        details.append(f"text={_short(node.text)!r}")
    for name in _DISPLAY_ATTRIBUTES:
        value = node.attributes.get(name)
        if value:
            details.append(f"{name}={_short(value)!r}")
    if details:
        return f"{node.tag} [{', '.join(details)}]"
    return node.tag


def format_tree(root: UiNode) -> str:
    """Render the parsed hierarchy as an indented, human-readable tree."""
    lines: list[str] = []

    def visit(
        node: UiNode,
        prefix: str,
        is_last: bool,
        is_root: bool = False,
    ) -> None:
        branch = "" if is_root else ("└── " if is_last else "├── ")
        lines.append(f"{prefix}{branch}{_format_node(node)}")
        child_prefix = (
            prefix if is_root else prefix + ("    " if is_last else "│   ")
        )
        for index, child in enumerate(node.children):
            visit(child, child_prefix, index == len(node.children) - 1)

    visit(root, "", True, is_root=True)
    return "\n".join(lines)


def main() -> int:
    with connect(CONFIG) as phone:
        raw_dump = phone.uidump(OUTPUT_PATH, prefer_webview=True)

    document = parse_uidump(raw_dump)
    tree = format_tree(document.root)
    TREE_OUTPUT_PATH.write_text(tree + "\n", encoding="utf-8")

    print(f"saved raw WebView-preferred dump: {OUTPUT_PATH}")
    print(f"saved readable node tree: {TREE_OUTPUT_PATH}")
    print(f"parsed nodes: {len(document.walk())}")
    print("Use dump_ui() when you need source and fallback details.")
    print("\nUI node tree:\n")
    print(tree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
