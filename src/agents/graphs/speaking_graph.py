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

from agents.states.speaking_state import SpeakingTaskState
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.speaking_prompt import (
    SPEAKING_ACTION_PLANNER_PROMPT,
    SPEAKING_GENERATOR_FOLLOW_UP_PROMPT
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import (
    _get_persona_text,
    _build_action_history_summary
)
from agents.task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)
reply_max_latency = 30
history_check_interval = 60

async def _plan_action(state: SpeakingTaskState, config: RunnableConfig):
    """规划下一步行动"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        action_history_summary = _build_action_history_summary(state.get("action_history", []))
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        processed_chat_history_str = observing_task_shared_data.get("processed_chat_history_str", "还没有聊天记录。")
        unprocessed_chat_history_str = observing_task_shared_data.get("unprocessed_chat_history_str", "还没有聊天记录。")
        last_bot_message_time = observing_task_shared_data.get("last_bot_message_time", None)
        last_user_message_time = observing_task_shared_data.get("last_user_message_time", None)
        
        # 构建时间和超时信息
        time_since_last_bot_message_info = ""
        if last_bot_message_time:
            time_diff = datetime.now().timestamp() - last_bot_message_time / 1000
            if time_diff < reply_max_latency:
                time_since_last_bot_message_info = f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。"
            else:
                time_since_last_bot_message_info = "提示：你已经很久没说话了。"
        
        timeout_context = ""
        if last_user_message_time:
            if last_bot_message_time > last_user_message_time:
                time_diff = datetime.now().timestamp() - last_user_message_time / 1000
                timeout_context = f"重要提示：对方已经{time_diff:.1f}秒没有回复你的消息了,请基于此情况规划下一步。"
                if time_diff > reply_max_latency:
                    timeout_context = "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。"
            else:
                time_diff = datetime.now().timestamp() - last_bot_message_time / 1000
                timeout_context = f"重要提示：你已经{time_diff:.1f}秒没有回复对方了，请基于此情况规划下一步。"
                if time_diff > reply_max_latency:
                    timeout_context = "重要提示：你已经很长时间没有回复对方了，请基于此情况规划下一步。"
        
        thinking_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.THINKING)
        goals_str = thinking_task_shared_data.get("goals_str", "")
        knowledge_info_str = thinking_task_shared_data.get("knowledge_info_str", "")
        logger.info(f"plan_action goals_str: {goals_str}")

        # logger.info(f"plan_action action_str: {action_str}")
        # 格式化提示词
        prompt = SPEAKING_ACTION_PLANNER_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            action_history_summary=action_history_summary,
            time_since_last_bot_message_info=time_since_last_bot_message_info,
            timeout_context=timeout_context,
            processed_chat_history_str=processed_chat_history_str,
            unprocessed_chat_history_str=unprocessed_chat_history_str,
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
                "current_action": action,
                "action_reason": reason,
                "processed_chat_history_str": processed_chat_history_str,
                "unprocessed_chat_history_str": unprocessed_chat_history_str,
                "last_bot_message_time": last_bot_message_time,
                "last_user_message_time": last_user_message_time,
                "goals_str": goals_str,
                "knowledge_info_str": knowledge_info_str
            },
            goto="execute_action"
        )
    except Exception as e:
        logger.error(f"规划行动时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _execute_action(state: SpeakingTaskState, config: RunnableConfig):
    """执行规划的行动"""
    try:
        action_type = state.get("current_action")
        if not action_type:
            return Command(goto="wait_for_user_message")
        
        # 根据行动类型执行不同的逻辑
        if action_type == "send_new_message":
            return Command(goto="generate_new_message")
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
        
async def _wait_for_user_message(state: SpeakingTaskState, config: RunnableConfig):
    """等待用户输入"""
    await asyncio.sleep(3)
    return Command(goto=END)

async def _generate_new_message(state: SpeakingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.STOPPED)
        
        configurable = Configuration.from_runnable_config(config)
        # 使用LLM生成立即回复
        chat_model = get_chat_model_by_type("basic")
        
        persona_text = _get_persona_text()
        
        # 使用从checkpoint获取的共享变量，如果没有则使用state中的默认值
        goals_str = state.get("goals_str", "")
        knowledge_info_str = state.get("knowledge_info_str", "")
        unprocessed_chat_history_str = state.get("unprocessed_chat_history_str", "还没有聊天记录。")
        processed_chat_history_str = state.get("processed_chat_history_str", "还没有聊天记录。")
        
        # 格式化提示词
        prompt = SPEAKING_GENERATOR_FOLLOW_UP_PROMPT.format(
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
                if TaskManager.get_instance().get_task_state(TaskType.SPEAKING) == TaskStateType.PAUSED:
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
        if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.STOPPED:
            TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.RUNNING)
        return Command(goto=END, update={
            "speaking_response": "finished"
        })            
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(goto=END, update={
            "speaking_response": "error"
        })            

# 创建前台状态机图
builder = StateGraph(SpeakingTaskState, config_schema=Configuration)

# 添加节点
builder.add_node("plan_action", _plan_action)
builder.add_node("execute_action", _execute_action)
builder.add_node("waiting", _wait_for_user_message)
builder.add_node("generate_reply", _generate_new_message)

# 添加边
builder.add_edge(START, "plan_action")

