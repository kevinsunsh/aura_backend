"""
DEPRECATED: 此文件已被废弃

main_graph.py 已被前台后台任务架构替代：
- 前台任务：frontend_graph.py - 负责快速响应和状态切换
- 后台任务：background_graph.py - 负责深度分析和内容生成
- 协调器：coordinator.py - 管理前台后台任务的异步执行

新的架构提供了更好的：
1. 响应性：前台任务可以快速响应用户输入
2. 并发性：前台后台任务可以并行执行
3. 可扩展性：可以独立扩展前台和后台功能
4. 可维护性：功能分离，职责清晰

请使用新的前台后台任务架构，而不是此文件。
"""

import json
import uuid
import asyncio
import time
from datetime import datetime
from typing import Literal, Optional, Tuple, Dict, Any, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.documents import Document

from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer

from agents.states.main_state import MainState, ConversationState, ActionType, UserInputCompletion
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.prompts.main_prompt import (
    user_input_completion_prompt,
    PFC_ACTION_PLANNER_INITIAL_PROMPT,
    PFC_ACTION_PLANNER_FOLLOW_UP_PROMPT,
    PFC_END_DECISION_PROMPT,
    PFC_GOAL_ANALYZER_PROMPT,
    PFC_REPLY_GENERATOR_DIRECT_PROMPT,
    PFC_REPLY_GENERATOR_FOLLOW_UP_PROMPT,
    PFC_REPLY_GENERATOR_FAREWELL_PROMPT,
    PFC_KNOWLEDGE_FETCHER_PROMPT,
    PFC_REPLY_CHECKER_PROMPT
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point

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

def _get_persona_text() -> str:
    """获取人设文本"""
    # 这里可以从配置中获取人设信息
    return "你的名字是Aura，你是一个智能助手，性格温和友善，喜欢帮助用户解决问题。"

def _check_reply_similarity(reply: str, last_bot_messages: List[str]) -> Tuple[bool, str]:
    """检查回复与历史消息的相似度
    
    Args:
        reply: 待检查的回复
        last_bot_messages: 最近的机器人消息列表
        
    Returns:
        Tuple[bool, str]: (是否通过检查, 原因)
    """
    if not last_bot_messages:
        return True, "没有历史消息可比较"
    
    # 检查是否与最近的消息完全相同
    if reply == last_bot_messages[0]:
        return False, "回复与上一条消息完全相同"
    
    # 检查相似度
    try:
        import difflib
        similarity_ratio = difflib.SequenceMatcher(None, reply, last_bot_messages[0]).ratio()
        similarity_threshold = 0.9
        
        if similarity_ratio > similarity_threshold:
            return False, f"回复与上一条消息高度相似 (相似度 {similarity_ratio:.2f})"
        
        return True, f"相似度检查通过 (相似度 {similarity_ratio:.2f})"
    except Exception as e:
        logger.warning(f"相似度检查出错: {e}")
        return True, "相似度检查失败，默认通过"

def _update_bot_messages(state: MainState, new_message: str) -> List[str]:
    """更新机器人消息列表
    
    Args:
        state: 当前状态
        new_message: 新消息
        
    Returns:
        List[str]: 更新后的消息列表
    """
    last_bot_messages = state.get("last_bot_messages", [])
    last_bot_messages.append(new_message)
    
    # 只保留最近3条消息
    if len(last_bot_messages) > 3:
        last_bot_messages = last_bot_messages[-3:]
    
    return last_bot_messages

# PFC节点函数

async def _observe_conversation(state: MainState, config: RunnableConfig):
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
                "conversation_state": ConversationState.ANALYZING,
                "new_messages_count": new_messages_count,
                "chat_history_str": chat_history_str,
                "unprocessed_messages": unprocessed_messages
            },
            goto="analyze_goals"
        )
    except Exception as e:
        logger.error(f"观察对话状态时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _analyze_goals(state: MainState, config: RunnableConfig):
    """分析对话目标"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        goals_str = _build_goals_str(state.get("goals", []))
        action_history_text = _build_action_history_summary(state.get("action_history", []))
        chat_history_text = state.get("chat_history_str", "还没有聊天记录。")
        
        # 格式化提示词
        prompt = PFC_GOAL_ANALYZER_PROMPT.format(
            persona_text=persona_text,
            action_history_text=action_history_text,
            goals_str=goals_str,
            chat_history_text=chat_history_text
        )
        
        # 调用LLM分析目标
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        # 解析JSON响应
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
        
        return Command(
            update={
                "conversation_state": ConversationState.PLANNING,
                "goals": goals,
                "current_goal": current_goal
            },
            goto="plan_action"
        )
    except Exception as e:
        logger.error(f"分析对话目标时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _plan_action(state: MainState, config: RunnableConfig):
    """规划下一步行动"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        goals_str = _build_goals_str(state.get("goals", []))
        knowledge_info_str = _build_knowledge_info_str(state.get("knowledge_list", []))
        action_history_summary = _build_action_history_summary(state.get("action_history", []))
        
        # 构建时间和超时信息
        time_since_last_bot_message_info = ""
        last_bot_time = state.get("last_bot_message_time")
        if last_bot_time:
            time_diff = time.time() - last_bot_time
            if time_diff < 60.0:
                time_since_last_bot_message_info = f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。\n"
        
        timeout_context = ""
        goals = state.get("goals", [])
        if goals:
            last_goal = goals[-1]
            if isinstance(last_goal, dict) and "goal" in last_goal:
                last_goal_text = last_goal["goal"]
                if "分钟，思考接下来要做什么" in last_goal_text:
                    timeout_context = "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
        
        chat_history_text = state.get("chat_history_str", "还没有聊天记录。")
        last_successful_reply_action = state.get("last_successful_reply_action")
        
        # 选择提示词模板
        if last_successful_reply_action in ["direct_reply", "send_new_message"]:
            prompt_template = PFC_ACTION_PLANNER_FOLLOW_UP_PROMPT
        else:
            prompt_template = PFC_ACTION_PLANNER_INITIAL_PROMPT
        
        # 格式化提示词
        prompt = prompt_template.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            action_history_summary=action_history_summary,
            last_action_context="",  # 可以扩展这个字段
            time_since_last_bot_message_info=time_since_last_bot_message_info,
            timeout_context=timeout_context,
            chat_history_text=chat_history_text
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
                "conversation_state": ConversationState.GENERATING,
                "current_action": ActionType(action),
                "action_reason": reason
            },
            goto="execute_action"
        )
    except Exception as e:
        logger.error(f"规划行动时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _execute_action(state: MainState, config: RunnableConfig):
    """执行规划的行动"""
    try:
        action = state.get("current_action")
        if not action:
            return Command(goto="wait_for_user_message")
        
        action_type = action.value if hasattr(action, 'value') else str(action)
        
        # 根据行动类型执行不同的逻辑
        if action_type == "direct_reply":
            return Command(goto="generate_reply")
        elif action_type == "send_new_message":
            return Command(goto="generate_reply")
        elif action_type == "fetch_knowledge":
            return Command(goto="fetch_knowledge")
        elif action_type == "wait":
            return Command(goto="wait_for_user_message")
        elif action_type == "listening":
            return Command(goto="wait_for_user_message")
        elif action_type == "rethink_goal":
            return Command(goto="analyze_goals")
        elif action_type == "end_conversation":
            return Command(goto="end_conversation")
        elif action_type == "block_and_ignore":
            return Command(goto="block_and_ignore")
        else:
            # 默认等待
            return Command(goto="wait_for_user_message")
    except Exception as e:
        logger.error(f"执行行动时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _generate_reply(state: MainState, config: RunnableConfig):
    """生成回复"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建提示词参数
        persona_text = _get_persona_text()
        goals_str = _build_goals_str(state.get("goals", []))
        knowledge_info_str = _build_knowledge_info_str(state.get("knowledge_list", []))
        chat_history_text = state.get("chat_history_str", "还没有聊天记录。")
        
        # 选择提示词模板
        action_type = state.get("current_action")
        if action_type == ActionType.SEND_NEW_MESSAGE:
            prompt_template = PFC_REPLY_GENERATOR_FOLLOW_UP_PROMPT
        else:
            prompt_template = PFC_REPLY_GENERATOR_DIRECT_PROMPT
        
        # 格式化提示词
        prompt = prompt_template.format(
            persona_text=persona_text,
            goals_str=goals_str,
            knowledge_info_str=knowledge_info_str,
            chat_history_text=chat_history_text
        )
        
        # 生成回复
        reply = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                reply += chunk.content
        
        # 更新状态
        return Command(
            update={
                "conversation_state": ConversationState.CHECKING,
                "current_message": reply
            },
            goto="check_reply"
        )
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _check_reply(state: MainState, config: RunnableConfig):
    """检查回复质量"""
    try:
        reply = state.get("current_message", "")
        if not reply:
            return Command(goto="wait_for_user_message")
        
        # 获取当前目标
        current_goal = state.get("current_goal", "")
        chat_history_text = state.get("chat_history_str", "")
        last_bot_messages = state.get("last_bot_messages", [])
        retry_count = state.get("reply_check_retry_count", 0)
        max_retries = state.get("max_reply_check_retries", 3)
        
        # 首先进行相似度检查
        similarity_ok, similarity_reason = _check_reply_similarity(reply, last_bot_messages)
        if not similarity_ok:
            logger.warning(f"相似度检查失败: {similarity_reason}")
            if retry_count >= max_retries:
                return Command(
                    update={
                        "conversation_state": ConversationState.PLANNING,
                        "reply_check_retry_count": 0,
                        "current_message": ""
                    },
                    goto="plan_action"
                )
            else:
                return Command(
                    update={
                        "conversation_state": ConversationState.GENERATING,
                        "reply_check_retry_count": retry_count + 1,
                        "current_message": ""
                    },
                    goto="generate_reply"
                )
        
        # 使用LLM进行详细检查
        chat_model = get_chat_model_by_type("basic")
        
        # 构建检查提示词
        prompt = PFC_REPLY_CHECKER_PROMPT.format(
            goal=current_goal,
            chat_history_text=chat_history_text,
            reply=reply
        )
        
        # 调用LLM检查
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        # 解析检查结果
        try:
            check_result = json.loads(response)
            suitable = check_result.get("suitable", True)
            reason = check_result.get("reason", "检查通过")
            need_replan = check_result.get("need_replan", False)
            
            # 如果suitable是字符串，转换为布尔值
            if isinstance(suitable, str):
                suitable = suitable.lower() == "true"
        except json.JSONDecodeError:
            logger.warning("回复检查响应不是有效的JSON格式")
            suitable = True
            reason = "检查响应解析失败，默认通过"
            need_replan = False
        
        # 根据检查结果决定下一步
        if suitable:
            # 检查通过，继续发送
            return Command(
                update={
                    "conversation_state": ConversationState.SENDING,
                    "reply_check_retry_count": 0
                },
                goto="send_message"
            )
        else:
            # 检查不通过
            if retry_count >= max_retries or need_replan:
                # 达到最大重试次数或需要重新规划
                logger.warning(f"回复检查失败，需要重新规划: {reason}")
                return Command(
                    update={
                        "conversation_state": ConversationState.PLANNING,
                        "reply_check_retry_count": 0,
                        "current_message": ""
                    },
                    goto="plan_action"
                )
            else:
                # 重试生成回复
                logger.info(f"回复检查失败，重试生成: {reason}")
                return Command(
                    update={
                        "conversation_state": ConversationState.GENERATING,
                        "reply_check_retry_count": retry_count + 1,
                        "current_message": ""
                    },
                    goto="generate_reply"
                )
                
    except Exception as e:
        logger.error(f"检查回复时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _send_message(state: MainState, config: RunnableConfig):
    """发送消息"""
    try:
        chat_id = state["chat_id"]
        configurable = Configuration.from_runnable_config(config)
        reply = state.get("current_message", "")
        
        if not reply:
            return Command(goto="wait_for_user_message")
        
        # 发送流式响应
        writer = get_stream_writer()
        for char in reply:
            writer({"content": char})
        
        # 保存消息到数据库
        configurable.message_store.add_message(Message(
            msg_id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_id="aura",
            platform="default",
            m_type="text",
            content=reply,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        ))
        
        # 更新机器人消息列表
        last_bot_messages = _update_bot_messages(state, reply)
        
        # 更新状态
        action_history = state.get("action_history", [])
        current_action = state.get("current_action")
        if current_action:
            action_history.append(f"执行了 {current_action.value} 行动")
        
        return Command(
            update={
                "conversation_state": ConversationState.WAITING,
                "last_bot_message_time": time.time(),
                "last_successful_reply_action": current_action.value if current_action else None,
                "action_history": action_history,
                "current_message": "",
                "last_bot_messages": last_bot_messages
            },
            goto="wait_for_user_message"
        )
    except Exception as e:
        logger.error(f"发送消息时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _fetch_knowledge(state: MainState, config: RunnableConfig):
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
                "conversation_state": ConversationState.PLANNING,
                "knowledge_list": knowledge_list
            },
            goto="plan_action"
        )
    except Exception as e:
        logger.error(f"获取知识时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _wait_for_user_message(state: MainState, config: RunnableConfig):
    """等待用户消息"""
    try:
        # 检查是否应该继续
        if not state.get("should_continue", True):
            return Command(goto=END)
        
        # 检查是否被忽略
        ignore_until = state.get("ignore_until_timestamp")
        if ignore_until and time.time() < ignore_until:
            return Command(goto=END)
        
        # 等待一段时间后重新观察
        await asyncio.sleep(2)
        
        return Command(
            update={
                "conversation_state": ConversationState.ANALYZING
            },
            goto="observe_conversation"
        )
    except Exception as e:
        logger.error(f"等待用户消息时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _end_conversation(state: MainState, config: RunnableConfig):
    """结束对话"""
    try:
        chat_model = get_chat_model_by_type("basic")
        
        # 构建告别语提示词
        persona_text = _get_persona_text()
        chat_history_text = state.get("chat_history_str", "")
        
        prompt = PFC_END_DECISION_PROMPT.format(
            persona_text=persona_text,
            chat_history_text=chat_history_text
        )
        
        # 决定是否发送告别语
        response = ""
        async for chunk in chat_model.astream([SystemMessage(content=prompt)]):
            if hasattr(chunk, 'content'):
                response += chunk.content
        
        try:
            decision_data = json.loads(response)
            say_bye = decision_data.get("say_bye", "no")
        except json.JSONDecodeError:
            say_bye = "no"
        
        if say_bye == "yes":
            # 生成告别语
            farewell_prompt = PFC_REPLY_GENERATOR_FAREWELL_PROMPT.format(
                persona_text=persona_text,
                chat_history_text=chat_history_text
            )
            
            farewell = ""
            async for chunk in chat_model.astream([SystemMessage(content=farewell_prompt)]):
                if hasattr(chunk, 'content'):
                    farewell += chunk.content
            
            # 发送告别语
            if farewell:
                writer = get_stream_writer()
                for char in farewell:
                    writer({"content": char})
                
                # 保存告别语
                chat_id = state["chat_id"]
                configurable = Configuration.from_runnable_config(config)
                configurable.message_store.add_message(Message(
                    msg_id=str(uuid.uuid4()),
                    chat_id=chat_id,
                    user_id="aura",
                    platform="default",
                    m_type="text",
                    content=farewell,
                    data={},
                    created_at=int(datetime.now().timestamp() * 1000)
                ))
        
        return Command(
            update={
                "conversation_state": ConversationState.ENDED,
                "should_continue": False
            },
            goto=END
        )
    except Exception as e:
        logger.error(f"结束对话时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

async def _block_and_ignore(state: MainState, config: RunnableConfig):
    """屏蔽并忽略"""
    try:
        # 设置忽略时间（1小时）
        ignore_until = time.time() + 3600
        
        return Command(
            update={
                "conversation_state": ConversationState.IGNORED,
                "ignore_until_timestamp": ignore_until,
                "is_ignored": True,
                "should_continue": False
            },
            goto=END
        )
    except Exception as e:
        logger.error(f"屏蔽忽略时出错: {str(e)}")
        return Command(
            update={
                "conversation_state": ConversationState.ERROR,
                "error_message": str(e)
            },
            goto=END
        )

# 创建StateGraph
builder = StateGraph(MainState, config_schema=Configuration)

# 添加PFC节点
builder.add_node("observe_conversation", _observe_conversation)
builder.add_node("analyze_goals", _analyze_goals)
builder.add_node("plan_action", _plan_action)
builder.add_node("execute_action", _execute_action)
builder.add_node("generate_reply", _generate_reply)
builder.add_node("check_reply", _check_reply)
builder.add_node("send_message", _send_message)
builder.add_node("fetch_knowledge", _fetch_knowledge)
builder.add_node("wait_for_user_message", _wait_for_user_message)
builder.add_node("end_conversation", _end_conversation)
builder.add_node("block_and_ignore", _block_and_ignore)

# 添加边
builder.add_edge(START, "observe_conversation")
builder.add_edge("observe_conversation", "analyze_goals")
builder.add_edge("analyze_goals", "plan_action")
builder.add_edge("plan_action", "execute_action")
builder.add_edge("execute_action", "generate_reply")
builder.add_edge("execute_action", "fetch_knowledge")
builder.add_edge("execute_action", "wait_for_user_message")
builder.add_edge("execute_action", "analyze_goals")
builder.add_edge("execute_action", "end_conversation")
builder.add_edge("execute_action", "block_and_ignore")
builder.add_edge("generate_reply", "check_reply")
builder.add_edge("check_reply", "send_message")
builder.add_edge("check_reply", "generate_reply")
builder.add_edge("check_reply", "plan_action")
builder.add_edge("send_message", "wait_for_user_message")
builder.add_edge("fetch_knowledge", "plan_action")
builder.add_edge("wait_for_user_message", "observe_conversation")
builder.add_edge("end_conversation", END)
builder.add_edge("block_and_ignore", END)

# 编译图
graph = builder.compile()
