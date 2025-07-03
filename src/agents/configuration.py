import os
from enum import Enum
from dataclasses import dataclass, fields
from typing import Any, Optional, Dict, Literal

from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel
from agents.aura_memory.message_store import MessageStore
from agents.aura_memory.chat_stream import ChatStream, ChatStreamManager

@dataclass(kw_only=True)
class Configuration:
	"""The configurable fields for the chatbot."""
	chat_id: str = "default" # User ID
	thread_id: str = "default" # Thread ID
	chat_stream: ChatStream = None
	message_store: MessageStore = None
	chat_stream_manager: ChatStreamManager = None

	@classmethod
	def from_runnable_config(
		cls, config: Optional[RunnableConfig] = None
	) -> "Configuration":
		"""Create a Configuration instance from a RunnableConfig."""
		configurable = (
			config["configurable"] if config and "configurable" in config else {}
		)
		values: dict[str, Any] = {
			f.name: os.environ.get(f.name.upper(), configurable.get(f.name))
			for f in fields(cls)
			if f.init
		}
		return cls(**{k: v for k, v in values.items() if v})

LLMType = Literal["basic", "reasoning", "vision"]
LLM_MODEL_MAP: dict[str, str] = {
    "basic": "doubao-seed-1-6-flash-250615",
    "reasoning": "doubao-seed-1-6-flash-250615",
    "vision": "doubao-seed-1-6-flash-250615"
}

def get_chat_model_by_type(
    llm_type: LLMType,
) -> BaseChatModel:
    """
    Get LLM instance by type. Returns cached instance if available.
    """

    return init_chat_model(model=LLM_MODEL_MAP[llm_type], model_provider="openai")

class ClientEventEnum(Enum):
	StartConnection = 1
	FinishConnection = 2
	StartSession = 100
	FinishSession = 102
	TaskRequest = 200
	SayHello = 300
	ChatTTSText = 500

class ServerEventEnum(Enum):
	ConnectionStarted = 50
	ConnectionFailed = 51
	ConnectionFinished = 52
	SessionStarted = 150
	SessionFinished = 152
	SessionFailed = 153
	TTSSentenceStart = 350
	TTSSentenceEnd = 351
	TTSResponse = 352
	TTSEnded = 359
	ASRInfo = 450
	ASRResponse = 451
	ASREnded = 459
	ChatResponse = 550
	ChatEnded = 559
