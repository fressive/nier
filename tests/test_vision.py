from __future__ import annotations

import sys
import types

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


def _install_fake_cv2(monkeypatch, *, score: float = 0.93) -> None:
    cv2 = types.ModuleType("cv2")
    numpy = types.ModuleType("numpy")
    numpy.uint8 = object()
    numpy.frombuffer = lambda data, dtype: data
    numpy.std = lambda _image: 1.0
    cv2.IMREAD_GRAYSCALE = 0
    cv2.TM_CCOEFF_NORMED = 5

    def imdecode(data, _flags):
        if data == b"screenshot":
            return _FakeImage(100, 80)
        if data == b"template":
            return _FakeImage(10, 6)
        return None

    cv2.imdecode = imdecode
    cv2.matchTemplate = lambda *_args: object()
    cv2.minMaxLoc = lambda _result: (0.0, score, (0, 0), (4, 3))
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
