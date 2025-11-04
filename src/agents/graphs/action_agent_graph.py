"""
完整的 Action Agent 流程图实现
包含计划制定、执行计划（观察+动作）的循环
"""
import json
import numpy as np
from typing import Dict, List, Any, Optional, Literal
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.prebuilt import create_react_agent
from loguru import logger
from agents.agent_memory.configuration.config import ChatModel, EmbeddingModel

from agents.states.action_agent_state import ActionFlowState, Plan, StepType, Step, ObserveNearbyItems, SearchState, SearchDecision, QueryRegion
from agents.prompts.action_agent_prompts import (
    ACTION_PLANNING_PROMPT,
    SEARCH_AGENT_PROMPT,
    SEARCH_REPORT_PROMPT,
    FIX_PLAN_PROMPT
)
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.message_store import MessageStore
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from configuration.configuration import Configuration
from agents.states.action_agent_state import SearchResult, SearchDecision
from agents.agent_memory.prompt_manager.spatial_entity.manager import DBManager as SpatialEntityManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from langchain_core.callbacks import dispatch_custom_event
# ==========================================
# 工具定义
# ==========================================

@tool
def query_spatial_memory(
    session_id: str,
    item_description: str, 
    relation_filter: list[str] = None,
    reasoning: str = "",
    max_depth: int = 3,
    limit: int = 10
) -> str:
    """查询空间记忆中符合描述的物品信息
    
    Args:
        item_description: 物品描述，如 "一个红色的杯子"
        relation_filter: 关系过滤条件，如 ["在桌子上", "在房间里"]，如果为空则查询所有匹配的物品
        reasoning: 查询原因说明
    
    Returns:
        匹配的物品信息JSON，包含：item_id, item_type, item_description, item_relation, item_actions
    """
    # TODO: 实现实际的空间记忆查询逻辑
    # logger.info(f"查询空间记忆: {item_description}, 关系过滤: {relation_filter}")
    embedding_model = EmbeddingModel(
        model_name="doubao-embedding-large-text-250515",
        api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
        api_base="https://ark.cn-beijing.volces.com/api/v3"
    )
    query_vector = embedding_model.embed(item_description)
    entities = SpatialEntityManager().get_instance().query_items_by_constraints(
        scene_id=scene_id,
        session_id=session_id,
        description_vector=query_vector
    )
    feedback = {}
    for entity in entities:
        feedback[entity["id"]] = {
            "name": entity["item_name"],
            "label": entity["label_name"],
            "description": entity["description"],
            "item_description": entity["item_description"],
            "acceptable_actions": entity["actions"]
        }
    return json.dumps(feedback, ensure_ascii=False, indent=2)

def format_observation_result(feedback) -> str:
    """格式化观察结果"""
    logger.info(f"格式化观察结果: {feedback}")
    content = ["以下是观察到的物品信息："]
    for key, value in feedback.items():
        for entity_id, entity in value.items():
            if entity_id == "Aura_0":
                continue
            content.append(f"你的{key}有物品entity_id为:{entity_id}, 描述为:{entity['description']}, 可执行动作有{entity['acceptable_actions']}")
    result = "\n".join(content)
    return result

def format_region_result(region_list) -> str:
    """格式化区域结果"""
    logger.info(f"格式化区域结果: {region_list}")
    content = ["以下是查询到的区域信息："]
    for entity in region_list:
        content.append(f"区域entity_id为:{entity['entity_id']}, 描述为:{entity['description']}, 可执行动作有{entity['acceptable_actions']}")
    result = "\n".join(content)
    return result

