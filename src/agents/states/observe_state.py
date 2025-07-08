from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import BaseState, ObserveState, GoalState, KnowledgeState, TimeState

class ObserveTaskState(BaseState, ObserveState):
    """
    观察状态
    """
    start_time: float  # 任务开始时间
    end_time: float  # 任务结束时间
