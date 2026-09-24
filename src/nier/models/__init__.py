"""Model provider interfaces and optional implementations."""

from .base import LlmToolCall
from .sysone import (
    SysOneAnswer,
    SysOneCriteria,
    SysOneDecisionProvider,
    SysOneProvider,
    SysOneQuestion,
    SysOneResponse,
)
from .ocr import PaddleOcrApiProvider, PaddleOcrCompatibleApiProvider, PaddleOcrProvider

__all__ = [
    "LlmToolCall",
    "SysOneAnswer",
    "SysOneCriteria",
    "SysOneDecisionProvider",
    "SysOneProvider",
    "SysOneQuestion",
    "SysOneResponse",
    "PaddleOcrApiProvider",
    "PaddleOcrCompatibleApiProvider",
    "PaddleOcrProvider",
]
