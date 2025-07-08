from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import (
    BaseState, 
    ObserveState, 
    GoalState, 
    ActionState
)

class ChitchatTaskState(BaseState, ObserveState, GoalState, ActionState):
    """
    流式回复状态
    """
    last_successful_action: str  # 上一次成功的行动
    aura_response: str  # 阿瑞斯回复
    response_message: str  # 响应缓冲区
