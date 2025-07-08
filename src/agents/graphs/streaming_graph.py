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
    FRONTEND_REPLY_GENERATOR_FOLLOW_UP_PROMPT,
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
        configurable = Configuration.from_runnable_config(config)
        # if TaskManager.get_instance().get_streaming_action().action_type == StreamingActionType.WAITING:
        #     return Command(goto="wait_for_user_message")

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
        if chat_stream.chatstream_checked_at > now_timestamp - 60:
            recent_processed_messages = configurable.message_store.get_messages_by_time_range(
                chat_id, 
                now_timestamp - 60, 
                chat_stream.chatstream_checked_at
            )
        else:
            recent_processed_messages = []

        last_bot_message_time = configurable.message_store.get_recent_messages(user_id="aura", limit=1)[0].created_at
        last_user_message_time = configurable.message_store.get_recent_messages(user_id=user_id, limit=1)[0].created_at

        # 更新观察信息
        unprocessed_chat_history_str = _build_chat_history_str(unprocessed_messages)
        logger.info(f"observe_conversation unprocessed_chat_history_str: {unprocessed_chat_history_str}")
        processed_chat_history_str = _build_chat_history_str(recent_processed_messages)
        logger.info(f"observe_conversation processed_chat_history_str: {processed_chat_history_str}")

        return Command(
            update={
                "processed_chat_history_str": processed_chat_history_str,
                "unprocessed_chat_history_str": unprocessed_chat_history_str,
                "last_bot_message_time": last_bot_message_time,
                "last_user_message_time": last_user_message_time
            },
            goto="plan_action"
        )
    
    except Exception as e:
        logger.error(f"观察对话状态时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _plan_action(state: StreamingTaskState, config: RunnableConfig):
    """规划下一步行动"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        action_history_summary = _build_action_history_summary(state.get("action_history", []))
        
        # 构建时间和超时信息
        time_since_last_bot_message_info = ""
        last_bot_time = state.get("last_bot_message_time", None)
        if last_bot_time:
            time_diff = datetime.now().timestamp() - last_bot_time / 1000
            if time_diff < 60.0:
                time_since_last_bot_message_info = f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。"
            else:
                time_since_last_bot_message_info = "提示：你已经很久没说话了。"
        
        timeout_context = ""
        last_user_time = state.get("last_user_message_time", None)
        if last_user_time:
            if last_bot_time > last_user_time:
                time_diff = datetime.now().timestamp() - last_user_time / 1000
                timeout_context = f"重要提示：对方已经{time_diff:.1f}秒没有回复你的消息了,请基于此情况规划下一步。"
                if time_diff > 60.0:
                    timeout_context = "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。"
            else:
                time_diff = datetime.now().timestamp() - last_bot_time / 1000
                timeout_context = f"重要提示：你已经{time_diff:.1f}秒没有回复对方了，请基于此情况规划下一步。"
                if time_diff > 60.0:
                    timeout_context = "重要提示：你已经很长时间没有回复对方了，请基于此情况规划下一步。"
        
        unprocessed_chat_history_str = state.get("unprocessed_chat_history_str", "还没有聊天记录。")
        processed_chat_history_str = state.get("processed_chat_history_str", "还没有聊天记录。")
        last_successful_reply_action = state.get("streaming_current_action")
        
        goals_str = _build_goals_str(state.get("goals", state.get("goals", [])))
        logger.info(f"plan_action goals_str: {goals_str}")
        knowledge_info_str = _build_knowledge_info_str(state.get("knowledge_list", []))

        # 选择提示词模板
        action_str = ""
        if last_successful_reply_action in ["direct_reply", "send_new_message"]:
            action_str = FRONTEND_FOLLOW_UP_ACTION
        else:
            action_str = FRONTEND_INITIAL_ACTION
        
        # logger.info(f"plan_action action_str: {action_str}")
        # 格式化提示词
        prompt = FRONTEND_ACTION_PLANNER_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            action_history_summary=action_history_summary,
            time_since_last_bot_message_info=time_since_last_bot_message_info,
            timeout_context=timeout_context,
            processed_chat_history_str=processed_chat_history_str,
            unprocessed_chat_history_str=unprocessed_chat_history_str,
            action_str = action_str,
            bot_name="aura",
            user_name=state.get("user_id", "")
        )
        
        # 调用LLM规划行动
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)], extra_body={"thinking": {"type": "disabled"}}):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        # 解析JSON响应
        try:
            action_data = json.loads(response)
            action = action_data.get("action", "wait")
            reason = action_data.get("reason", "")
            logger.info(f"plan_action action: {action}, reason: {reason}")
        except json.JSONDecodeError:
            logger.warning("行动规划响应不是有效的JSON格式")
            action = "wait"
            reason = "解析响应失败，默认等待"
        
        # 更新状态
        return Command(
            update={
                "streaming_current_action": action,
                "streaming_action_reason": reason
            },
            goto="execute_action"
        )
    except Exception as e:
        logger.error(f"规划行动时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _execute_action(state: StreamingTaskState, config: RunnableConfig):
    """执行规划的行动"""
    try:
        action_type = state.get("streaming_current_action")
        if not action_type:
            return Command(goto="wait_for_user_message")
        
        # 根据行动类型执行不同的逻辑
        if action_type == "direct_reply":
            return Command(goto="generate_reply", update={
                "streaming_last_successful_reply_action": "direct_reply"
            })
        elif action_type == "send_new_message":
            return Command(goto="generate_reply", update={
                "streaming_last_successful_reply_action": "send_new_message"
            })
        elif action_type == "listening":
            return Command(goto="wait_for_user_message")
        elif action_type == "wait":
            return Command(goto="wait_for_user_message")
        else:
            # 默认等待
            return Command(goto="wait_for_user_message")
    except Exception as e:
        logger.error(f"执行行动时出错: {str(e)}")
        return Command(goto=END)
        
async def _wait_for_user_message(state: StreamingTaskState, config: RunnableConfig):
    """等待用户输入"""
    await asyncio.sleep(3)
    return Command(goto=END)

async def _generate_reply(state: StreamingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        configurable = Configuration.from_runnable_config(config)
        # 使用LLM生成立即回复
        chat_model = get_chat_model_by_type("basic")
        
        persona_text = _get_persona_text()
        
        # 使用从checkpoint获取的共享变量，如果没有则使用state中的默认值
        # goals = state.get("goals", state.get("goals", []))
        # goals_str = _build_goals_str(goals)
        goals_str = ""
        # knowledge_list = state.get("knowledge_list", [])
        # knowledge_info_str = _build_knowledge_info_str(knowledge_list)
        knowledge_info_str = ""
        unprocessed_chat_history_str = state.get("unprocessed_chat_history_str", "还没有聊天记录。")
        processed_chat_history_str = state.get("processed_chat_history_str", "还没有聊天记录。")
        
        # 格式化提示词
        if state.get("streaming_current_action") == "direct_reply":
            prompt = FRONTEND_REPLY_GENERATOR_DIRECT_PROMPT.format(
                persona_text=persona_text,
                goals_str=goals_str,
                knowledge_info_str=knowledge_info_str,
                processed_chat_history_str=processed_chat_history_str,
                unprocessed_chat_history_str=unprocessed_chat_history_str
            )
        elif state.get("streaming_current_action") == "send_new_message":
            prompt = FRONTEND_REPLY_GENERATOR_FOLLOW_UP_PROMPT.format(
                persona_text=persona_text,
                goals_str=goals_str,
                knowledge_info_str=knowledge_info_str,
                processed_chat_history_str=processed_chat_history_str,
                unprocessed_chat_history_str=unprocessed_chat_history_str
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
                final_response += chunk.content
                writer({"content": chunk.content})
                if TaskManager.get_instance().get_streaming_action().action_type == StreamingActionType.WAITING:
                    logger.info(f"打断流式响应，继续倾听")  
                    break
        
        configurable.chat_stream_manager.update_chat_stream_checked_at(state["chat_id"])
        # 保存消息到数据库
        configurable.message_store.add_message(Message(
            msg_id=str(uuid.uuid4()),
            chat_id=state["chat_id"],
            user_id="aura",
            platform="default",
            m_type="text",
            content=final_response,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        ))
        return Command(goto=END, update={
            "aura_response": "finished"
        })            
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(goto=END)            

# 创建前台状态机图
builder = StateGraph(StreamingTaskState, config_schema=Configuration)

# 添加节点
builder.add_node("observe_conversation", _observe_conversation)
builder.add_node("plan_action", _plan_action)
builder.add_node("execute_action", _execute_action)
builder.add_node("waiting", _wait_for_user_message)
builder.add_node("generate_reply", _generate_reply)

# 添加边
builder.add_edge(START, "observe_conversation")

