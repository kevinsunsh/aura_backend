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

from agents.states.main_state import MainState, UserInputCompletion
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.prompts.main_prompt import user_input_completion_prompt
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point

logger = logging.getLogger(__name__)

async def _check_user_message(state: MainState, config: RunnableConfig):
    chat_id = state["chat_id"]
    configurable = Configuration.from_runnable_config(config)
    messages = configurable.message_store.get_messages_by_time_range(chat_id, configurable.chat_stream.chatstream_checked_at, int(datetime.now().timestamp() * 1000))
    chat_model = get_chat_model_by_type("basic")
    current_message = "\n".join([m.content for m in messages])

    # output_parser = RemoveFunctionCallOutputParser(pydantic_object=UserInputCompletion)
    # structured_llm = chat_model | output_parser

    # user_input_completion_format = output_parser.get_format_instructions()

    system_instructions = user_input_completion_prompt.format(
            user_messages_segments=current_message,
        )
    check_user_message_point_id = start_performance_point("检查用户消息")
    async for chunk in chat_model.astream([
        SystemMessage(content=system_instructions)
    ]):
        if hasattr(chunk, 'content'):
            if "waiting" in chunk.content:
                end_performance_point(check_user_message_point_id)
                return Command(
                    update={"aura_response": "waiting",
                            "current_message": current_message,
                            "waiting_for_user_message_at": datetime.now().timestamp()},
                    goto="wait_for_user_message"
                )
            elif "ready" in chunk.content:
                end_performance_point(check_user_message_point_id)
                return Command(
                    update={"aura_response": "ready",
                            "current_message": current_message},
                    goto="response_user_message"
                )

async def _wait_for_user_message(state: MainState, config: RunnableConfig):
    while True:
        await asyncio.sleep(1)
        if datetime.now().timestamp() - state["waiting_for_user_message_at"] > 1:
            return Command(
                update={"aura_response": "ready"},
                goto="response_user_message"
            )

async def _response_user_message(state: MainState, config: RunnableConfig):
    """处理聊天流"""
    try:
        # 获取用户ID
        chat_id = state["chat_id"]
        configurable = Configuration.from_runnable_config(config)
        logger.info(f"处理聊天流: {chat_id} {state['current_message']}")

        chat_model = get_chat_model_by_type("basic")
        final_response = ""
        # 使用stream方法生成流式响应
        writer = get_stream_writer() 
        response_user_message_point_id = start_performance_point("处理聊天流")
        async for chunk in chat_model.astream([
            SystemMessage(content=state["current_message"])
        ]):
            if hasattr(chunk, 'content'):
                # logger.info(f"流式响应: {chunk.content}")
                end_performance_point(response_user_message_point_id)
                final_response += chunk.content
                writer({"content": chunk.content})
            elif isinstance(chunk, dict) and 'content' in chunk:
                writer({"content": chunk['content']})

        logger.info(f"流式响应完成: {final_response}")
        configurable.message_store.add_message(Message(
                                                msg_id=str(uuid.uuid4()),
                                                chat_id=chat_id,
                                                user_id="aura",
                                                platform="default",
                                                m_type="text",
                                                content=final_response,
                                                data={},
                                                created_at=int(datetime.now().timestamp() * 1000)))
        configurable.chat_stream_manager.update_chat_stream_checked_at(chat_id)
        return Command(
            update={"aura_response": "finished"},
            goto=END
        )
    except Exception as e:
        logger.error(f"Error in _acquire_chat_stream: {str(e)}")
        return Command(
            update={"aura_response": "error"},
            goto=END
        )

# 创建StateGraph
builder = StateGraph(MainState, config_schema=Configuration)

# 添加节点
builder.add_node("check_user_message", _check_user_message)
builder.add_node("response_user_message", _response_user_message)
builder.add_node("wait_for_user_message", _wait_for_user_message)

# 添加边
builder.add_edge(START, "check_user_message")
