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

from agents.states.main_state import MainState, Message, UserInputCompletion
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.prompts.main_prompt import user_input_completion_prompt

logger = logging.getLogger(__name__)

async def _check_user_message(state: MainState, config: RunnableConfig):
    check_user_message_at = datetime.now().timestamp()
    user_input = state["user_input"]
    current_message = state.get("current_message", Message(message_segments=[]))
    current_message.message_segments.append(user_input)
    
    logger.info(f"检查用户输入: {"".join(current_message.message_segments)}")

    chat_model = get_chat_model_by_type("basic")

    # output_parser = RemoveFunctionCallOutputParser(pydantic_object=UserInputCompletion)
    # structured_llm = chat_model | output_parser

    # user_input_completion_format = output_parser.get_format_instructions()

    system_instructions = user_input_completion_prompt.format(
            user_messages_segments="\n".join(current_message.message_segments),
        )

    async for chunk in chat_model.astream([
        SystemMessage(content=system_instructions)
    ]):
        if hasattr(chunk, 'content'):
            if "waiting" in chunk.content:
                return Command(
                    update={"aura_response": "waiting",
                            "current_message": current_message,
                            "check_user_message_at": check_user_message_at,
                            "waiting_for_user_message_at": datetime.now().timestamp()},
                    goto="wait_for_user_message"
                )
            elif "ready" in chunk.content:
                return Command(
                    update={"aura_response": "ready",
                            "check_user_message_at": check_user_message_at,
                            "current_message": current_message},
                    goto="response_user_message"
                )

async def _wait_for_user_message(state: MainState, config: RunnableConfig):
    while True:
        await asyncio.sleep(0.1)
        if datetime.now().timestamp() - state["waiting_for_user_message_at"] > 1:
            return Command(
                update={"aura_response": "ready"},
                goto="response_user_message"
            )

async def _response_user_message(state: MainState, config: RunnableConfig):
    """处理聊天流获取"""
    try:
        # 获取用户ID
        user_id = state.get("user_id", "default_user")
        user_message = "\n".join(state["current_message"].message_segments)
        logger.info(f"处理聊天流获取: {user_id} {user_message}")

        chat_model = get_chat_model_by_type("basic")

        # 使用stream方法生成流式响应
        writer = get_stream_writer() 
        async for chunk in chat_model.astream([
            SystemMessage(content=user_message)
        ]):
            if hasattr(chunk, 'content'):
                logger.info(f"处理聊天流获取: {chunk.content}")
                writer({"content": chunk.content})
            elif isinstance(chunk, dict) and 'content' in chunk:
                writer({"content": chunk['content']})
        
        return Command(
            update={"aura_response": "responsed",
                    "current_message": Message(user_message="", message_segments=[])},
            goto="finish_response"
        )
    except Exception as e:
        logger.error(f"Error in _acquire_chat_stream: {str(e)}")
        return Command(
            update={"aura_response": "error"},
            goto="finish_response"
        )

async def _finish_response(state: MainState, config: RunnableConfig):
    """处理聊天流结束"""
    return Command(
        update={"aura_response": "finished"},
        goto=END
    )

# 创建StateGraph
builder = StateGraph(MainState, config_schema=Configuration)

# 添加节点
builder.add_node("check_user_message", _check_user_message)
builder.add_node("response_user_message", _response_user_message)
builder.add_node("wait_for_user_message", _wait_for_user_message)
builder.add_node("finish_response", _finish_response)

# 添加边
builder.add_edge(START, "check_user_message")
