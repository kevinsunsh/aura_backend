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

from agents.states.thinking_state import BackgroundState, BackgroundActionType
from agents.task_manager import StreamingActionType
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.thinking_prompt import (
    BACKGROUND_GOAL_ANALYZER_PROMPT,
    BACKGROUND_ACTION_PLANNER_INITIAL_PROMPT,
    BACKGROUND_ACTION_PLANNER_FOLLOW_UP_PROMPT,
    BACKGROUND_KNOWLEDGE_FETCHER_PROMPT,
    BACKGROUND_REPLY_GENERATOR_DIRECT_PROMPT,
    BACKGROUND_REPLY_GENERATOR_FOLLOW_UP_PROMPT,
    BACKGROUND_REPLY_GENERATOR_FAREWELL_PROMPT,
    BACKGROUND_REPLY_CHECKER_PROMPT,
    BACKGROUND_END_DECISION_PROMPT,
    BACKGROUND_ERROR_HANDLING_PROMPT,
    BACKGROUND_FRONTEND_CONTROL_PROMPT
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.shared_checkpoint_utils import get_shared_variables_from_checkpoint, update_shared_variables_to_checkpoint

logger = logging.getLogger(__name__)

# 工具函数
def _build_goals_str(goals: List[Dict[str, str]]) -> str:
    """构建目标字符串"""
    if not goals:
        return "- 目前没有明确对话目标\n"
    
    goals_str = ""
    for goal_reason in goals:
        goal = goal_reason.get("goal", "目标内容缺失")
        reasoning = goal_reason.get("reasoning", "没有明确原因")
        goals_str += f"- 目标：{goal}\n  原因：{reasoning}\n"
    return goals_str

def _build_knowledge_info_str(knowledge_list: List[Dict[str, str]]) -> str:
    """构建知识信息字符串"""
    knowledge_info_str = "【供参考的相关知识和记忆】\n"
    try:
        if knowledge_list:
            # 最多只显示最近的 5 条知识
            recent_knowledge = knowledge_list[-5:]
            for i, knowledge_item in enumerate(recent_knowledge):
                query = knowledge_item.get("query", "未知查询")
                knowledge = knowledge_item.get("knowledge", "无知识内容")
                source = knowledge_item.get("source", "未知来源")
                # 只取知识内容的前 2000 个字
                knowledge_snippet = knowledge[:2000] + "..." if len(knowledge) > 2000 else knowledge
                knowledge_info_str += f"{i + 1}. 关于 '{query}' (来源: {source}): {knowledge_snippet}\n"
        else:
            knowledge_info_str += "- 暂无。\n"
    except Exception as e:
        logger.error(f"构建知识信息字符串时出错: {e}")
        knowledge_info_str += "- 处理知识列表时出错。\n"
    
    return knowledge_info_str

def _build_action_history_summary(action_history: List[str]) -> str:
    """构建行动历史概要"""
    if not action_history:
        return "暂无行动历史。\n"
    
    # 取最近5条行动
    recent_actions = action_history[-5:]
    summary = "最近行动历史：\n"
    for i, action in enumerate(recent_actions):
        summary += f"{i + 1}. {action}\n"
    return summary

# 后台任务节点函数
async def _observe_conversation(state: BackgroundState, config: RunnableConfig):
    """观察对话状态"""
    try:
        chat_id = state["chat_id"]
        configurable = Configuration.from_runnable_config(config)
        
        # 获取新消息
        now_timestamp = int(datetime.now().timestamp() * 1000)
        messages = configurable.message_store.get_messages_by_time_range(
            chat_id, 
            configurable.chat_stream.chatstream_checked_at, 
            now_timestamp
        )
        
        # 更新观察信息
        new_messages_count = len(messages)
        chat_history_str = "\n".join([m.content for m in messages])
        
        # 构建未处理消息列表
        unprocessed_messages = []
        for msg in messages:
            unprocessed_messages.append({
                "message_id": msg.msg_id,
                "content": msg.content,
                "user_id": msg.user_id,
                "created_at": msg.created_at
            })
        
        return Command(
            update={
                "new_messages_count": new_messages_count,
                "chat_history_str": chat_history_str,
                "unprocessed_messages": unprocessed_messages
            },
            goto="observe_conversation"
        )
    except Exception as e:
        logger.error(f"观察对话状态时出错: {str(e)}")
        return Command(
            goto="observe_conversation"
        )

# 创建StateGraph
builder = StateGraph(BackgroundState, config_schema=Configuration)

# 添加后台任务节点
builder.add_node("observe_conversation", _observe_conversation)

# 添加边
builder.add_edge(START, "observe_conversation")
