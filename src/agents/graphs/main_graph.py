import json
import uuid
import asyncio
from enum import Enum
from datetime import datetime
from typing import Literal, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.documents import Document

from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer

from agents.states.main_state import MainState
from agents.configuration import Configuration, get_chat_model_by_type
import logging

logger = logging.getLogger(__name__)

async def _acquire_chat_stream(state: MainState, config: RunnableConfig):
    """处理聊天流获取"""
    try:
        # 获取用户ID
        user_id = state.get("user_id", "default_user")
        
        chat_model = get_chat_model_by_type("basic")
        # 生成简单的响应
        response = f"你好，我是Aura Agent。用户ID: {user_id}"
        
        # 使用stream方法生成流式响应
        writer = get_stream_writer() 
        async for chunk in chat_model.astream([
            SystemMessage(content=response)
        ]):
            if hasattr(chunk, 'content'):
                # 这里可以实时返回每个chunk，但为了简化，我们先收集完整响应
                writer({"content": chunk.content})
            elif isinstance(chunk, dict) and 'content' in chunk:
                writer({"content": chunk['content']})
        
        return Command(
            update={"nova_response": "finished"},
            goto=END
        )
    except Exception as e:
        logger.error(f"Error in _acquire_chat_stream: {str(e)}")
        return Command(
            update={"nova_response": "抱歉，处理您的请求时出现了错误。"},
            goto=END
        )

async def _get_new_message(state: MainState, config: RunnableConfig):
    """获取新消息（简化版本）"""
    return {
        "new_messages": []
    }

async def _process_message(state: MainState, config: RunnableConfig):
    """处理消息（简化版本）"""
    return {
        "new_messages": []
    }

async def _send_event(state: MainState, config: RunnableConfig):
    """发送事件（简化版本）"""
    return {
        "event_sent": True
    }

# 创建StateGraph
builder = StateGraph(MainState, config_schema=Configuration)

# 添加节点
builder.add_node("acquire_chat_stream", _acquire_chat_stream)
builder.add_node("get_new_message", _get_new_message)
builder.add_node("process_message", _process_message)
builder.add_node("send_event", _send_event)

# 添加边
builder.add_edge(START, "acquire_chat_stream")
builder.add_edge("acquire_chat_stream", END)