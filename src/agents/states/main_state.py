from typing import TypedDict
from pydantic import BaseModel, Field

class NovaUserMessage(BaseModel):
    content: str = Field(description="User message")
    created_at: str = Field(description="User message created at")

class NovaChatMessages(BaseModel):
    user_messages: list[NovaUserMessage] = Field(description="User messages")

class MainState(TypedDict):
    """
    主状态
    """
    user_id: str # User ID
    nova_response: str
    user_messages: NovaChatMessages # User messages
    
