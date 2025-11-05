"""
Agent 流程状态定义
"""
from typing import Dict, List, Any, Optional, TypedDict, Literal
from datetime import datetime
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState

# class ActionsGoal(BaseModel):
#     action_goal: str = Field(
#         description="Action goal.",
#     )
#     related_environment_description: str = Field(
#         description="Action goal related environment description. the environment description should be a detailed description of the environment where the action goal is located.",
#     )

# class SpatialMemoryQuery(BaseModel):
#     """空间记忆查询参数"""
#     query_entity_description: str = Field(
#         description="查询实体描述, 如：'一个红色的杯子'",
#     )
#     query_entity_relation_filter: list[str] = Field(
#         description="查询实体关系过滤，如：['在桌子上', '在房间里', '在厨房里']，只有满足这些关系的实体才会被查询出来。如果为空，则查询所有实体",
#     )

# class ExecuteAction(BaseModel):
#     execute_action_target_id: str = Field(
#         description="执行动作目标ID",
#     )
#     execute_action_target_description: str = Field(
#         description="执行动作目标描述",
#     )
#     execute_action_cmd: str = Field(
#         description="执行动作命令",
#     )

# class NextAction(BaseModel):
#     action_type: Literal["spatial_memory_query", "execute_action", "report_progress", "report_result"] = Field(
#         description="行动类型：spatial_memory_query（查询空间记忆）或 execute_action（执行动作）或 report_progress（报告进度）或 report_result（报告结果）",
#     )
#     next_action_reasoning: str = Field(
#         description="Next action reasoning.",
#     )
#     # 空间记忆查询相关字段
#     spatial_memory_query: Optional[SpatialMemoryQuery] = Field(
#         description="空间记忆查询参数，当action_type为spatial_memory_query时使用",
#         default=None
#     )
#     execute_action: Optional[ExecuteAction] = Field(
#         description="执行动作参数，当action_type为execute_action时使用",
#         default=None
#     )

# class FeedbackAnalysis(BaseModel):
#     analysis_result_type: Literal["goal_archived", "plan_next_action"] = Field(
#         description="Type of the analysis result. goal_archived: the goal is archived and no more goal needed to be achieved, plan_next_action: the goal is still not achieved, we need plan the next action to continue.",
#     )
#     analysis_result_reasoning: str = Field(
#         description="Analysis result reasoning.",
#     )

# class AgentFlowState(TypedDict):
#     """Agent 流程状态"""
#     # 基础信息
#     user_id: str
#     chat_id: str
#     scene_id: str
#     bot_name: str
#     # 聊天记录
#     chat_history: str
#     # 目标相关
#     action_goal: str
#     goal_timestamp: int
#     # related_environment_description: str
#     # 相关物品
#     related_items: str
#     # 行为规划
#     action_type: str  # 新增：行动类型
#     action_target_id: str
#     action_cmd: str
#     look_for_item_type: str
#     look_for_item_description: str
#     next_action_reasoning: str
#     # 空间记忆查询相关
#     memory_query_result: str  # 新增：空间记忆查询结果
#     # 执行相关
#     feedback_reasoning: str
#     # 角色描述
#     character_description: str
#     # 行动步骤计数
#     action_step_count: int
#     # 执行结果
#     current_result: str
from enum import Enum

class StepType(str, Enum):
    SEARCH = "Search"

class Step(BaseModel):
    step_goal: str = Field(..., description="The goal of the step")
    result: Optional[str] = Field(
        default=None, description="The Step execution result"
    )

class Plan(BaseModel):
    has_achieved_goal: bool = Field(..., description="Indicates whether the goal has been achieved")
    reasoning: str = Field(..., description="The reasoning of the plan")
    steps: List[Step] = Field(
        default_factory=list,
        description="The steps of the plan",
    )
    def plan_steps_to_string(self) -> str:
        plan_steps_string = f"计划执行情况: "
        for step in self.steps:
            plan_steps_string += f"步骤: {step.step_goal}\n执行结果: {step.result}\n"
        return plan_steps_string

class Observation(BaseModel):
    entity_id: str = Field(..., description="The entity ID")
    summary_description: str = Field(..., description="The summary description of the entity according to the query")
    acceptable_actions: List[str] = Field(default_factory=list, description="The acceptable actions of the entity")
    action_suggestion: str = Field(..., description="The action suggestion")

class ObservationResult(BaseModel):
    observations: List[Observation] = Field(default_factory=list, description="The observations")

class ObserveNearbyItems(BaseModel):
    session_id: str = Field(..., description="当前session_id")
    query_item_name: str = Field(..., description="说明观察的目标的名称，比如杯子，椅子，桌子等。")
    query_item_description: str = Field(..., description="说明观察的目标的描述，比如一个红色的杯子，一个黑色的椅子，一个白色的桌子等越详细越好。")

class QueryRegion(BaseModel):
    session_id: str = Field(..., description="当前session_id")

class SearchResult(BaseModel):
    search_task: str = Field(..., description="The search task")
    search_result: str = Field(..., description="The search result of the task")
    follow_up_search_suggestion: str = Field(..., description="The follow up search suggestion")

class SearchDecision(BaseModel):
    """搜索子图的下一步决策与参数"""
    tool_name: Literal["Observe_Items", "Query_Region", "Execute_Action", "Report"] = Field(
        ..., description="下一步要调用的工具：Observe_Items/Query_Region/Execute_Action/Report"
    )
    # 对应工具所需参数
    session_id: str | None = Field(default=None, description="当前会话ID，仅当需要时提供")
    # observe 参数
    query_item_name: str | None = Field(default=None, description="观察查询目标名称，比如杯子，椅子，桌子等。")
    query_item_description: str | None = Field(default=None, description="观察查询目标描述，比如一个红色的杯子，一个黑色的椅子，一个白色的桌子等越详细越好。")
    # execute 参数
    entity_id: str | None = Field(default=None, description="执行动作目标entity_id")
    action_cmd: str | None = Field(default=None, description="执行动作命令，如 move_to/examine")
    reasoning: str | None = Field(default=None, description="动作或观察的原因")
    # report 参数
    search_result: str | None = Field(default=None, description="总结性的搜索结果")
    follow_up_search_suggestion: str | None = Field(default=None, description="后续搜索建议")

class ActionFlowState(MessagesState):
    session_id: str
    action_goal: str
    action_result: str
    plan_iterations: int = 0
    plan_history: List[str] = Field(default_factory=list, description="计划历史")
    current_plan: Plan | str = None
    # 原始计划，用于修复计划
    raw_plan: str = None
    search_result: str | None = None

class SearchState(TypedDict):
    session_id: str
    current_plan: Plan | str = None
    search_steps: List[str]
    search_result: str | None = None
    # 搜索子图：下一步工具决策与参数
    next_search_decision: SearchDecision | None = None
