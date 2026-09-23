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
from .jev_goal import JevGoal, JevGoalCandidate
from .models.base import LlmToolCall
from .models.jev import (
    JevAnswer,
    JevCriteria,
    JevDecisionProvider,
    JevProvider,
    JevQuestion,
    JevResponse,
)
from .protocol import ActivityInfo
from .ui import UiDocument, UiNode, parse_uidump

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
    "JevGoal",
    "JevGoalCandidate",
    "JevAnswer",
    "JevCriteria",
    "JevDecisionProvider",
    "JevProvider",
    "JevQuestion",
    "JevResponse",
    "LlmToolCall",
    "ActivityInfo",
    "UiDocument",
    "UiNode",
    "__version__",
    "connect",
    "parse_uidump",
]
