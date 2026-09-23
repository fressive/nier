"""Model provider interfaces and optional implementations."""

from .base import LlmToolCall
from .jev import (
    JevAnswer,
    JevCriteria,
    JevDecisionProvider,
    JevProvider,
    JevQuestion,
    JevResponse,
)
from .ocr import PaddleOcrApiProvider, PaddleOcrCompatibleApiProvider, PaddleOcrProvider

__all__ = [
    "LlmToolCall",
    "JevAnswer",
    "JevCriteria",
    "JevDecisionProvider",
    "JevProvider",
    "JevQuestion",
    "JevResponse",
    "PaddleOcrApiProvider",
    "PaddleOcrCompatibleApiProvider",
    "PaddleOcrProvider",
]
