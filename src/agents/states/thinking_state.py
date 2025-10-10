from typing import List, Optional
from enum import Enum
from agents.states.shared_state import (
    BaseState
)

class ActionTaskState(BaseState):
    """
    思考任务状态
    """
    action_response: str
