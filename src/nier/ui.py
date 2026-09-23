"""UI acquisition, dump parsing, and WebView fallback policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from re import Pattern
from xml.etree import ElementTree

from .backend import Backend
from .errors import ProtocolError
from .protocol import DumpUiRequest, UiDump, UiSource

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_TREE_BOOLEAN_ATTRIBUTES = {
    "aria-atomic",
    "aria-busy",
    "aria-checked",
    "aria-disabled",
    "aria-expanded",
    "aria-hidden",
    "aria-modal",
    "aria-multiline",
    "aria-multiselectable",
    "aria-pressed",
    "aria-readonly",
    "aria-required",
    "aria-selected",
    "checkable",
    "checked",
    "clickable",
    "context-clickable",
    "dismissable",
    "editable",
    "enabled",
    "focusable",
    "focused",
    "long-clickable",
    "password",
    "scrollable",
    "selected",
    "visible",
    "visible-to-user",
}
TextMatcher = str | Pattern[str]


def _matches(
    value: str, expected: TextMatcher | None, *, contains: bool = False
) -> bool:
    if expected is None:
        return True
    if hasattr(expected, "search"):
        return expected.search(value) is not None
    return str(expected) in value if contains else value == expected


def _boolean_attribute(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


@dataclass(frozen=True)
class UiNode:
    """One parsed UI node from UIAutomator XML or WebView HTML."""

    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    text: str = ""
    children: tuple[UiNode, ...] = ()

    @property
    def text_content(self) -> str:
        """Return this node's text plus descendant text, normalized."""
        parts = [self.text.strip()]
        parts.extend(child.text_content for child in self.children)
        return " ".join(part for part in parts if part)

    @property
    def resource_id(self) -> str:
        return self.attributes.get("resource-id", self.attributes.get("id", ""))

    @property
    def class_name(self) -> str:
        return self.attributes.get("class", "")

    @property
    def content_desc(self) -> str:
        return self.attributes.get(
            "content-desc",
            self.attributes.get("aria-label", self.attributes.get("title", "")),
        )

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        value = self.attributes.get("bounds", "")
        match = _BOUNDS_RE.fullmatch(value.strip())
        if match is None:
            return None
        return tuple(int(item) for item in match.groups())  # type: ignore[return-value]

    @property
    def center(self) -> tuple[float, float] | None:
        bounds = self.bounds
        if bounds is None:
            return None
        left, top, right, bottom = bounds
        return ((left + right) / 2, (top + bottom) / 2)

    @property
    def clickable(self) -> bool | None:
        return _boolean_attribute(self.attributes.get("clickable"))

    @property
    def visible(self) -> bool | None:
        value = self.attributes.get("visible-to-user", self.attributes.get("visible"))
        return _boolean_attribute(value)

    def attr(self, name: str, default: str | None = None) -> str | None:
        """Read an arbitrary source attribute."""
        return self.attributes.get(name, default)

    def to_dict(self) -> dict[str, object]:
        """Return this element and its descendants as JSON-ready data."""
        return _structured_node(self, max_nodes=None, max_text_length=None, state=[0])

    def walk(self) -> tuple[UiNode, ...]:
        """Return this node and all descendants in document order."""
        result = [self]
        for child in self.children:
            result.extend(child.walk())
        return tuple(result)

    def find_all(
        self,
        *,
        text: TextMatcher | None = None,
        text_contains: TextMatcher | None = None,
        resource_id: TextMatcher | None = None,
        class_name: TextMatcher | None = None,
        content_desc: TextMatcher | None = None,
        tag: TextMatcher | None = None,
        clickable: bool | None = None,
        visible: bool | None = None,
    ) -> tuple[UiNode, ...]:
        """Find matching nodes, including this node if it matches."""
        result: list[UiNode] = []
        for node in self.walk():
            if not _matches(node.text_content, text):
                continue
            if not _matches(node.text, text_contains, contains=True):
                continue
            if not _matches(node.resource_id, resource_id):
                continue
            if not _matches(node.class_name, class_name):
                continue
            if not _matches(node.content_desc, content_desc):
                continue
            if not _matches(node.tag, tag):
                continue
            if clickable is not None and node.clickable is not clickable:
                continue
            if visible is not None and node.visible is not visible:
                continue
            result.append(node)
        return tuple(result)

    def find(self, **filters: TextMatcher | bool | None) -> UiNode | None:
        """Return the first matching node or ``None``."""
        matches = self.find_all(**filters)
        return matches[0] if matches else None


