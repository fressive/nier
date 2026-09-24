"""Nier Android automation runtime."""

from .agent import (
    Agent,
    AgentDebugSession,
    AgentDebugState,
    AgentDebugStep,
    AgentPlan,
    AgentRun,
    AgentStep,
)
from .api import Device, connect
from .sysone_goal import SysOneGoal, SysOneGoalCandidate
from .models.base import LlmToolCall
from .models.sysone import (
    SysOneAnswer,
    SysOneCriteria,
    SysOneDecisionProvider,
    SysOneProvider,
    SysOneQuestion,
    SysOneResponse,
)
from .protocol import ActivityInfo
from .ui import UiDocument, UiNode, parse_uidump
from .vision import ImageMatch
from .widgets import Widget, WidgetList

__version__ = "0.1.0"
__all__ = [
    "Agent",
    "AgentDebugSession",
    "AgentDebugState",
    "AgentDebugStep",
    "AgentPlan",
    "AgentRun",
    "AgentStep",
    "Device",
    "SysOneGoal",
    "SysOneGoalCandidate",
    "SysOneAnswer",
    "SysOneCriteria",
    "SysOneDecisionProvider",
    "SysOneProvider",
    "SysOneQuestion",
    "SysOneResponse",
    "LlmToolCall",
    "ImageMatch",
    "ActivityInfo",
    "UiDocument",
    "UiNode",
    "Widget",
    "WidgetList",
    "__version__",
    "connect",
    "parse_uidump",
]
