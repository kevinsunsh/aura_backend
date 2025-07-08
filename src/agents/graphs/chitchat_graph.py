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

from agents.states.streaming_state import StreamingTaskState
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.streaming_prompt import (
    FRONTEND_REPLY_GENERATOR_DIRECT_PROMPT,
    FRONTEND_ACTION_PLANNER_PROMPT,
    FRONTEND_INITIAL_ACTION,
    FRONTEND_FOLLOW_UP_ACTION
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.task_manager import StreamingActionType
from agents.graphs.todo_mock_func import (
    _get_persona_text,
    _build_chat_history_str,
    _build_goals_str,
    _build_knowledge_info_str,
    _build_action_history_summary
)
from agents.task_manager import TaskManager

logger = logging.getLogger(__name__)

# 后台任务节点函数
async def _observe_conversation(state: StreamingTaskState, config: RunnableConfig):
    """观察对话状态"""
    try:
        chat_id = state["chat_id"]
        configurable = Configuration.from_runnable_config(config)
        
        # 获取新消息
        now_timestamp = int(datetime.now().timestamp() * 1000)
        chat_stream = configurable.chat_stream_manager.get_or_create_chat_stream(chat_id)
        messages = configurable.message_store.get_messages_by_time_range(
            chat_id, 
            chat_stream.chatstream_checked_at, 
            now_timestamp
        )

        # 更新观察信息
        new_messages_count = len(messages)
        chat_history_str = _build_chat_history_str(messages)
        logger.info(f"observe_conversation chat_history_str: {chat_history_str}")
        # 构建未处理消息列表
        unprocessed_messages = []
        for msg in messages:
            unprocessed_messages.append({
                "message_id": msg.msg_id,
                "content": msg.content,
                "user_id": msg.user_id,
                "created_at": msg.created_at
            })
        if new_messages_count > 0:
            return Command(
                update={
                    "new_messages_count": new_messages_count,
                    "chat_history_str": chat_history_str,
                    "unprocessed_messages": unprocessed_messages,
                },
                goto="plan_action"
            )
        else:
            return Command(
                goto=END
            )
    except Exception as e:
        logger.error(f"观察对话状态时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _generate_reply(state: StreamingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        configurable = Configuration.from_runnable_config(config)
        # 使用LLM生成立即回复
        chat_model = get_chat_model_by_type("basic")
        
        persona_text = _get_persona_text()
        
        # 使用从checkpoint获取的共享变量，如果没有则使用state中的默认值
        goals = state.get("goals", state.get("goals", []))
        knowledge_list = state.get("knowledge_list", state.get("knowledge_list", []))
        messages = configurable.message_store.get_messages_by_time_range(
            state["chat_id"], 
            configurable.chat_stream_manager.get_or_create_chat_stream(state["chat_id"]).chatstream_checked_at, 
            int(datetime.now().timestamp() * 1000)
        )
        messages.reverse()
        chat_history_str = _build_chat_history_str(messages)
        logger.info(f"generate_reply chat_history_str: {chat_history_str}")
        goals_str = _build_goals_str(goals)
        knowledge_info_str = _build_knowledge_info_str(knowledge_list)
        
        # 格式化提示词
        prompt = FRONTEND_REPLY_GENERATOR_DIRECT_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            chat_history_text=chat_history_str
        )
        
        writer = get_stream_writer()
        # 生成立即回复
        immediate_response = ""
        quick_response_point_id = start_performance_point("快速响应")
        async for chunk in chat_model.astream([
            SystemMessage(content=prompt)
        ]):
            if hasattr(chunk, 'content'):
                end_performance_point(quick_response_point_id)
                immediate_response += chunk.content
                writer({"content": chunk.content})
                if TaskManager.get_instance().get_streaming_action().action_type == StreamingActionType.WAITING:
                    logger.info(f"打断流式响应，继续倾听")  
                    break
        # 保存消息到数据库
        configurable.message_store.add_message(Message(
            msg_id=str(uuid.uuid4()),
            chat_id=state["chat_id"],
            user_id="aura",
            platform="default",
            m_type="text",
            content=immediate_response,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        ))
        configurable.chat_stream_manager.update_chat_stream_checked_at(state["chat_id"])
        return Command(goto=END, update={
            "aura_response": "finished"
        })            
    except Exception as e:
        return Command(goto=END)            

# 创建前台状态机图
builder = StateGraph(StreamingTaskState, config_schema=Configuration)

# 添加节点
builder.add_node("observe_conversation", _observe_conversation)
builder.add_node("generate_reply", _generate_reply)

# 添加边
builder.add_edge(START, "observe_conversation")

