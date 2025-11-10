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
    check_points: List[str] = Field(..., description="The check points of the step")
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

class EntityInfo(BaseModel):
    summary_description: str = Field(..., description="The summary description of the entity according to the query")
    acceptable_actions: List[str] = Field(default_factory=list, description="The acceptable actions of the entity")
    action_suggestion: str = Field(..., description="The action suggestion")

class ObservationResult(BaseModel):
    query_target: str = Field(..., description="The query target")
    entities: Dict[str, EntityInfo] = Field(..., description="The entities related to the query target")

class QueryItems(BaseModel):
    current_scene_id: str = Field(..., description="当前场景ID")
    current_region: str = Field(..., description="当前区域ID")
    action_goal: str = Field(..., description="说明查询的目标的描述，比如预期找什么样的物品等，描述的越详细，查询到的物品信息越准确。")

class QueryRegions(BaseModel):
    scene_id: str = Field(..., description="当前场景ID")
    current_region: str = Field(..., description="当前区域ID")

class SearchResult(BaseModel):
    search_task: str = Field(..., description="The search task")
    task_execution_record: str = Field(..., description="The task execution record")
    finish_reasoning: str = Field(..., description="The finish reasoning of the task")

    # # 对应工具所需参数
    # session_id: str | None = Field(default=None, description="当前会话ID，仅当需要时提供")
    # # observe 参数
    # query_item_name: str | None = Field(default=None, description="观察查询目标名称，比如杯子，椅子，桌子等。")
    # query_item_description: str | None = Field(default=None, description="观察查询目标描述，比如一个红色的杯子，一个黑色的椅子，一个白色的桌子等越详细越好。")
    # # execute 参数
    # entity_id: str | None = Field(default=None, description="执行动作目标entity_id")
    # action_cmd: str | None = Field(default=None, description="执行动作命令，如 move_to/examine")
    # reasoning: str | None = Field(default=None, description="动作或观察的原因")
class QueryItemsParams(BaseModel):
    query_item_description: str = Field(..., description="说明查询的目标的描述，比如预期找什么样的物品等，描述的越详细，查询到的物品信息越准确。")

class QueryRegionsParams(BaseModel):
    current_region: str = Field(..., description="当前区域ID")

class ExecuteActionParams(BaseModel):
    entity_id: str = Field(..., description="执行动作目标entity_id")
    action_cmd: str = Field(..., description="执行动作命令，如 move_to/examine")

class ReportParams(BaseModel):
    finish_reasoning: str = Field(..., description="完成任务的原因说明")

class SearchActionDecision(BaseModel):
    """搜索子图的下一步决策与参数"""
    action_name: Literal["Query_Items", "Query_Regions", "Execute_Action", "Report"] = Field(
        ..., description="接下来要执行的动作：Query_Items/Query_Regions/Execute_Action/Report"
    )
    action_params: QueryItemsParams | QueryRegionsParams | ExecuteActionParams | ReportParams | None = Field(default=None, description="接下来要执行的动作的参数")

class RegionInfo(BaseModel):
    is_visited: bool = Field(..., description="Whether the region has been visited")
    is_searched: bool = Field(..., description="Whether the region has been searched")

class ValidatedRegions(BaseModel):
    regions: Dict[str, RegionInfo] = Field(..., description="The regions")
    def to_string(self) -> str:
        regions_string = "对于以下未访问的区域，可以执行move_to动作，移动到该区域。对于当前区域可以执行Query_Items动作来完成对当前区域的搜索。"
        for region_id, region_info in self.regions.items():
            regions_string += f"区域ID: {region_id}, 是否已访问: {region_info.is_visited}, 是否已搜索: {region_info.is_searched}\n"
        return regions_string

class ActionFlowState(MessagesState):
    session_id: str
    current_scene_id: str
    action_goal: str
    action_result: str
    action_step: int = 0
    plan_history: List[str]
    current_plan: Plan | None = None
    # 原始计划，用于修复计划
    raw_plan: str = None
    current_region: str | None = None
    validated_regions: ValidatedRegions

class SearchState(TypedDict):
    session_id: str
    current_scene_id: str
    current_plan: Plan | str = None
    search_steps: List[str]
    search_result: str | None = None
    # 搜索子图：下一步工具决策与参数
    next_search_decision: SearchActionDecision | None = None
    current_region: str | None = None
    validated_regions: ValidatedRegions
    action_step: int = 0

