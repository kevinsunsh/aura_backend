import json
import uuid
import asyncio
import time
from datetime import datetime
from typing import Literal, Optional, Tuple, Dict, Any, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer

from agents.states.muttering_state import MutteringTaskState
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.replying_prompt import (
    REPLYING_GENERATOR_DIRECT_PROMPT
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import (
    _get_persona_text
)
from agents.task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)

async def _generate_muttering(state: MutteringTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.STOPPED:
            return Command(goto=END, update={
                "muttering_response": "stopped"
            })
        if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.PAUSED:
            return Command(goto=END, update={
                "muttering_response": "paused"
            })
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        last_bot_message_time = observing_task_shared_data.get("last_bot_message_time", None)
        last_user_message_time = observing_task_shared_data.get("last_user_message_time", None)
        if last_bot_message_time is None or last_user_message_time is None:
            return Command(goto=END, update={
                "muttering_response": "skipped"
            })
        if last_bot_message_time > last_user_message_time:
            return Command(goto=END, update={
                "muttering_response": "skipped"
            })
        
        return Command(goto=END, update={
            "muttering_response": "finished",
            "muttering_content": "我想想。"
        })
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(goto=END, update={
            "muttering_response": "error"
        })            

# 创建前台状态机图
builder = StateGraph(MutteringTaskState, config_schema=Configuration)

# 添加节点
builder.add_node("generate_muttering", _generate_muttering)

# 添加边
builder.add_edge(START, "generate_muttering")

