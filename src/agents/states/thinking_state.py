from typing import List, Optional
from enum import Enum
from agents.states.shared_state import (
    BaseState, 
    ObserveState, 
    GoalState, 
    KnowledgeState
)

class ThinkingTaskState(BaseState, ObserveState, GoalState, KnowledgeState):
    """
    思考任务状态
    """
    thinking_action_history: List[str]  # 行动历史记录
    thinking_current_action: Optional[str]  # 当前行动
    thinking_action_reason: str  # 行动原因
