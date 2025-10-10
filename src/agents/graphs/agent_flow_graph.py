"""
完整的 Agent 流程图实现
包含目标分析、行为规划、执行等待、结果验证和继续规划
"""

import json
import numpy as np
from turtle import goto
from datetime import datetime
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain.chat_models import init_chat_model
from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from agents.states.agent_flow_state import AgentFlowState, NextAction, FeedbackAnalysis
from agents.prompts.agent_flow_prompts import (
    ACTION_PLANNING_PROMPT,
    FEEDBACK_ANALYSIS_PROMPT
)
from loguru import logger
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.message_store import MessageStore
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.configuration.config import EmbeddingModel
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from utils.utils import safe_async_call

def format_chat_history(chat_history: List[Dict[str, Any]]) -> str:
    """格式化聊天记录"""
    if not chat_history:
        return "暂无聊天记录"
    
    formatted = []
    for msg in chat_history:
        formatted.append(f"消息类型:{msg.m_type}, 角色:{msg.role}, 内容:{msg.content}")
    
    return "\n".join(formatted)

def format_items(items: List[Dict[str, Any]]) -> str:
    """格式化物品列表"""
    if not items:
        return "暂无物品"
    formatted = []
    formatted.append("你的周围有以下物品：")
    for item in items:
        if isinstance(item["actions"], dict):
            actions_str = ",".join([action for actions in item.get("actions", {}).values() for action in actions])
        if isinstance(item["actions"], list):
            actions_str = ",".join([action for action in item.get("actions", [])])
        line = f"ID={item.get('item_id')}, 描述={item.get('description') or ''}"
        if actions_str:
            line += f", 可接受动作=[{actions_str}]"
        else:
            line += f", 可接受动作=[move_to]"
        formatted.append(line)
    formatted.append("注意：ID只能用于作为动作目标参数，不能在任何其他地方使用。如果你需要在其他地方引用该物品，请使用该物品的描述内容。")
    return "\n".join(formatted)

# def analyze_goals(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
#     """分析目标节点"""
#     try:
#         # 获取聊天模型
#         planner = get_chat_model_by_type("pfc_action_planner")
#         # 格式化输入数据
#         chat_id = state.get("chat_id", "")
#         user_id = state.get("user_id", "")
#         prompt_manager = PromptManager.get_instance()
#         chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=120*1000, chat_id=chat_id, m_type="text")
#         char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(user_id, chat_id)
#         view_np = np.array(char_instance_info.view_matrix, dtype=float)
#         view_np = view_np.reshape(4, 4)
#         view_np = np.transpose(view_np)
#         scene_id = char_instance_info.current_scene_id
#         inv_view_matrix = np.linalg.inv(view_np)
#         character_world_pos = np.dot(inv_view_matrix, np.array([0, 0, 0, 1]))[:3]
#         character_world_pos = character_world_pos.tolist()
#         character_world_pos[2] = 0.5
#         candidate_items = SceneItemEntryManager().get_scene_items_by_distance(character_world_pos, 1000, scene_id, ["Nova", "Zoe", "Eva", "Nova老", "nova", "MHC_Talker"])
#         chat_history_str = format_chat_history(chat_history)
#         previous_goal_str = state.get("action_goal", "")
#         scene_description = format_items(candidate_items)
#         planner_model = init_chat_model(
#             model=planner.model_name,
#             model_provider=planner.model_provider,
#             api_key=planner.api_key,
#             base_url=planner.api_base
#         )
#         output_parser = RemoveFunctionCallOutputParser(pydantic_object=ActionsGoal)
#         structured_llm = planner_model | output_parser
#         goal_format = output_parser.get_format_instructions()
#         # Format system instructions for plan generation
#         system_instructions = GOAL_ANALYSIS_PROMPT.format(
#             character_description=prompt_manager.character.description,
#             scene_description=scene_description,
#             chat_history=chat_history_str,
#             previous_goal=previous_goal_str,
#             format=goal_format
#         )
#         # Generate plan
#         actions_plan: ActionsGoal = structured_llm.invoke([
#             SystemMessage(content=system_instructions)
#         ])
#         update_data = {
#             "action_goal": actions_plan.action_goal,
#             "related_environment_description": actions_plan.related_environment_description,
#             "chat_history": chat_history_str,
#             "scene_id": prompt_manager.scene_info.scene_id,
#             "character_description": prompt_manager.character.description
#         }
#         return update_data
#     except Exception as e:
#         logger.error(f"分析目标时出错: {str(e)}")
#         return Command(goto=END)

