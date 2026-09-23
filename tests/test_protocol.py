from __future__ import annotations

import pytest

from nier.errors import ProtocolError
from nier.protocol import (
    Click,
    Point,
    ScreenshotRequest,
    Swipe,
    normalize_activity_component,
)


def test_normalized_point_is_validated() -> None:
    assert Point(0.5, 1.0, normalized=True).x == 0.5
    with pytest.raises(ProtocolError):
        Point(1.1, 0.5, normalized=True)


def test_swipe_requires_two_points() -> None:
    with pytest.raises(ProtocolError):
        Swipe((Point(1, 2),))


def test_click_rejects_negative_duration() -> None:
    with pytest.raises(ProtocolError):
        Click(Point(1, 2), duration_ms=-1)


def test_screenshot_defaults_are_safe() -> None:
    request = ScreenshotRequest()
    assert request.quality == 90
    with pytest.raises(ProtocolError):
        ScreenshotRequest(quality=0)


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        ("MainActivity", "com.example.app/com.example.app.MainActivity"),
        (".MainActivity", "com.example.app/com.example.app.MainActivity"),
        ("com.example.app.MainActivity", "com.example.app/com.example.app.MainActivity"),
        ("com.example.app/.MainActivity", "com.example.app/com.example.app.MainActivity"),
    ],
)
def test_activity_components_are_normalized(activity: str, expected: str) -> None:
    assert normalize_activity_component("com.example.app", activity) == expected


def test_activity_component_cannot_escape_package() -> None:
    with pytest.raises(ValueError):
        normalize_activity_component("com.example.app", "com.other.app.MainActivity")
    with pytest.raises(ValueError):
        normalize_activity_component("com.example.app", "com.other.app/.MainActivity")
