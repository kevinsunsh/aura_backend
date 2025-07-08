from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import (
    BaseState, 
    ObserveState, 
    GoalState, 
    KnowledgeState
)

class StreamingTaskState(BaseState, ObserveState, GoalState, KnowledgeState):
    """
    流式回复状态
    """
    streaming_action_history: List[str]  # 行动历史记录
    streaming_current_action: Optional[str]  # 当前行动
    streaming_action_reason: str  # 行动原因
    streaming_last_successful_reply_action: Optional[str]  # 上一次成功的回复行动
    aura_response: str  # 阿瑞斯回复
