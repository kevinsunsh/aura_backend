from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import (
    BaseState
)

class MutteringTaskState(BaseState):
    """
    流式回复状态
    """
    muttering_response: str
    muttering_content: str
