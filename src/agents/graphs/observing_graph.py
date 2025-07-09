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

from agents.states.observing_state import ObservingTaskState
from agents.configuration import Configuration, get_chat_model_by_type
import logging

from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import _build_chat_history_str
from agents.task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)
history_check_interval = 60000 #ms
# 后台任务节点函数
async def _observe_conversation(state: ObservingTaskState, config: RunnableConfig):
    """观察对话状态"""
    try:
        await asyncio.sleep(1)
        if TaskManager.get_instance().get_task_state(TaskType.OBSERVING) == TaskStateType.PAUSED:
            return Command(goto=END)
        
        configurable = Configuration.from_runnable_config(config)

        chat_id = state["chat_id"]
        user_id = state["user_id"]
        
        # 获取新消息
        now_timestamp = int(datetime.now().timestamp() * 1000)
        chat_stream = configurable.chat_stream_manager.get_or_create_chat_stream(chat_id)
        unprocessed_messages = configurable.message_store.get_messages_by_time_range(
            chat_id, 
            chat_stream.chatstream_checked_at, 
            now_timestamp
        )
        if chat_stream.chatstream_checked_at > now_timestamp - history_check_interval:
            recent_processed_messages = configurable.message_store.get_messages_by_time_range(
                chat_id, 
                now_timestamp - history_check_interval, 
                chat_stream.chatstream_checked_at
            )
        else:
            recent_processed_messages = []
        
        last_bot_message = configurable.message_store.get_recent_messages(user_id="aura", limit=1)[0]
        last_user_message = configurable.message_store.get_recent_messages(user_id=user_id, limit=1)[0]
        last_bot_message_time = last_bot_message.created_at if last_bot_message else None
        last_user_message_time = last_user_message.created_at if last_user_message else None
        last_bot_message_content = last_bot_message.content if last_bot_message else None
        last_user_message_content = last_user_message.content if last_user_message else None
        
        # 更新观察信息
        unprocessed_chat_history_str = _build_chat_history_str(unprocessed_messages)
        logger.info(f"observe_conversation unprocessed_chat_history_str: {unprocessed_chat_history_str}")
        processed_chat_history_str = _build_chat_history_str(recent_processed_messages)
        logger.info(f"observe_conversation processed_chat_history_str: {processed_chat_history_str}")

        await TaskManager.get_instance().set_task_shared_data(TaskType.OBSERVING, {
            "processed_chat_history_str": processed_chat_history_str,
            "unprocessed_chat_history_str": unprocessed_chat_history_str,
            "last_bot_message_time": last_bot_message_time,
            "last_bot_message_content": last_bot_message_content,
            "last_user_message_time": last_user_message_time,
            "last_user_message_content": last_user_message_content
        })

        return Command(goto=END)
    except Exception as e:
        logger.error(f"观察对话状态时出错: {str(e)}")
        return Command(
            goto=END
        )

# 创建StateGraph
builder = StateGraph(ObservingTaskState, config_schema=Configuration)

# 添加后台任务节点
builder.add_node("observe_conversation", _observe_conversation)

# 添加边
builder.add_edge(START, "observe_conversation")
