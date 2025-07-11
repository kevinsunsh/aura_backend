import json
import uuid
import time
import asyncio
import re
from enum import Enum
from datetime import datetime
from typing import Literal, Optional, Tuple, Dict, Any, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command

from agents.states.thinking_state import ThinkingTaskState
from agents.configuration.config import GraphConfiguration, get_chat_model_by_type
import logging
from agents.prompts.thinking_prompt import (
    THINKING_GOAL_ANALYZER_PROMPT,
    THINKING_ACTION_PLANNER_PROMPT,
    THINKING_ACTION
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import (
    _get_persona_text,
    _build_chat_history_str,
    _build_goals_str,
    _build_action_history_summary,
    _build_knowledge_info_str
)
from agents.task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)

async def _analyze_goals(state: ThinkingTaskState, config: RunnableConfig):
    """分析对话目标"""
    try:
        if TaskManager.get_instance().get_task_state(TaskType.THINKING) == TaskStateType.PAUSED:
            return Command(goto="wait_for_user_message")
        
        chat_model = get_chat_model_by_type("pfc_action_planner")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        processed_chat_history_str = observing_task_shared_data.get("processed_chat_history_str", "还没有聊天记录。")
        unprocessed_chat_history_str = observing_task_shared_data.get("unprocessed_chat_history_str", "还没有聊天记录。")
        logger.info(f"analyze_goals unprocessed_chat_history_str: {unprocessed_chat_history_str}")
        logger.info(f"analyze_goals processed_chat_history_str: {processed_chat_history_str}")

        thinking_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.THINKING)
        goals_str = thinking_task_shared_data.get("goals_str", "")
        logger.info(f"analyze_goals begin goals_str: {goals_str}")
        knowledge_info_str = thinking_task_shared_data.get("knowledge_info_str", "")

        # 格式化提示词
        prompt = THINKING_GOAL_ANALYZER_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            processed_chat_history_str=processed_chat_history_str,
            unprocessed_chat_history_str=unprocessed_chat_history_str,
            bot_name="aura",
            user_name=state.get("user_id", "")
        )
        
        # 调用LLM分析目标
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        # 使用正则表达式提取 [] 格式的JSON数组
        json_match = re.search(r'\[.*?\]', response)
        if json_match:
            json_str = json_match.group(0)
            try:
                goals_data = json.loads(json_str)
                if isinstance(goals_data, list):
                    goals = goals_data
                else:
                    goals = [goals_data]
            except json.JSONDecodeError:
                logger.warning("目标分析响应不是有效的JSON格式")
                goals = []
        else:
            # 如果没有找到 [] 格式，尝试匹配 {} 格式的JSON对象
            json_obj_match = re.search(r'\{.*?\}', response)
            if json_obj_match:
                json_str = json_obj_match.group(0)
                try:
                    goals_data = json.loads(json_str)
                    goals = [goals_data]  # 将单个对象包装成列表
                except json.JSONDecodeError:
                    logger.warning("目标分析响应不是有效的JSON格式")
                    goals = []
            else:
                # 如果都没有找到，尝试直接解析整个响应
                try:
                    goals_data = json.loads(response)
                    if isinstance(goals_data, list):
                        goals = goals_data
                    else:
                        goals = [goals_data]
                except json.JSONDecodeError:
                    logger.warning("目标分析响应不是有效的JSON格式")
                    goals = []
        
        # 更新状态
        goals_str = _build_goals_str(goals)
        logger.info(f"analyze_goals end goals_str: {goals_str}")
        await TaskManager.get_instance().set_task_shared_data(TaskType.THINKING, {
            "goals_str": goals_str,
            "knowledge_info_str": ""
        })
        await asyncio.sleep(1)
        return Command(goto=END)
    except Exception as e:
        logger.error(f"分析对话目标时出错: {str(e)}")
        return Command(
            goto=END
        )

# 创建StateGraph
builder = StateGraph(ThinkingTaskState, config_schema=GraphConfiguration)

# 添加后台任务节点
builder.add_node("analyze_goals", _analyze_goals)

# 添加边
builder.add_edge(START, "analyze_goals")
