from typing import List, Optional
from enum import Enum
from agents.states.shared_state import (
    BaseState
)

class MemorizingTaskState(BaseState):
    """
    记忆任务状态
    """
    memorizing_response: str