def prepare_data(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """准备数据节点"""
    try:
        action_goal = state.get("action_goal", "")
        embedding_model = EmbeddingModel(
            model_name="doubao-embedding-large-text-250515",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
        )
        desc_vec = embedding_model.embed(action_goal)
        scene_id = PromptManager.get_instance().scene_info.scene_id
        character_description = PromptManager.get_instance().character.description
        bot_name = PromptManager.get_instance().character.name
        items = SceneItemEntryManager().search_items_by_description_vector(scene_id, desc_vec, top_k=20)
        important_items = SceneItemEntryManager().get_scene_items_by_type(scene_id, "", ["Nova", "Zoe", "Eva", "Nova老", "nova", "MHC_Talker"])
        items.extend(important_items)
        related_items_str = format_items(items)
        update_data = {
            "related_items": related_items_str,
            "character_description": character_description,
            "scene_id": scene_id,
            "bot_name": bot_name
        }
        return update_data
    except Exception as e:
        logger.bind(tag="BASE").info(f"准备数据时出错: {str(e)}")
        return Command(goto=END)

def plan_action(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """行为规划节点"""
    try:
        # 获取聊天模型
        planner = get_chat_model_by_type("pfc_action_planner")
        # 格式化输入数据
        chat_id = state.get("chat_id", "")
        action_goal = state.get("action_goal", "")
        character_description = state.get("character_description", "")
        related_items = state.get("related_items", "")
        goal_timestamp = state.get("goal_timestamp", 0)
        current_timestamp = int(datetime.now().timestamp() * 1000)
        duration = current_timestamp - goal_timestamp
        chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=duration, chat_id=chat_id, m_type="action")
        chat_history_str = format_chat_history(chat_history)
        # logger.bind(tag="BASE").info(f"related_items_str: {related_items_str}")
        planner_model = init_chat_model(
            model=planner.model_name,
            model_provider=planner.model_provider,
            api_key=planner.api_key,
            base_url=planner.api_base
        )
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=NextAction)
        structured_llm = planner_model | output_parser
        plan_format = output_parser.get_format_instructions()
        # Format system instructions for plan generation
        system_instructions = ACTION_PLANNING_PROMPT.format(
            character_description=character_description,
            current_goal=action_goal,
            action_history=chat_history_str,
            related_items=related_items,
            format=plan_format
        )
        # Generate plan
        next_action: NextAction = structured_llm.invoke([
            SystemMessage(content=system_instructions)
        ])
        update_data = {
            "action_target_id": next_action.action_target_id,
            "action_cmd": next_action.action_cmd,
            "next_action_reasoning": next_action.next_action_reasoning,
        }
        return update_data
    except Exception as e:
        logger.bind(tag="BASE").info(f"规划行为时出错: {str(e)}")
        return Command(goto=END)

def execute_action(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """执行行动节点"""
    action_target_id = state.get("action_target_id", "")
    action_cmd = state.get("action_cmd", "")
    action_reasoning = state.get("next_action_reasoning", "")
    scene_id = state.get("scene_id", "")
    bot_name = state.get("bot_name", "")
    goal_timestamp = state.get("goal_timestamp", 0)
    current_timestamp = int(datetime.now().timestamp() * 1000)
    duration = current_timestamp - goal_timestamp
    character_description = state.get("character_description", "")
    interrupt_message = json.dumps({"id": action_target_id, "cmd": action_cmd, "reasoning": action_reasoning, "scene_id": scene_id, "bot_name": bot_name}, ensure_ascii=False, indent=2)
    logger.bind(tag="BASE").info(f"interrupt message: {interrupt_message}")
    feedback = interrupt(interrupt_message)
    try:
        planner = get_chat_model_by_type("pfc_action_planner")
        # 格式化输入数据
        chat_id = state.get("chat_id", "")
        action_goal = state.get("action_goal", "")
        # action_target_id = state.get("action_target_id", "")
        # action_cmd = state.get("action_cmd", "")
        # current_action = state.get("current_action", "")
        # current_target = state.get("current_target", "")
        character_description = state.get("character_description", "")
        planner_model = init_chat_model(
            model=planner.model_name,
            model_provider=planner.model_provider,
            api_key=planner.api_key,
            base_url=planner.api_base
        )
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=FeedbackAnalysis)
        structured_llm = planner_model | output_parser
        feedback_format = output_parser.get_format_instructions()
        chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=duration, chat_id=chat_id, m_type="action")
        chat_history_str = format_chat_history(chat_history)
        # Format system instructions for plan generation
        system_instructions = FEEDBACK_ANALYSIS_PROMPT.format(
            character_description=character_description,
            current_goal=action_goal,
            action_history=chat_history_str,
            format=feedback_format
        )
        # Generate plan
        feedback_analysis: FeedbackAnalysis = structured_llm.invoke([
            SystemMessage(content=system_instructions)
        ])
        if feedback_analysis.analysis_result_type == "goal_archived":
            logger.bind(tag="BASE").info(f"目标已实现")
            return Command(goto=END, update={"action_goal": action_goal, "current_result": feedback_analysis.analysis_result_reasoning})
        elif feedback_analysis.analysis_result_type == "plan_next_action":
            logger.bind(tag="BASE").info(f"规划下一步行动: {feedback_analysis.analysis_result_reasoning}")
            return Command(goto="plan_action", 
                update={"feedback_reasoning": feedback_analysis.analysis_result_reasoning})
    except Exception as e:
        logger.bind(tag="BASE").info(f"执行行动时出错: {str(e)}")
        return Command(goto=END)

# 创建状态图
builder = StateGraph(AgentFlowState)

# 添加节点
# builder.add_node("analyze_goals", analyze_goals)
builder.add_node("prepare_data", prepare_data)
builder.add_node("plan_action", plan_action)
builder.add_node("execute_action", execute_action)
# 添加边
builder.add_edge(START, "prepare_data")
builder.add_edge("prepare_data", "plan_action")
builder.add_edge("plan_action", "execute_action")
