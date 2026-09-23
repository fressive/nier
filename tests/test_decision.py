from __future__ import annotations

from nier.models.base import BoundingBox, TextSpan
from nier.models.decision import TextMatchDecisionProvider


def test_decision_keeps_ocr_coordinates() -> None:
    result = TextMatchDecisionProvider().decide(
        [TextSpan("提交", 0.95, BoundingBox(10, 20, 30, 40))],
        "点击提交按钮",
    )
    assert result.action == "tap"
    assert result.point == (20, 30)
    assert result.confidence == 0.95


def test_decision_does_not_guess_when_no_text_matches() -> None:
    result = TextMatchDecisionProvider().decide(
        [TextSpan("取消", 0.99, BoundingBox(10, 20, 30, 40))],
        "点击提交按钮",
    )
    assert result.action == "noop"
    assert result.point is None

