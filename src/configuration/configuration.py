import os
from enum import Enum
from dataclasses import dataclass, fields
from typing import Any, Optional, Dict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

@dataclass(kw_only=True)
class Configuration:
	"""The configurable fields for the chatbot."""
	# number_of_queries: int = 2 # Number of search queries to generate per iteration
	user_id: str = "default" # User ID
	thread_id: str = "default" # Thread ID
	session_id: str = "default" # Session ID
	# search_api: SearchAPI = SearchAPI.TAVILY # Default to TAVILY
	# search_api_config: Optional[Dict[str, Any]] = None 
	serper_api_key: str = "48fdcd7bf30f08324b50dc97c2cafe038da46a16"# Defaults to serper_api_key
	max_plan_iterations: int = 1  # Maximum number of plan iterations
	max_search_results: int = 3 # Maximum number of search results
	max_step_num: int = 3 # Maximum number of steps
	search_iteration_limit: int = 2 # Maximum number of search iterations

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
