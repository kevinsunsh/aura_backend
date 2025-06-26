import os
from enum import Enum
from dataclasses import dataclass, fields
from typing import Any, Optional, Dict, Literal

from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel


@dataclass(kw_only=True)
class Configuration:
	"""The configurable fields for the chatbot."""
	user_id: str = "default" # User ID
	thread_id: str = "default" # Thread ID

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
    "basic": "doubao-1-5-pro-32k-250115",
    "reasoning": "doubao-1-5-pro-32k-250115",
    "vision": "doubao-1-5-pro-32k-250115"
}

def get_chat_model_by_type(
    llm_type: LLMType,
) -> BaseChatModel:
    """
    Get LLM instance by type. Returns cached instance if available.
    """

    return init_chat_model(model=LLM_MODEL_MAP[llm_type], model_provider="openai")
