from typing import TypedDict, Literal
from pydantic import BaseModel, Field

class UserInputCompletion(BaseModel):
    user_input_completion: str = Field(default="", description="尝试补全用户输入")
    user_input_completion_confidence: str = Field(default="", description="用户输入补全的置信度, 可选值: 非常肯定, 比较肯定, 不确定, 非常不确定")

class MainState(TypedDict):
    """
    主状态
    """
    chat_id: str # Chat ID
    waiting_for_user_message_at: int
    aura_response: str
    current_message: str