@tool(args_schema=ObserveNearbyItems)
def observe_nearby_items(
    session_id: str,
    query: str
) -> str:
    """不能移动位置的动作，只能观察附近10米空间的物品，用不同的query可以观察到不同的物品，同样的query只能观察到一样的物品，所以相同query不要多次调用（没有意义），否则会返回同样的物品信息。
    
    Args:
        session_id: 当前session_id
        query: 说明观察的目标的描述，比如预期找什么样的物品等，描述的越详细，观察到的物品信息越准确。
    
    Returns:
        附近物品列表JSON，每个物品包含：entity_id, description, acceptable_actions
    """
    # TODO: 实现实际的观察逻辑
    try:
        char_instance_info = CharInstanceInfoManager().get_instance().get_char_instance_info_by_chat_id(session_id)
        self_entity = SpatialEntityManager().get_instance().query_items_by_entity_id(
            scene_id=char_instance_info.current_scene_id,
            entity_id="Aura_0"
        )
        
        self_forward = self_entity["properties"].get("forward", [1, 0, 0])
        self_pos = self_entity["anchor_point_3d"]
        embedding_model = EmbeddingModel(
            model_name="doubao-embedding-large-text-250515",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3"
        )
        query_vector = embedding_model.embed(query, embedding_size=1024)
        # current_region = SpatialEntityManager().get_instance().query_region_of_item(
        #     scene_id=char_instance_info.current_scene_id,
        #     target_entity_id="Aura_0",
        #     session_id="static"
        # )
        entities = SpatialEntityManager().get_instance().query_nearby_items(
            scene_id=char_instance_info.current_scene_id,
            session_id="static",
            agent_pos=self_entity["anchor_point_3d"],
            radius=8000.0,
            limit=5,
            description_vector=query_vector,
            description_similarity_threshold=0.1
        )
        feedback = {}
        feedback["forward"] = {}
        feedback["backward"] = {}
        feedback["left"] = {}
        feedback["right"] = {}
        for entity in entities:
            entity_pos = entity["anchor_point_3d"]
            try:
                self_pos_np = np.array(self_pos, dtype=float)
                self_fwd_np = np.array(self_forward, dtype=float)
                entity_pos_np = np.array(entity_pos, dtype=float)
                # 投影到平面 (x, y)，忽略 z，高度不影响左右前后
                fwd_xy = self_fwd_np[:2]
                vec_xy = (entity_pos_np - self_pos_np)[:2]
                # 归一化并防御零向量
                fwd_norm = np.linalg.norm(fwd_xy)
                if fwd_norm < 1e-6:
                    fwd_xy = np.array([1.0, 0.0])
                    fwd_norm = 1.0
                dir_xy = vec_xy
                dir_norm = np.linalg.norm(dir_xy)
                # 默认关系
                relation = "forward"
                distance = float(dir_norm)
                if dir_norm < 1e-6:
                    relation = "forward"
                else:
                    # 角度阈值：前后以45°划分
                    cos_val = float(np.dot(fwd_xy, dir_xy) / (fwd_norm * dir_norm))
                    cos_val = max(min(cos_val, 1.0), -1.0)
                    cos_45 = 0.7071067811865476
                    if cos_val >= cos_45:
                        relation = "forward"
                    elif cos_val <= -cos_45:
                        relation = "backward"
                    else:
                        # 左右通过二维叉积符号判定（z 分量）
                        cross_z = fwd_xy[0] * dir_xy[1] - fwd_xy[1] * dir_xy[0]
                        relation = "left" if cross_z > 0 else "right"
                # 写入分类桶
                feedback[relation][entity["entity_id"]] = {
                    "description": entity["description"],
                    "acceptable_actions": list(set(entity["actions"] + ["move_to", "examine"]))
                }
            except Exception:
                # 回退：若计算失败，按前方处理
                feedback["forward"][entity["entity_id"]] = {
                    "description": entity["description"],
                    "acceptable_actions": list(set(entity["actions"] + ["move_to", "examine"]))
                }
        return format_observation_result(feedback)
    except Exception as e:
        logger.error(f"观察附近物品失败: {e}")

