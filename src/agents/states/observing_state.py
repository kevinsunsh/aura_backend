from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from agents.states.shared_state import BaseState

class ObservingTaskState(BaseState):
    """
    观察状态
    """
    observing_response: str
