import uuid
import asyncio
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer

from agents.states.quick_state import QuickState
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.quick_prompt import quick_response_prompt
from utils.utils import start_performance_point, end_performance_point

logger = logging.getLogger(__name__)

async def _quick_response(state: QuickState, config: RunnableConfig):
    try:
        chat_id = state["chat_id"]
        configurable = Configuration.from_runnable_config(config)
        messages = configurable.message_store.get_messages_by_time_range(chat_id, configurable.chat_stream.chatstream_checked_at, int(datetime.now().timestamp() * 1000))
        chat_model = get_chat_model_by_type("basic")
        current_message = "\n".join([m.content for m in messages])

        # output_parser = RemoveFunctionCallOutputParser(pydantic_object=UserInputCompletion)
        # structured_llm = chat_model | output_parser

        # user_input_completion_format = output_parser.get_format_instructions()

        system_instructions = quick_response_prompt.format(
                user_messages_segments=current_message,
            )
        writer = get_stream_writer()
        quick_response_point_id = start_performance_point("快速响应")
        async for chunk in chat_model.astream([
            SystemMessage(content=system_instructions)
        ]):
            if hasattr(chunk, 'content'):
                end_performance_point(quick_response_point_id)
                logger.info(f"快速响应流式响应: {chunk.content}")
                writer({"content": chunk.content})

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
builder = StateGraph(QuickState, config_schema=Configuration)

# 添加节点
builder.add_node("quick_response", _quick_response)

# 添加边
builder.add_edge(START, "quick_response")
