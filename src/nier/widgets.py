"""Device-bound widgets and bounded, typed selection over UI dumps."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from .errors import ModelError, UiElementNotFound
from .models.sysone import SysOneOptions
from .protocol import ActionResult, UiSource
from .ui import UiNode

if TYPE_CHECKING:
    from .api import Device
    from .models.router import ModelRouter

_MAX_CHOICE_WIDGETS = 32
_MAX_WIDGET_TEXT = 240


def _short(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) > _MAX_WIDGET_TEXT:
        return normalized[: _MAX_WIDGET_TEXT - 1] + "…"
    return normalized


@dataclass(frozen=True)
class Widget:
    """A parsed UI node bound to the device that captured it."""

    device: Device
    node: UiNode

    @property
    def text(self) -> str:
        return self.node.text_content

    @property
    def content_desc(self) -> str:
        return self.node.content_desc

    @property
    def clickable(self) -> bool | None:
        return self.node.clickable

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        return self.node.bounds

    @property
    def center(self) -> tuple[float, float] | None:
        return self.node.center

    @property
    def label(self) -> str:
        """Return the shortest useful human-readable label for decisions."""
        values = tuple(
            value
            for value in (
                _short(self.node.text_content),
                _short(self.node.content_desc),
                _short(self.node.resource_id),
            )
            if value
        )
        if values:
            return " — ".join(dict.fromkeys(values))
        return _short(self.node.class_name or self.node.tag)

    def click(self) -> ActionResult:
        """Tap the center of this clickable, not-explicitly-hidden widget once."""
        if self.node.clickable is not True or self.node.visible is False:
            raise UiElementNotFound("widget is not clickable or is explicitly hidden")
        bounds = self.node.bounds
        if not _usable_bounds(bounds):
            raise UiElementNotFound("widget has unusable screen bounds")
        center = self.node.center
        assert center is not None
        return self.device.tap(*center)


class WidgetList(Sequence[Widget]):
    """A chainable collection of widgets parsed from one UI dump.

    ``clickable()`` is an optional narrowing filter. ``choice()`` always
    restricts model candidates to clickable nodes not marked hidden and with
    screen bounds, so callers may omit the explicit filter before ``click()``.
    """

    def __init__(
        self,
        device: Device,
        nodes: Sequence[UiNode],
        *,
        source: UiSource | None = None,
    ) -> None:
        self._device = device
        self._widgets = tuple(Widget(device, node) for node in nodes)
        self.source = source

    @overload
    def __getitem__(self, index: int) -> Widget: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Widget, ...]: ...

    def __getitem__(self, index: int | slice) -> Widget | tuple[Widget, ...]:
        return self._widgets[index]

    def __len__(self) -> int:
        return len(self._widgets)

    def __iter__(self) -> Iterator[Widget]:
        return iter(self._widgets)

    def clickable(self) -> WidgetList:
        """Return clickable nodes that are not explicitly marked hidden."""
        return WidgetList(
            self._device,
            tuple(
                widget.node
                for widget in self._widgets
                if widget.clickable is True and widget.node.visible is not False
            ),
            source=self.source,
        )

    def choice(
        self,
        instruction: str,
        *,
        provider: str | None = None,
        router: ModelRouter | None = None,
        max_candidates: int = _MAX_CHOICE_WIDGETS,
    ) -> Widget:
        """Ask the configured TypeSafe Choice provider to select a widget.

        Clickable nodes not marked hidden and having usable screen bounds are
        candidates; the model receives labels and semantic attributes, never
        coordinates. UIAutomator dumps omit invisible nodes by default.
        The returned widget remains bound to this device and can be clicked.
        """
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("choice instruction must not be empty")
        if (
            isinstance(max_candidates, bool)
            or not isinstance(max_candidates, int)
            or max_candidates <= 0
        ):
            raise ValueError("max_candidates must be positive")

        candidates = tuple(
            widget
            for widget in self._widgets
            if widget.clickable is True
            and widget.node.visible is not False
            and _usable_bounds(widget.bounds)
        )
        if not candidates:
            raise UiElementNotFound(
                "no clickable widgets with usable screen bounds are available"
            )
        if len(candidates) > max_candidates:
            raise ValueError(
                f"choice has {len(candidates)} candidates; narrow the widgets or "
                f"raise max_candidates (limit: {max_candidates})"
            )

        options: dict[str, str] = {}
        descriptions: list[dict[str, str]] = []
        by_id: dict[str, Widget] = {}
        for index, widget in enumerate(candidates):
            candidate_id = f"widget_{index}"
            label = widget.label
            options[candidate_id] = label
            by_id[candidate_id] = widget
            descriptions.append(
                {
                    "id": candidate_id,
                    "label": label,
                    "tag": _short(widget.node.tag),
                    "class": _short(widget.node.class_name),
                    "resource_id": _short(widget.node.resource_id),
                    "content_desc": _short(widget.content_desc),
                }
            )

        answer = self._device.choice(
            {
                "source": self.source.value if self.source is not None else None,
                "widgets": descriptions,
            },
            options,
            instructions=instruction.strip(),
            question_id="widget",
            provider=provider,
            router=router,
        )
        selected = by_id.get(answer.choice or "")
        if selected is None:
            raise ModelError(
                f"SysOne Choice returned unknown widget id {answer.choice!r}"
            )
        return selected


def _usable_bounds(bounds: tuple[int, int, int, int] | None) -> bool:
    if bounds is None:
        return False
    left, top, right, bottom = bounds
    return left >= 0 and top >= 0 and right - left >= 12 and bottom - top >= 12


__all__ = ["Widget", "WidgetList"]
