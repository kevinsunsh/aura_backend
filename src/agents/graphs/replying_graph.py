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
from configuration.config import GraphConfiguration, get_chat_model_by_type
from loguru import logger
from agents.prompts.replying_prompt import (
    REPLYING_GENERATOR_DIRECT_PROMPT,
    REPLYING_CHECK_PROMPT
)
from agents.aura_memory.message_store import MessageStore, Message
from agents.aura_memory.chat_stream import ChatStreamManager
from utils.utils import start_performance_point, end_performance_point
from utils.todo_mock_func import (
    _build_chat_history_str
)
from agents.task_manager import TaskManager, TaskType, TaskStateType


history_check_interval = 20000 #ms

async def _observe_conversation(state: ReplayingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.STOPPED:
            return Command(goto=END, update={
                "replaying_response": "stopped"
            })
        if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.PAUSED:
            return Command(goto=END, update={
                "replaying_response": "paused"
            })
        
        chat_id = state["chat_id"]
        user_id = state["user_id"]
        
        # 获取新消息
        now_timestamp = int(datetime.now().timestamp() * 1000)
        history_messages = MessageStore.get_instance().get_messages_by_time_range(
            chat_id, 
            now_timestamp - history_check_interval, 
            now_timestamp
        )
        
        last_bot_message = MessageStore.get_instance().get_recent_messages(user_id="aura", limit=1)[0]
        last_bot_message_time = last_bot_message.created_at if last_bot_message else None
        last_user_message = MessageStore.get_instance().get_recent_messages(user_id=user_id, limit=1)[0]
        last_user_message_time = last_user_message.created_at if last_user_message else None
        # last_user_messages = MessageStore.get_instance().get_messages_in_recent_time(
        #     milliseconds=min(now_timestamp - last_bot_message_time, history_check_interval), 
        #     user_id=user_id, 
        #     chat_id=chat_id
        # )

        # last_user_message_time = last_user_messages[-1].created_at if last_user_messages[-1] else None
        # last_user_message_content = "".join([last_user_message.content for last_user_message in last_user_messages])
        # 更新观察信息
        chat_history_str = _build_chat_history_str(history_messages)
        logger.debug(f"observe_conversation chat_history_str: {chat_history_str}")

        if last_bot_message_time is None or last_user_message_time is None:
            logger.info(f"observe_conversation last_bot_message_time or last_user_message_time is None")
            await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.STOPPED)
            return Command(goto=END, update={
                "replaying_response": "skipped"
            })
        # if last_bot_message_time > last_user_message_time:
        #     logger.info(f"observe_conversation last_bot_message_time > last_user_message_time")
        #     await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.STOPPED)
        #     return Command(goto=END, update={
        #         "replaying_response": "skipped"
        #     })
        # logger.info(f"observe_conversation last_user_message_content: {last_user_message_content}")
        plan_model = get_chat_model_by_type("pfc_action_planner")
        check_prompt = REPLYING_CHECK_PROMPT.format(user_input=chat_history_str)
        check_response = await plan_model.ainvoke([
            SystemMessage(content=check_prompt)
        ])
        if "false" in check_response.content.lower():
            await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.STOPPED)
            return Command(goto=END, update={
                "replaying_response": "skipped"
            })
        
        return Command(goto="generate_reply", update={
            "chat_history_str": chat_history_str,
            "last_user_message_content": last_user_message_content
        })
    except Exception as e:
        logger.error(f"生成被动回复时出错: {str(e)}")
        return Command(goto=END, update={
            "replaying_response": "error"
        })

async def _generate_reply(state: ReplayingTaskState, config: RunnableConfig):
    try:
        # 使用LLM生成立即回复
        chat_model = get_chat_model_by_type("pfc_chat")
        thinking_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.THINKING)
        goals_str = thinking_task_shared_data.get("goals_str", "")
        knowledge_info_str = thinking_task_shared_data.get("knowledge_info_str", "")
        persona_text = ""

        # 格式化提示词
        prompt = REPLYING_GENERATOR_DIRECT_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            chat_history_str=state["chat_history_str"],
            user_latest_message=state["last_user_message_content"]
        )
        writer = get_stream_writer()
        # 生成立即回复
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
                writer({"content": chunk.content})
        ChatStreamManager.get_instance().update_chat_stream_checked_at(state["chat_id"])
        # if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.STOPPED:
        #     await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)
        logger.info(f"generate_reply final_response: {final_response}")
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.STOPPED)
        return Command(goto=END, update={
            "replaying_response": "finished"
        })
    except Exception as e:
        logger.error(f"生成被动回复时出错: {str(e)}")
        return Command(goto=END, update={
            "replaying_response": "error"
        })

# 创建前台状态机图
builder = StateGraph(ReplayingTaskState, config_schema=GraphConfiguration)

# 添加节点
builder.add_node("observe_conversation", _observe_conversation)
builder.add_node("generate_reply", _generate_reply)

# 添加边
builder.add_edge(START, "observe_conversation")