def _format_tree(root: UiNode, *, color: bool) -> str:
    """Render a compact tree, showing text and true-valued attributes only."""
    lines: list[str] = []

    def styled(value: str, code: str) -> str:
        return f"\x1b[{code}m{value}\x1b[0m" if color else value

    def short(value: str, limit: int = 120) -> str:
        value = " ".join(value.split())
        if len(value) > limit:
            return value[: limit - 1] + "…"
        return value

    def format_node(node: UiNode) -> str:
        details: list[str] = []
        if node.text:
            details.append(f"text={styled(repr(short(node.text)), '32')}")
        details.extend(
            styled(f"{name}=True", "33")
            for name, value in node.attributes.items()
            if (
                name.lower() in _TREE_BOOLEAN_ATTRIBUTES
                and _boolean_attribute(value) is True
            )
        )
        rendered_tag = styled(node.tag, "1;36")
        if details:
            return f"{rendered_tag} [{', '.join(details)}]"
        return rendered_tag

    def visit(
        node: UiNode,
        prefix: str,
        is_last: bool,
        *,
        is_root: bool = False,
    ) -> None:
        branch = "" if is_root else styled("└── " if is_last else "├── ", "2")
        lines.append(f"{prefix}{branch}{format_node(node)}")
        child_prefix = (
            prefix if is_root else prefix + ("    " if is_last else styled("│   ", "2"))
        )
        for index, child in enumerate(node.children):
            visit(
                child,
                child_prefix,
                index == len(node.children) - 1,
            )

    visit(root, "", True, is_root=True)
    return "\n".join(lines)


@dataclass(frozen=True)
class UiDocument:
    """Parsed representation of a generated UI dump."""

    root: UiNode
    raw: str
    source: UiSource | None = None
    complete: bool = True
    warning: str = ""

    def walk(self) -> tuple[UiNode, ...]:
        return self.root.walk()

    def find_all(self, **filters: TextMatcher | bool | None) -> tuple[UiNode, ...]:
        return self.root.find_all(**filters)

    def find(self, **filters: TextMatcher | bool | None) -> UiNode | None:
        return self.root.find(**filters)

    def to_dict(
        self,
        *,
        include_raw: bool = False,
        max_nodes: int | None = 256,
        max_text_length: int | None = 500,
    ) -> dict[str, object]:
        """Return a bounded, JSON-ready representation of the UI tree.

        The default bound is intended for model context. Pass ``max_nodes=None``
        when an offline caller needs the complete parsed tree. Raw XML/HTML is
        excluded unless ``include_raw=True`` because structured consumers
        normally do not need a second, unbounded copy of the same UI.
        """
        if max_nodes is not None and max_nodes <= 0:
            raise ValueError("max_nodes must be positive or None")
        if max_text_length is not None and max_text_length <= 0:
            raise ValueError("max_text_length must be positive or None")
        result: dict[str, object] = {
            "source": self.source.value if self.source is not None else None,
            "complete": self.complete,
            "warning": self.warning,
            "root": _structured_node(
                self.root,
                max_nodes=max_nodes,
                max_text_length=max_text_length,
                state=[0],
            ),
        }
        if include_raw:
            result["raw"] = self.raw
        return result


def _clip_text(value: str, max_text_length: int | None) -> str:
    if max_text_length is None or len(value) <= max_text_length:
        return value
    return value[:max_text_length] + "…"


