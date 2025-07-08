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
from agents.task_manager import StreamingActionType, ThinkingActionType
from agents.configuration import Configuration, get_chat_model_by_type
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
from agents.task_manager import TaskManager

logger = logging.getLogger(__name__)

async def _analyze_goals(state: ThinkingTaskState, config: RunnableConfig):
    """分析对话目标"""
    try:
        if TaskManager.get_instance().get_thinking_action().action_type == ThinkingActionType.WAITING:
            return Command(goto="wait_for_user_message")

        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        goals_str = _build_goals_str(state.get("goals", []))
        logger.info(f"analyze_goals begin goals_str: {goals_str}")
        action_history_text = _build_action_history_summary(state.get("action_history", []))
        unprocessed_chat_history_text = state.get("unprocessed_chat_history_str", "")
        processed_chat_history_text = state.get("processed_chat_history_str", "还没有聊天记录。")

        # 格式化提示词
        prompt = THINKING_GOAL_ANALYZER_PROMPT.format(
            persona_text=persona_text,
            action_history_text=action_history_text,
            goals_str=goals_str,
            chat_history_text=processed_chat_history_text + "\n" + unprocessed_chat_history_text,
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
        current_goal = goals[0].get("goal", "") if goals else ""
        logger.info(f"analyze_goals end goals_str: {_build_goals_str(goals)}")
        await asyncio.sleep(1)
        return Command(
            update={
                "goals": goals,
                "current_goal": current_goal
            },
            goto=END
        )
    except Exception as e:
        logger.error(f"分析对话目标时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _plan_action(state: ThinkingTaskState, config: RunnableConfig):
    """规划下一步行动"""
    try:
        configurable = Configuration.from_runnable_config(config)
        chat_model = get_chat_model_by_type("reasoning")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        goals_str = _build_goals_str(state.get("goals", []))
        knowledge_info_str = _build_knowledge_info_str(state.get("knowledge_list", []))
        action_history_summary = _build_action_history_summary(state.get("action_history", []))

        processed_chat_history_text = state.get("processed_chat_history_str", "")
        unprocessed_chat_history_text = state.get("unprocessed_chat_history_str", "还没有聊天记录。")

        # 格式化提示词
        prompt = THINKING_ACTION_PLANNER_PROMPT.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            action_history_summary=action_history_summary,
            chat_history_text=processed_chat_history_text + "\n" + unprocessed_chat_history_text,
            action_str = THINKING_ACTION
        )
        
        # 调用LLM规划行动
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        # 解析JSON响应
        try:
            action_data = json.loads(response)
            action = action_data.get("action", "wait")
            reason = action_data.get("reason", "")
        except json.JSONDecodeError:
            logger.warning("行动规划响应不是有效的JSON格式")
            action = "wait"
            reason = "解析响应失败，默认等待"
        
        # 更新状态
        return Command(
            update={
                "thinking_current_action": action,
                "thinking_action_reason": reason
            },
            goto="execute_action"
        )
    except Exception as e:
        logger.error(f"规划行动时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _execute_action(state: ThinkingTaskState, config: RunnableConfig):
    """执行规划的行动"""
    try:
        action = state.get("thinking_current_action")
        if not action:
            return Command(goto="wait_for_user_message")
        
        # 根据行动类型执行不同的逻辑
        if action == "fetch_knowledge":
            return Command(goto="fetch_knowledge")
        elif action == "wait":
            return Command(goto="wait_for_user_message")
        elif action == "rethink_goal":
            return Command(goto="analyze_goals")
        else:
            # 默认等待
            return Command(goto="wait_for_user_message")
    except Exception as e:
        logger.error(f"执行行动时出错: {str(e)}")
        return Command(goto=END)

async def _fetch_knowledge(state: ThinkingTaskState, config: RunnableConfig):
    """获取知识"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        chat_history_text = state.get("chat_history_str", "")
        goals_str = _build_goals_str(state.get("goals", []))
        
        # 这里可以扩展为从实际知识库获取信息
        # 目前使用模拟的知识获取
        knowledge_item = {
            "query": "用户查询",
            "knowledge": "这是从知识库获取的相关信息",
            "source": "知识库"
        }
        
        knowledge_list = state.get("knowledge_list", [])
        knowledge_list.append(knowledge_item)
        
        return Command(
            update={
                "knowledge_list": knowledge_list
            },
            goto=END
        )
    except Exception as e:
        logger.error(f"获取知识时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _wait_for_user_message(state: ThinkingTaskState, config: RunnableConfig):
    """等待用户消息"""
    try:
        # 等待一段时间后重新观察
        await asyncio.sleep(3)
        
        return Command(
            goto=END
        )
    except Exception as e:
        logger.error(f"等待用户消息时出错: {str(e)}")
        return Command(
            goto=END
        )

# 创建StateGraph
builder = StateGraph(ThinkingTaskState, config_schema=Configuration)

# 添加后台任务节点
builder.add_node("analyze_goals", _analyze_goals)
builder.add_node("plan_action", _plan_action)
builder.add_node("execute_action", _execute_action)
builder.add_node("fetch_knowledge", _fetch_knowledge)
builder.add_node("wait_for_user_message", _wait_for_user_message)

# 添加边
builder.add_edge(START, "analyze_goals")
