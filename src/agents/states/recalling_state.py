from typing import List, Optional
from enum import Enum
from agents.states.shared_state import (
    BaseState
)

class RecallingTaskState(BaseState):
    """
    回忆任务状态
    """
    recalling_response: str