@tool(args_schema=QueryRegion)
def query_region(
    session_id: str,
    query: str
) -> str:
    """可以移动位置的动作，查询周围的区域，区域是符合描述的物品的集合。
    
    Args:
        session_id: 当前session_id
        query: 说明查询的区域描述，比如预期找什么样的区域等，描述的越详细，查询到的区域信息越准确。
    
    Returns:
        区域列表JSON，每个区域包含：entity_id, description, acceptable_actions
    """
    # TODO: 实现实际的观察逻辑
    try:
        char_instance_info = CharInstanceInfoManager().get_instance().get_char_instance_info_by_chat_id(session_id)
        embedding_model = EmbeddingModel(
            model_name="doubao-embedding-large-text-250515",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3"
        )
        query_vector = embedding_model.embed(query, embedding_size=1024)
        # current_region = SpatialEntityManager().get_instance().query_region_of_item(
        #     scene_id=char_instance_info.current_scene_id,
        #     target_entity_id="Aura_0",
        #     session_id="static"
        # )
        entities = SpatialEntityManager().get_instance().query_region(
            scene_id=char_instance_info.current_scene_id,
            session_id="static",
            limit=15,
            description_vector=query_vector,
            description_similarity_threshold=0.1
        )
        feedback = []
        for entity in entities:
            feedback.append({
                "entity_id": entity["entity_id"],
                "description": entity["description"],
                "acceptable_actions": ["move_to"]
            })
        return format_region_result(feedback)
    except Exception as e:
        logger.error(f"观察附近物品失败: {e}")

@tool(return_direct=True, args_schema=SearchResult)
def report_search_result(
    search_result: str,
    follow_up_search_suggestion: str
) -> str:
    """当完成任务后，调用此工具报告
    
    Args:
        search_result: 搜索结果
        follow_up_search_suggestion: 后续搜索建议
    Returns:
        搜索任务结果和后续搜索建议
    """
    result_str = f"搜索任务结果: {search_result}, 后续搜索建议: {follow_up_search_suggestion}"
    logger.bind(tag="BASE").info(f"报告搜索结果: {result_str}")
    return result_str

# @tool
# def execute_action(
#     session_id: str,
#     entity_id: str, 
#     action_cmd: str,
#     reasoning: str = ""
# ) -> str:
#     """能移动位置的动作，可以通过和特定物品交互来移动到目标物品位置，然后就有机会在后续的观察动作中获得更多物品的新位置，才能观察到的物品信息。
    
#     Args:
#         entity_id: 目标物品的entity_id
#         action_cmd: 在目标物品acceptable_actions中选择一个要执行的动作命令，比如 "move_to", "examine"等
#         reasoning: 执行动作的原因说明
    
#     Returns:
#         执行动作的结果反馈
#     """
#     logger.bind(tag="BASE").info(f"执行动作: {action_cmd} -> {entity_id}, 原因: {reasoning}, session_id: {session_id}")
#     result_str = f"执行动作 {action_cmd} -> {entity_id} 成功"
#     if action_cmd in ["move_to", "examine"]:
#         target_entity = SpatialEntityManager().get_instance().query_items_by_entity_id(
#             scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
#             entity_id=entity_id
#         )
#         if target_entity:
#             # execute_action_data = {
#             #     "type": "execute_action_tool",
#             #     "action_cmd": action_cmd,
#             #     "entity_id": entity_id
#             # }
#             # interrupt(execute_action_data)
#             SpatialEntityManager().get_instance().update_item_position(
#                 session_id="static",
#                 scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
#                 entity_id="Aura_0",
#                 position=np.array([target_entity["anchor_point_3d"][0], target_entity["anchor_point_3d"][1], target_entity["anchor_point_3d"][2]])
#             )
#             if action_cmd == "examine":
#                 result_str = result_str + f"，物品描述为: {target_entity['description']}"
#         else:
#             result_str = f"执行动作 {action_cmd} -> {entity_id} 失败，没有指定正确的物品entity_id"
#     return result_str

# ==========================================
# 辅助函数
# ==========================================

