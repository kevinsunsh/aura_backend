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

from agents.states.replaying_state import ReplayingTaskState
from agents.configuration.config import GraphConfiguration, get_chat_model_by_type
import logging
from agents.prompts.replying_prompt import (
    REPLYING_GENERATOR_DIRECT_PROMPT
)
from agents.aura_memory.message_store import MessageStore, Message
from agents.aura_memory.chat_stream import ChatStreamManager
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import (
    _get_persona_text
)
from agents.task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)

async def _generate_reply(state: ReplayingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.STOPPED:
            return Command(goto=END, update={
                "replaying_response": "stopped"
            })
        
        # 使用LLM生成立即回复
        chat_model = get_chat_model_by_type("pfc_chat")
        
        persona_text = _get_persona_text()
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        processed_chat_history_str = observing_task_shared_data.get("processed_chat_history_str", "还没有聊天记录。")
        unprocessed_chat_history_str = observing_task_shared_data.get("unprocessed_chat_history_str", "还没有聊天记录。")
        last_bot_message_time = observing_task_shared_data.get("last_bot_message_time", None)
        last_user_message_time = observing_task_shared_data.get("last_user_message_time", None)
        if last_bot_message_time is None or last_user_message_time is None:
            return Command(goto=END, update={
                "replaying_response": "skipped"
            })
        if last_bot_message_time > last_user_message_time:
            return Command(goto=END, update={
                "replaying_response": "skipped"
            })
        
        thinking_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.THINKING)
        goals_str = thinking_task_shared_data.get("goals_str", "")
        knowledge_info_str = thinking_task_shared_data.get("knowledge_info_str", "")
        
        # 格式化提示词
        prompt = REPLYING_GENERATOR_DIRECT_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            processed_chat_history_str=processed_chat_history_str,
            unprocessed_chat_history_str=unprocessed_chat_history_str,
            bot_name="aura",
            user_name=state.get("user_id", "")
        )
        
        writer = get_stream_writer()
        # 生成立即回复
        final_response = ""
        quick_response_point_id = start_performance_point("快速响应")
        async for chunk in chat_model.astream([
            SystemMessage(content=prompt)
        ],
        extra_body={"thinking": {"type": "disabled"}}):
            if hasattr(chunk, 'content'):
                end_performance_point(quick_response_point_id)
                if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.PAUSED:
                    logger.info(f"打断流式响应，继续倾听")  
                    break
                if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.RUNNING:
                    await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.STOPPED)
                final_response += chunk.content
                writer({"content": chunk.content})
        
        ChatStreamManager.get_instance().update_chat_stream_checked_at(state["chat_id"])
        # 保存消息到数据库
        MessageStore.get_instance().add_message(Message(
            msg_id=str(uuid.uuid4()),
            chat_id=state["chat_id"],
            user_id="aura",
            platform="default",
            m_type="text",
            content=final_response,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        ))
        # if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.STOPPED:
        #     await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)
        return Command(goto=END, update={
            "replaying_response": "finished"
        })            
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(goto=END, update={
            "replaying_response": "error"
        })            

# 创建前台状态机图
builder = StateGraph(ReplayingTaskState, config_schema=GraphConfiguration)

# 添加节点
builder.add_node("generate_reply", _generate_reply)

# 添加边
builder.add_edge(START, "generate_reply")

