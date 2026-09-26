from __future__ import annotations

import sys
import types
from math import exp, log

import pytest

from nier.errors import VisionUnavailable
from nier.vision import ImageMatch, locate_template


class _FakeImage:
    def __init__(self, width: int, height: int) -> None:
        self.shape = (height, width)
        self.size = width * height

    def __getitem__(self, slices) -> _FakeImage:
        y_slice, x_slice = slices
        return _FakeImage(
            x_slice.stop - x_slice.start,
            y_slice.stop - y_slice.start,
        )


def _install_fake_cv2(
    monkeypatch,
    *,
    score: float = 0.93,
    scores: dict[tuple[int, int], float] | None = None,
    location: tuple[int, int] = (4, 3),
) -> None:
    cv2 = types.ModuleType("cv2")
    numpy = types.ModuleType("numpy")
    numpy.uint8 = object()
    numpy.frombuffer = lambda data, dtype: data
    numpy.std = lambda _image: 1.0
    numpy.geomspace = lambda start, stop, num: [
        exp(log(start) + (log(stop) - log(start)) * index / (num - 1))
        for index in range(num)
    ]
    cv2.IMREAD_GRAYSCALE = 0
    cv2.TM_CCOEFF_NORMED = 5
    cv2.INTER_AREA = 3
    cv2.INTER_CUBIC = 2

    def imdecode(data, _flags):
        if data == b"screenshot":
            return _FakeImage(100, 80)
        if data == b"template":
            return _FakeImage(10, 6)
        return None

    def match_template(_search, image, _method):
        dimensions = (image.shape[1], image.shape[0])
        return scores.get(dimensions, score) if scores else score, location

    cv2.imdecode = imdecode
    cv2.resize = lambda _image, size, interpolation: _FakeImage(*size)
    cv2.matchTemplate = match_template
    cv2.minMaxLoc = lambda result: (0.0, result[0], (0, 0), result[1])
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "numpy", numpy)


def test_locate_template_returns_absolute_box_for_region_match(monkeypatch) -> None:
    _install_fake_cv2(monkeypatch)

    match = locate_template(
        b"screenshot",
        b"template",
        min_score=0.8,
        region=(20, 30, 40, 20),
    )

    assert match == ImageMatch(24, 33, 10, 6, 0.93)
    assert match is not None
    assert match.bounds == (24, 33, 34, 39)
    assert match.center == (29.0, 36.0)


def test_locate_template_returns_none_below_threshold(monkeypatch) -> None:
    _install_fake_cv2(monkeypatch, score=0.74)

    assert locate_template(b"screenshot", b"template", min_score=0.8) is None


def test_locate_template_finds_a_scaled_template(monkeypatch) -> None:
    _install_fake_cv2(
        monkeypatch,
        score=0.5,
        scores={(15, 9): 0.97},
    )

    match = locate_template(
        b"screenshot",
        b"template",
        min_score=0.9,
        region=(20, 30, 40, 20),
        scale_range=(1.5, 1.5),
    )

    assert match == ImageMatch(24, 33, 15, 9, 0.97)


def test_locate_template_can_scale_down_a_template_larger_than_the_region(
    monkeypatch,
) -> None:
    _install_fake_cv2(monkeypatch, location=(0, 0))

    match = locate_template(
        b"screenshot",
        b"template",
        region=(20, 30, 8, 4),
        scale_range=(0.5, 0.5),
    )

    assert match == ImageMatch(20, 30, 5, 3, 0.93)


def test_locate_template_handles_real_resizing_when_vision_is_available() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    random = np.random.default_rng(7)
    template = random.integers(0, 256, (18, 24), dtype=np.uint8)
    scaled = cv2.resize(template, (36, 27), interpolation=cv2.INTER_CUBIC)
    screenshot = random.integers(0, 40, (100, 150), dtype=np.uint8)
    screenshot[31:58, 67:103] = scaled
    template_ok, template_data = cv2.imencode(".png", template)
    screenshot_ok, screenshot_data = cv2.imencode(".png", screenshot)
    assert template_ok and screenshot_ok

    match = locate_template(
        screenshot_data.tobytes(),
        template_data.tobytes(),
        min_score=0.9,
    )

    assert match is not None
    assert match.bounds == (67, 31, 103, 58)
    assert match.score > 0.99


def test_locate_template_validates_threshold_and_region(monkeypatch) -> None:
    _install_fake_cv2(monkeypatch)

    with pytest.raises(ValueError, match="min_score"):
        locate_template(b"screenshot", b"template", min_score=1.1)
    with pytest.raises(ValueError, match="region"):
        locate_template(
            b"screenshot",
            b"template",
            region=(90, 70, 20, 20),
        )
    with pytest.raises(ValueError, match="scale_range"):
        locate_template(
            b"screenshot",
            b"template",
            scale_range=(2.0, 1.0),
        )
    with pytest.raises(ValueError, match="scale_steps"):
        locate_template(
            b"screenshot",
            b"template",
            scale_steps=1,
        )


def test_locate_template_rejects_undecodable_image(monkeypatch) -> None:
    _install_fake_cv2(monkeypatch)

    with pytest.raises(ValueError, match="screenshot"):
        locate_template(b"bad image", b"template")


def test_locate_template_rejects_flat_template(monkeypatch) -> None:
    _install_fake_cv2(monkeypatch)
    sys.modules["numpy"].std = lambda _image: 0.0

    with pytest.raises(ValueError, match="visual variation"):
        locate_template(b"screenshot", b"template")


def test_locate_template_reports_missing_optional_dependency(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)
    monkeypatch.setitem(sys.modules, "numpy", None)

    with pytest.raises(VisionUnavailable, match=r"nier\[vision\]"):
        locate_template(b"screenshot", b"template")