def format_chat_history(chat_history: List[Any]) -> str:
    """格式化聊天记录"""
    if not chat_history:
        return "暂无聊天记录"
    
    formatted = []
    for msg in chat_history:
        formatted.append(f"消息类型:{getattr(msg, 'm_type', 'unknown')}, 角色:{getattr(msg, 'role', 'unknown')}, 内容:{getattr(msg, 'content', '')}")
    
    return "\n".join(formatted)

def format_items_info(items_info: List[Dict[str, Any]]) -> str:
    """格式化物品信息列表"""
    if not items_info:
        return "暂无物品信息"
    
    formatted = []
    for item in items_info:
        formatted.append(f"ID={item.get('item_id')}, 类型={item.get('item_type')}, 描述={item.get('item_description')}, 可执行动作={item.get('item_actions')}")
    
    return "\n".join(formatted)

# ==========================================
# 节点定义
# ==========================================

def planner_node(
    state: ActionFlowState, 
    config: RunnableConfig
) -> Command[Literal["search_team", "reporter"]]:
    """计划节点：生成行动计划"""
    logger.info("Planner 生成行动计划")
    
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state.get("plan_iterations", 0)
    
    # 检查是否超过最大迭代次数
    if plan_iterations >= configurable.max_plan_iterations:
        logger.warning(f"达到最大计划迭代次数 {configurable.max_plan_iterations}")
        return Command(goto="reporter")
    
    # 获取必要信息
    action_goal = state.get("action_goal", "")
    character_description = state.get("character_description", "")
    
    # 获取模型
    planner_model_config = get_chat_model_by_type("pfc_action")
    planner_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=planner_model_config.model_provider,
        api_key=planner_model_config.api_key,
        base_url=planner_model_config.api_base
    )
        
    # 创建输出解析器
    output_parser = RemoveFunctionCallOutputParser(pydantic_object=Plan)
    structured_llm = planner_model | output_parser
    format_instructions = output_parser.get_format_instructions()
    
    # 构建提示词（加入最近观察，避免重复观察）
    plan_history = state.get("plan_history", [])
    plan_history_text = ""
    for i, plan_content in enumerate(plan_history):
        plan_history_text += f"步骤{i+1}: {plan_content}\n"
    system_instructions = ACTION_PLANNING_PROMPT.format(
        character_description=character_description,
        current_goal=action_goal,
        executed_steps=plan_history_text,
        format=format_instructions
    )
    
    messages = [HumanMessage(content=system_instructions)]
    
    result = planner_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    # 生成计划
    try:
        plan: Plan = output_parser.invoke(result.content)
        logger.bind(tag="BASE").info(f"生成计划，步骤数: {len(plan.steps)}" + ", 步骤详情: " + "\n".join([f"步骤{i+1}: {step.step_goal}" for i, step in enumerate(plan.steps)]))
        
        # 更新状态
        return Command(
            update={
                "current_plan": plan,
                "plan_iterations": plan_iterations + 1
            },
            goto="search_team" if not plan.has_achieved_goal else "reporter"
        )
    except Exception as e:
        logger.error(f"生成计划失败: {e}")
        return Command(
            update={"raw_plan": result.content},
            goto="fix_plan_node"
        )

def fix_plan_node(
    state: ActionFlowState,
    config: RunnableConfig
) -> Command[Literal["planner", "reporter"]]:
    """修复计划节点：修复计划中的错误"""
    logger.bind(tag="BASE").info("Fix Plan 修复计划")
    
    raw_plan = state.get("raw_plan")
    if not raw_plan:
        logger.warning("没有原始计划")
        return Command(goto="reporter")
    
    # 获取模型
    planner_model_config = get_chat_model_by_type("pfc_action")
    planner_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=planner_model_config.model_provider,
        api_key=planner_model_config.api_key,
        base_url=planner_model_config.api_base
    )
    output_parser = RemoveFunctionCallOutputParser(pydantic_object=Plan)
    structured_llm = planner_model | output_parser
    format_instructions = output_parser.get_format_instructions()
    system_instructions = FIX_PLAN_PROMPT.format(
        raw_plan=raw_plan,
        format=format_instructions
    )
    messages = [HumanMessage(content=system_instructions)]
    plan: Plan = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    # 更新状态
    return Command(
        update={
            "current_plan": plan
        },
        goto="search_team" if not plan.has_achieved_goal else "reporter"
    )

