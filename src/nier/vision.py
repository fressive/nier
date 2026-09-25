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
ImageScaleRange: TypeAlias = tuple[float, float]
SwipeDirection: TypeAlias = Literal["up", "down", "left", "right"]

_DEFAULT_SCALE_RANGE: ImageScaleRange = (0.5, 2.0)
_DEFAULT_SCALE_STEPS = 41


def _validate_jitter(jitter: float) -> float:
    if (
        isinstance(jitter, bool)
        or not isinstance(jitter, Real)
        or not isfinite(jitter)
        or jitter < 0
    ):
        raise ValueError("jitter must be a finite, non-negative pixel amount")
    return float(jitter)


def _gesture_jitter(jitter: float, humanize: bool) -> float:
    if not isinstance(humanize, bool):
        raise ValueError("humanize must be a boolean")
    amount = _validate_jitter(jitter)
    return amount if humanize else 0.0


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
        humanize: bool = True,
    ) -> ActionResult:
        """Tap within the matched region once, with small coordinate jitter.

        This is available on matches returned by ``Device.locate_icon()`` or
        ``Device.locate_text()``. A standalone ``ImageMatch`` has no device
        attached and raises ``RuntimeError``. ``jitter`` is the maximum
        random pixel offset from the center, clamped to the matched bounds.
        Set ``humanize=False`` to disable jitter, or pass ``jitter=0``. Device
        actions are never auto-retried.
        """
        if self._clicker is None:
            raise self._unbound_error()
        return self._clicker(duration_ms, _gesture_jitter(jitter, humanize))

    def long_press(
        self,
        duration_ms: int = 800,
        *,
        jitter: float = 2.0,
        humanize: bool = True,
    ) -> ActionResult:
        """Hold at the match for ``duration_ms`` with bounded finger jitter.

        The coordinate wiggle stays inside the match rectangle. Set
        ``humanize=False`` (or ``jitter=0``) for a stationary hold.
        ``duration_ms`` must be a positive integer. This sends one non-retried
        device action.
        """
        if self._long_presser is None:
            raise self._unbound_error()
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or duration_ms <= 0
        ):
            raise ValueError("duration_ms must be a positive integer")
        return self._long_presser(duration_ms, _gesture_jitter(jitter, humanize))

    def swipe(
        self,
        direction: SwipeDirection,
        *,
        distance: float | None = None,
        duration_ms: int = 350,
        jitter: float = 2.0,
        humanize: bool = True,
    ) -> ActionResult:
        """Swipe from the match in a cardinal direction.

        ``distance`` is in pixels and defaults to 40% of the screen dimension
        for that direction. The endpoint is clipped to the screen. ``jitter``
        controls small random offsets and path curvature in pixels. Set
        ``humanize=False`` (or ``jitter=0``) for a straight deterministic
        swipe. Invalid directions, distances, and requests with no room in the
        selected direction raise ``ValueError``.
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
            _gesture_jitter(jitter, humanize),
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
    scale_range: ImageScaleRange = _DEFAULT_SCALE_RANGE,
    scale_steps: int = _DEFAULT_SCALE_STEPS,
) -> ImageMatch | None:
    """Find ``template`` in an encoded screenshot using multi-scale correlation.

    ``region`` is an optional ``(x, y, width, height)`` crop in full-screen
    pixels. ``scale_range`` gives the smallest and largest template scale to
    search relative to the supplied image; ``scale_steps`` controls the number
    of logarithmically spaced sizes tested. The original size is tested when it
    falls inside the range. Promising sampled scales receive a small local
    refinement search to cover sizes between grid points. Returned bounds are
    relative to the full screenshot. OpenCV and NumPy are imported only when
    this function is called.
    """
    if (
        isinstance(min_score, bool)
        or not isinstance(min_score, Real)
        or not isfinite(min_score)
        or not 0.0 <= min_score <= 1.0
    ):
        raise ValueError("min_score must be a finite number between 0 and 1")
    minimum_scale, maximum_scale = _validate_scale_range(scale_range)
    if (
        isinstance(scale_steps, bool)
        or not isinstance(scale_steps, int)
        or not 2 <= scale_steps <= 41
    ):
        raise ValueError("scale_steps must be an integer between 2 and 41")
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

    scales = [
        float(scale)
        for scale in np.geomspace(
            minimum_scale,
            maximum_scale,
            num=scale_steps,
        )
    ]
    if minimum_scale <= 1.0 <= maximum_scale:
        scales.append(1.0)
    scales.sort(key=lambda scale: abs(scale - 1.0))

    best: ImageMatch | None = None
    tested_sizes: set[tuple[int, int]] = set()

    def consider_scale(scale: float) -> float | None:
        nonlocal best
        scaled_width = max(1, round(template_width * scale))
        scaled_height = max(1, round(template_height * scale))
        size = (scaled_width, scaled_height)
        if size in tested_sizes:
            return None
        tested_sizes.add(size)
        if scaled_width > search_width or scaled_height > search_height:
            return None

        if size == (template_width, template_height):
            scaled_template = template_image
        else:
            interpolation = (
                cv2.INTER_AREA
                if scale < 1.0
                else cv2.INTER_CUBIC
            )
            scaled_template = cv2.resize(
                template_image,
                size,
                interpolation=interpolation,
            )

        result = cv2.matchTemplate(
            search_image,
            scaled_template,
            cv2.TM_CCOEFF_NORMED,
        )
        _, max_score, _, max_location = cv2.minMaxLoc(result)
        score = float(max_score)
        if not isfinite(score):
            return None
        if best is None or score > best.score:
            best = ImageMatch(
                x=offset_x + int(max_location[0]),
                y=offset_y + int(max_location[1]),
                width=scaled_width,
                height=scaled_height,
                score=score,
            )
        return score

    coarse_results: list[tuple[float, float, tuple[int, int]]] = []
    for scale in scales:
        scaled_size = (
            max(1, round(template_width * scale)),
            max(1, round(template_height * scale)),
        )
        score = consider_scale(scale)
        if score is not None:
            coarse_results.append((score, scale, scaled_size))

    # Refine around the strongest coarse matches. Sampling two intermediate
    # scales on either side usually closes pixel-size gaps without requiring a
    # dense search across the entire scale range.
    ordered_scales = sorted(set(scales))
    seed_indices: list[int] = []
    seen_sizes: set[tuple[int, int]] = set()
    for _score, scale, size in sorted(coarse_results, reverse=True):
        if size in seen_sizes:
            continue
        seen_sizes.add(size)
        index = min(
            range(len(ordered_scales)),
            key=lambda candidate: abs(ordered_scales[candidate] - scale),
        )
        if any(abs(index - selected) < 2 for selected in seed_indices):
            continue
        seed_indices.append(index)
        if len(seed_indices) == 3:
            break

    for index in seed_indices:
        for neighbor in (index - 1, index + 1):
            if not 0 <= neighbor < len(ordered_scales):
                continue
            lower, upper = sorted((ordered_scales[index], ordered_scales[neighbor]))
            for fraction in (1 / 3, 2 / 3):
                consider_scale(lower + (upper - lower) * fraction)

    if best is None or best.score < min_score:
        return None
    return best


def _validate_scale_range(scale_range: ImageScaleRange) -> tuple[float, float]:
    if not isinstance(scale_range, tuple) or len(scale_range) != 2:
        raise ValueError("scale_range must be a (minimum, maximum) tuple")
    if any(
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(value)
        or not 0.1 <= value <= 4.0
        for value in scale_range
    ):
        raise ValueError("scale_range values must be finite and between 0.1 and 4.0")
    minimum, maximum = (float(value) for value in scale_range)
    if minimum > maximum:
        raise ValueError("scale_range minimum must not exceed its maximum")
    return minimum, maximum


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


__all__ = [
    "ImageMatch",
    "ImageRegion",
    "ImageScaleRange",
    "TemplateImage",
    "locate_template",
]
