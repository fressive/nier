"""Optional OpenCV-based screenshot template matching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Literal, TypeAlias

from .errors import VisionUnavailable
from .protocol import ActionResult

TemplateImage: TypeAlias = str | Path | bytes
ImageRegion: TypeAlias = tuple[int, int, int, int]
SwipeDirection: TypeAlias = Literal["up", "down", "left", "right"]


def _validate_jitter(jitter: float) -> float:
    if (
        isinstance(jitter, bool)
        or not isinstance(jitter, Real)
        or not isfinite(jitter)
        or jitter < 0
    ):
        raise ValueError("jitter must be a finite, non-negative pixel amount")
    return float(jitter)


@dataclass(frozen=True)
class ImageMatch:
    """A visual match in absolute screen pixel coordinates.

    Matches returned by :class:`nier.Device` are bound to that device and can
    gesture relative to their bounds. Matches created by lower-level helper
    functions are not device-bound.
    """

    x: int
    y: int
    width: int
    height: int
    score: float
    _clicker: Callable[[int, float], ActionResult] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _long_presser: Callable[[int, float], ActionResult] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _swiper: Callable[
        [SwipeDirection, float | None, int, float], ActionResult
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Return the match rectangle as ``(left, top, right, bottom)``."""
        return self.x, self.y, self.x + self.width, self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        """Return the center of the matched region in screen pixels."""
        return self.x + self.width / 2, self.y + self.height / 2

    def click(
        self,
        duration_ms: int = 80,
        *,
        jitter: float = 2.0,
    ) -> ActionResult:
        """Tap within the matched region once, with small coordinate jitter.

        This is available on matches returned by ``Device.locate_icon()`` or
        ``Device.locate_text()``. A standalone ``ImageMatch`` has no device
        attached and raises ``RuntimeError``. ``jitter`` is the maximum
        random pixel offset from the center, clamped to the matched bounds;
        pass ``0`` for a deterministic center tap. Device actions are never
        auto-retried.
        """
        if self._clicker is None:
            raise self._unbound_error()
        return self._clicker(duration_ms, _validate_jitter(jitter))

    def long_press(
        self,
        duration_ms: int = 800,
        *,
        jitter: float = 2.0,
    ) -> ActionResult:
        """Hold at the match for ``duration_ms`` with bounded finger jitter.

        The coordinate wiggle stays inside the match rectangle. Set ``jitter=0``
        for a stationary hold. ``duration_ms`` must be a positive integer.
        This sends one non-retried device action.
        """
        if self._long_presser is None:
            raise self._unbound_error()
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or duration_ms <= 0
        ):
            raise ValueError("duration_ms must be a positive integer")
        return self._long_presser(duration_ms, _validate_jitter(jitter))

    def swipe(
        self,
        direction: SwipeDirection,
        *,
        distance: float | None = None,
        duration_ms: int = 350,
        jitter: float = 2.0,
    ) -> ActionResult:
        """Swipe from the match in a cardinal direction.

        ``distance`` is in pixels and defaults to 40% of the screen dimension
        for that direction. The endpoint is clipped to the screen. ``jitter``
        controls small random offsets and path curvature in pixels; set it to
        ``0`` for a straight deterministic swipe. Invalid directions,
        distances, and requests with no room in the selected direction raise
        ``ValueError``.
        """
        if self._swiper is None:
            raise self._unbound_error()
        if direction not in ("up", "down", "left", "right"):
            raise ValueError("direction must be 'up', 'down', 'left', or 'right'")
        if distance is not None and (
            isinstance(distance, bool)
            or not isinstance(distance, Real)
            or not isfinite(distance)
            or distance < 1
        ):
            raise ValueError("distance must be at least one finite pixel")
        return self._swiper(
            direction,
            distance,
            duration_ms,
            _validate_jitter(jitter),
        )

    @staticmethod
    def _unbound_error() -> RuntimeError:
        return RuntimeError(
            "this match is not bound to a device; obtain it from "
            "phone.locate_icon() or phone.locate_text()"
        )


def locate_template(
    screenshot: bytes,
    template: TemplateImage,
    *,
    min_score: float = 0.85,
    region: ImageRegion | None = None,
) -> ImageMatch | None:
    """Find ``template`` in an encoded screenshot using normalized correlation.

    ``region`` is an optional ``(x, y, width, height)`` crop in full-screen
    pixels. The returned match is always relative to the full screenshot.
    OpenCV and NumPy are imported only when this function is called.
    """
    if (
        isinstance(min_score, bool)
        or not isinstance(min_score, Real)
        or not isfinite(min_score)
        or not 0.0 <= min_score <= 1.0
    ):
        raise ValueError("min_score must be a finite number between 0 and 1")
    if not isinstance(screenshot, bytes) or not screenshot:
        raise ValueError("screenshot must contain encoded image bytes")
    template_data = _read_template(template)

    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise VisionUnavailable(
            "OpenCV icon matching is not installed; run "
            "python -m pip install 'nier[vision]'"
        ) from exc

    screen_image = _decode_image(cv2, np, screenshot, "screenshot")
    template_image = _decode_image(cv2, np, template_data, "template")
    if float(np.std(template_image)) == 0.0:
        raise ValueError("template image must contain visual variation")
    screen_height, screen_width = screen_image.shape[:2]

    if region is None:
        search_image = screen_image
        offset_x = offset_y = 0
    else:
        offset_x, offset_y, region_width, region_height = _validate_region(
            region, screen_width, screen_height
        )
        search_image = screen_image[
            offset_y : offset_y + region_height,
            offset_x : offset_x + region_width,
        ]

    template_height, template_width = template_image.shape[:2]
    search_height, search_width = search_image.shape[:2]
    if template_width > search_width or template_height > search_height:
        return None

    result = cv2.matchTemplate(
        search_image,
        template_image,
        cv2.TM_CCOEFF_NORMED,
    )
    _, max_score, _, max_location = cv2.minMaxLoc(result)
    score = float(max_score)
    if not isfinite(score) or score < min_score:
        return None

    return ImageMatch(
        x=offset_x + int(max_location[0]),
        y=offset_y + int(max_location[1]),
        width=template_width,
        height=template_height,
        score=score,
    )


def _read_template(template: TemplateImage) -> bytes:
    if isinstance(template, bytes):
        data = template
    elif isinstance(template, (str, Path)):
        data = Path(template).read_bytes()
    else:
        raise TypeError("template must be a file path or encoded image bytes")
    if not data:
        raise ValueError("template image is empty")
    return data


def _decode_image(cv2, np, data: bytes, label: str):
    image = cv2.imdecode(
        np.frombuffer(data, dtype=np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )
    if image is None or image.size == 0:
        raise ValueError(f"{label} is not a decodable image")
    return image


def _validate_region(
    region: ImageRegion,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int, int, int]:
    if not isinstance(region, tuple) or len(region) != 4:
        raise ValueError("region must be an (x, y, width, height) tuple")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in region
    ):
        raise ValueError("region values must be integers")
    x, y, width, height = region
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(
            "region coordinates must be non-negative with positive size"
        )
    if x + width > screen_width or y + height > screen_height:
        raise ValueError("region must fit within the screenshot dimensions")
    return x, y, width, height


__all__ = ["ImageMatch", "ImageRegion", "TemplateImage", "locate_template"]