def search_team_node(
    state: ActionFlowState
) -> Command[Literal["search", "planner", "reporter"]]:
    """搜索团队节点：分配任务给搜索者"""
    logger.bind(tag="BASE").info("Search Team 分配任务")
    
    current_plan = state.get("current_plan")
    plan_history = state.get("plan_history", [])
    # 检查计划是否存在
    if not current_plan or not current_plan.steps:
        logger.warning("当前没有有效的计划或步骤")
        return Command(goto="reporter")
    
    # 找到第一个未执行的步骤
    next_step = None
    for step in current_plan.steps:
        if not step.result:
            next_step = step
            break
    
    if not next_step:
        # 所有步骤都已完成
        logger.bind(tag="BASE").info("所有步骤已完成，返回规划节点")
        for step in current_plan.steps: 
            search_result = f"任务目标: {step.step_goal} 执行结果: {step.result}"
            plan_history.append(search_result)
        return Command(goto="planner", update={"plan_history": plan_history})
    
    # 根据步骤类型分发到不同的节点
    logger.bind(tag="BASE").info(f"执行观察步骤: {next_step.step_goal}")
    return Command(goto="search", update={"session_id": state.get("session_id", ""), "current_plan": current_plan, "plan_history": plan_history})

def _search_decide_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["tool_observe_items", "tool_query_region", "tool_execute_action", "tool_report", END]]:
    """搜索子图-决策节点：决定调用哪个工具，并写入参数到状态"""
    logger.bind(tag="BASE").info("Search子图 决策下一步工具")

    current_plan = state.get("current_plan")
    
    # 检查计划是否存在
    if not current_plan or not current_plan.steps:
        logger.warning("当前没有有效的计划或步骤")
        return Command(goto="reporter")
    
    # 找到第一个未执行的步骤
    next_step = None
    for step in current_plan.steps:
        if not step.result:
            next_step = step
            break
    
    # 获取模型
    observer_model_config = get_chat_model_by_type("pfc_action_planner")
    observer_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=observer_model_config.model_provider,
        api_key=observer_model_config.api_key,
        base_url=observer_model_config.api_base
    )
    # 解析成 SearchDecision
    output_parser = RemoveFunctionCallOutputParser(pydantic_object=SearchDecision)
    structured_llm = observer_model | output_parser
    format_instructions = output_parser.get_format_instructions()
    system_instructions = SEARCH_AGENT_PROMPT.format(
        session_id=state.get("session_id", ""),
        search_task=f"{next_step.step_goal}",
        search_steps_history=state.get("search_steps", []),
        format=format_instructions
    )
    messages = [SystemMessage(content=system_instructions)]
    decision: SearchDecision = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    logger.bind(tag="BASE").info(f"搜索决策: {decision}")

    update = {"next_search_decision": decision}
    if decision.tool_name == "Observe_Items":
        return Command(update=update, goto="tool_observe_items")
    if decision.tool_name == "Query_Region":
        return Command(update=update, goto="tool_query_region")
    if decision.tool_name == "Execute_Action":
        return Command(update=update, goto="tool_execute_action")
    return Command(update=update, goto="tool_report")

def _search_tool_observe_items_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["search_decide"]]:
    """搜索子图-观察工具节点"""
    decision: SearchDecision | None = state.get("next_search_decision")
    session_id = decision.session_id or state.get("session_id", "") if decision else state.get("session_id", "")
    query = decision.query if decision else None
    if not query:
        logger.warning("缺少观察参数query，回到决策")
        return Command(goto="search_decide")
    try:
        result = observe_nearby_items.invoke({"session_id": session_id, "query": query})
        search_steps = state.get("search_steps", [])
        search_steps.append(f"观察: {query}\n结果: {result}")
        return Command(update={"search_steps": search_steps}, goto="search_decide")
    except Exception as e:
        logger.error(f"执行观察失败: {e}")
        return Command(goto="search_decide")

