from typing import TypedDict, Literal
from pydantic import BaseModel, Field

class QuickState(TypedDict):
    """
    快速响应状态
    """
    chat_id: str # Chat ID
    aura_response: str