def _structured_node(
    node: UiNode,
    *,
    max_nodes: int | None,
    max_text_length: int | None,
    state: list[int],
) -> dict[str, object]:
    if max_nodes is not None and state[0] >= max_nodes:
        return {"tag": node.tag, "truncated": True}
    state[0] += 1

    result: dict[str, object] = {"tag": node.tag}
    if node.attributes:
        result["attributes"] = {
            str(name): _clip_text(str(value), max_text_length)
            for name, value in node.attributes.items()
        }
    if node.text:
        result["text"] = _clip_text(node.text, max_text_length)
    text_content = node.text_content
    if text_content and text_content != node.text:
        result["text_content"] = _clip_text(text_content, max_text_length)
    if node.resource_id:
        result["resource_id"] = _clip_text(node.resource_id, max_text_length)
    if node.class_name:
        result["class_name"] = _clip_text(node.class_name, max_text_length)
    if node.content_desc:
        result["content_desc"] = _clip_text(node.content_desc, max_text_length)
    if node.bounds is not None:
        result["bounds"] = list(node.bounds)
        result["center"] = list(node.center or ())
    if node.clickable is not None:
        result["clickable"] = node.clickable
    if node.visible is not None:
        result["visible"] = node.visible

    children: list[dict[str, object]] = []
    for index, child in enumerate(node.children):
        if max_nodes is not None and state[0] >= max_nodes:
            children.append(
                {
                    "truncated": True,
                    "remaining_children": len(node.children) - index,
                }
            )
            break
        children.append(
            _structured_node(
                child,
                max_nodes=max_nodes,
                max_text_length=max_text_length,
                state=state,
            )
        )
    if children:
        result["children"] = children
    return result


@dataclass
class _MutableNode:
    tag: str
    attributes: dict[str, str]
    text_parts: list[str] = field(default_factory=list)
    children: list[_MutableNode] = field(default_factory=list)

    def freeze(self) -> UiNode:
        return UiNode(
            tag=self.tag,
            attributes=dict(self.attributes),
            text=" ".join(part.strip() for part in self.text_parts if part.strip()),
            children=tuple(child.freeze() for child in self.children),
        )


class _HtmlTreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[_MutableNode] = []
        self.stack: list[_MutableNode] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _MutableNode(tag, {name: value or "" for name, value in attrs})
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.roots.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _MutableNode(tag, {name: value or "" for name, value in attrs})
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.roots.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].text_parts.append(data)


def _xml_node(element: ElementTree.Element) -> UiNode:
    tag = element.tag.rsplit("}", 1)[-1] if "}" in element.tag else element.tag
    text = element.attrib.get("text", "")
    if not text and element.text:
        text = element.text
    return UiNode(
        tag=tag,
        attributes=dict(element.attrib),
        text=text.strip(),
        children=tuple(_xml_node(child) for child in element),
    )


def _html_root(raw: str) -> UiNode:
    parser = _HtmlTreeBuilder()
    try:
        parser.feed(raw)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"could not parse UI dump as HTML: {exc}") from exc
    roots = tuple(node.freeze() for node in parser.roots)
    if not roots:
        raise ProtocolError("UI dump contains no parseable root node")
    if len(roots) == 1:
        return roots[0]
    return UiNode("document", children=roots)


def parse_uidump(
    dump: str | Path | UiDump,
    *,
    source: UiSource | None = None,
) -> UiDocument:
    """Parse UIAutomator XML or WebView HTML into searchable nodes.

    A ``Path`` reads a previously saved dump. A string is treated as dump
    content, so callers can safely parse XML/HTML that happens to contain
    characters resembling a filename.
    """
    complete = True
    warning = ""
    if isinstance(dump, UiDump):
        raw = dump.xml
        source = dump.source if source is None else source
        complete = dump.complete
        warning = dump.warning
    elif isinstance(dump, Path):
        try:
            raw = dump.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(f"could not read UI dump {dump}: {exc}") from exc
    elif isinstance(dump, str):
        raw = dump
    else:
        raise TypeError("dump must be XML/HTML text, a Path, or UiDump")

    if not raw.strip():
        raise ProtocolError("UI dump is empty")

    root: UiNode
    if source is UiSource.WEBVIEW_DEVTOOLS:
        root = _html_root(raw)
    else:
        try:
            root = _xml_node(ElementTree.fromstring(raw))
        except ElementTree.ParseError:
            root = _html_root(raw)
    return UiDocument(
        root=root, raw=raw, source=source, complete=complete, warning=warning
    )


@dataclass(frozen=True)
class UiSnapshot:
    xml: str
    source: UiSource
    complete: bool
    warning: str = ""


class UiDumpProvider:
    """Use the device's negotiated policy and preserve fallback diagnostics."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def capture(
        self, *, prefer_webview: bool = True, include_invisible: bool = False
    ) -> UiSnapshot:
        result: UiDump = self.backend.dump_ui(
            DumpUiRequest(
                prefer_webview=prefer_webview, include_invisible=include_invisible
            )
        )
        return UiSnapshot(
            xml=result.xml,
            source=result.source,
            complete=result.complete,
            warning=result.warning,
        )