def _search_tool_query_region_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["search_decide"]]:
    """搜索子图-查询区域工具节点"""
    decision: SearchDecision | None = state.get("next_search_decision")
    session_id = decision.session_id or state.get("session_id", "") if decision else state.get("session_id", "")
    query = decision.query if decision else None
    if not query:
        logger.warning("缺少查询参数query，回到决策")
        return Command(goto="search_decide")
    try:
        result = query_region.invoke({"session_id": session_id, "query": query})
        search_steps = state.get("search_steps", [])
        search_steps.append(f"查询区域: {query}\n结果: {result}")
        return Command(update={"search_steps": search_steps}, goto="search_decide")
    except Exception as e:
        logger.error(f"查询区域失败: {e}")
        return Command(goto="search_decide")

def _search_tool_execute_action_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["search_decide"]]:
    """搜索子图-执行动作工具节点"""
    decision: SearchDecision | None = state.get("next_search_decision")
    session_id = decision.session_id or state.get("session_id", "") if decision else state.get("session_id", "")
    entity_id = decision.entity_id if decision else None
    action_cmd = decision.action_cmd if decision else None
    reasoning = decision.reasoning or ""
    if not (entity_id and action_cmd):
        logger.warning("缺少执行参数，回到决策")
        return Command(goto="search_decide")
    result = interrupt({
        "type": "execute_action_tool",
        "session_id": session_id,
        "entity_id": entity_id,
        "action_cmd": action_cmd,
        "reasoning": reasoning,
    })
    search_steps = state.get("search_steps", [])
    search_steps.append(f"执行: {action_cmd} -> {entity_id}\n结果: {result}")
    return Command(update={"search_steps": search_steps}, goto="search_decide")

def _search_tool_report_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal[END]]:
    """搜索子图-报告工具节点，结束当前步骤并返回上层"""
    decision: SearchDecision | None = state.get("next_search_decision")
    if not decision or not (decision.search_result and decision.follow_up_search_suggestion):
        logger.warning("缺少报告参数，直接返回")
        return Command(goto=END)
    try:
        result = report_search_result.invoke({
            "search_result": decision.search_result,
            "follow_up_search_suggestion": decision.follow_up_search_suggestion,
        })
        # 写入当前步骤结果
        current_plan = state.get("current_plan")
        if current_plan and getattr(current_plan, "steps", None):
            for step in current_plan.steps:
                if not step.result:
                    step.result = result
                    break
        search_steps = state.get("search_steps", [])
        search_steps.append(f"报告结果: {result}")
        return Command(update={"search_steps": search_steps, "next_search_decision": None}, goto=END)
    except Exception as e:
        logger.error(f"报告结果失败: {e}")
        return Command(goto=END)

def reporter_node(state: ActionFlowState) -> Dict[str, Any]:
    """报告节点：生成最终结果"""
    logger.bind(tag="BASE").info("Reporter 生成最终报告")
    
    current_plan = state.get("current_plan", None)
    plan_history = state.get("plan_history", [])
    action_goal = state.get("action_goal", "")
    
    # 构建最终结果
    result = f"""
# 任务执行报告

## 目标
{action_goal}

## 执行步骤
"""
    for i, plan_content in enumerate(plan_history):
        result += f"\n### 步骤 {i+1}: {plan_content}\n"
    
    result += "\n## 状态\n"
    if current_plan and current_plan.has_achieved_goal:
        result += "✓ 目标已达成\n"
    else:
        result += "✗ 目标未达成\n"
    
    logger.bind(tag="BASE").info(f"生成最终报告: {result[:200]}...")
    
    return {"action_result": result}


