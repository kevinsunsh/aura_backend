from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import (
    BaseState, 
    ObserveState, 
    GoalState, 
    KnowledgeState,
    ActionState
)

class SpeakingTaskState(BaseState, ObserveState, GoalState, KnowledgeState, ActionState):
    """
    流式回复状态
    """
    speaking_response: str
