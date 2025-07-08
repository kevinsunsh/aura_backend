from typing import List, Optional
from enum import Enum
from agents.states.shared_state import (
    BaseState
)

class ThinkingTaskState(BaseState):
    """
    思考任务状态
    """
    thinking_response: str