# ==========================================
# Graph 构建
# ==========================================

action_agent_builder = StateGraph(
    ActionFlowState,
    config_schema=Configuration
)

# 添加节点
action_agent_builder.add_node("planner", planner_node)
action_agent_builder.add_node("search_team", search_team_node)

# 构建搜索子图：工具节点化 + 条件边
search_subgraph_builder = StateGraph(
    SearchState,
    config_schema=Configuration
)
search_subgraph_builder.add_node("search_decide", _search_decide_node)
search_subgraph_builder.add_node("tool_observe_items", _search_tool_observe_items_node)
search_subgraph_builder.add_node("tool_query_region", _search_tool_query_region_node)
search_subgraph_builder.add_node("tool_execute_action", _search_tool_execute_action_node)
search_subgraph_builder.add_node("tool_report", _search_tool_report_node)
search_subgraph_builder.add_edge(START, "search_decide")
search_subgraph = search_subgraph_builder.compile()

# 将子图作为一个节点挂到主图
action_agent_builder.add_node("search", search_subgraph)

# action_agent_builder.add_node("observe", observe_node)
# action_agent_builder.add_node("action", action_node)
action_agent_builder.add_node("reporter", reporter_node)
action_agent_builder.add_node("fix_plan_node", fix_plan_node)

# 添加边
# 注意：每个节点都有自己的 Command，通过 goto 控制流程
# planner -> search_team -> (search) -> search_team -> planner (循环)
# 或者到达 reporter -> END
action_agent_builder.add_edge(START, "planner")
action_agent_builder.add_edge("reporter", END)
action_agent_builder.add_edge("search", "search_team")

# 编译Graph
action_agent_graph = action_agent_builder.compile()


# ==========================================
# 测试代码
# ==========================================

if __name__ == "__main__":
    # 简单的测试流程
    import os
    import sys
    from pprint import pprint
    from langgraph.checkpoint.memory import MemorySaver
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    import dotenv
    dotenv.load_dotenv(os.path.join(project_root, '.env'))
    
    checkpointer = MemorySaver()
    chat_id = "fc5d21b7-0e45-08d8-2252-c59cf44104dd"
    user_id = "test_user_123"
    
    # 构造测试状态
    test_state = ActionFlowState(
        action_goal="Check the wooden chair for any hidden compartments or symbols",
        action_result="",
        observations=[],
        plan_iterations=0,
        current_plan=None,
        messages=[],
        session_id=chat_id,
        character_description="一个智能AI助手"
    )
    
    # 编译 graph
    test_graph = action_agent_graph
    thread_config = {
        "configurable": {
            "thread_id": "test_thread"
        }
    }

    # SpatialEntityManager().get_instance().add_entity(
    #     session_id="static",
    #     scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
    #     entity_type='object',
    #     entity_class="Aura",
    #     world_pos=np.array([950, 970, 0]),  # 使用计算出的边界框中心点
    #     world_bb=np.array([950, 970, 0, 10, 10, 10]),
    #     confidence=1.0,
    #     parent_id=None,
    #     max_age_sec=100000000.0,
    # )
    SpatialEntityManager().get_instance().update_item_position(
        session_id="static",
        scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
        entity_id="Aura_0",
        position=np.array([950, 970, 0])
    )
    SpatialEntityManager().get_instance().update_item_properties(
        session_id="static",
        scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
        entity_id="Aura_0",
        properties={"forward": [1, 0, 0]}
    )
    
    try:
        print("=== 开始执行测试 Action Agent Graph ===")
        # 执行 graph，stream 模式逐步输出状态变更
        for idx, event in enumerate(test_graph.stream(test_state, thread_config, stream_mode="updates")):
            print(f"\n---- Event #{idx} ----")
            pprint(event)
    except Exception as e:
        print(f"执行测试Graph时出错: {str(e)}")
        import traceback
        traceback.print_exc()
