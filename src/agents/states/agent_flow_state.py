"""
Agent 流程状态定义
"""
from typing import Dict, List, Any, Optional, TypedDict, Literal
from datetime import datetime
from pydantic import BaseModel, Field

# class ActionsGoal(BaseModel):
#     action_goal: str = Field(
#         description="Action goal.",
#     )
#     related_environment_description: str = Field(
#         description="Action goal related environment description. the environment description should be a detailed description of the environment where the action goal is located.",
#     )

class NextAction(BaseModel):
    action_target_id: str = Field(
        description="Action target ID should the ID of the item in the environment.",
    )
    action_cmd: str = Field(
        description="Action cmd should the command of the action that the target item can accept.",
    )
    next_action_reasoning: str = Field(
        description="Next action reasoning.",
    )

class FeedbackAnalysis(BaseModel):
    analysis_result_type: Literal["goal_archived", "plan_next_action"] = Field(
        description="Type of the analysis result. goal_archived: the goal is archived and no more goal needed to be achieved, plan_next_action: the goal is still not achieved, we need plan the next action to continue.",
    )
    analysis_result_reasoning: str = Field(
        description="Analysis result reasoning.",
    )

class AgentFlowState(TypedDict):
    """Agent 流程状态"""
    # 基础信息
    user_id: str
    chat_id: str
    scene_id: str
    bot_name: str
    # 聊天记录
    chat_history: str
    # 目标相关
    action_goal: str
    goal_timestamp: int
    # related_environment_description: str
    # 相关物品
    related_items: str
    # 行为规划
    action_target_id: str
    action_cmd: str
    next_action_reasoning: str
    # 执行相关
    feedback_reasoning: str
    # 角色描述
    character_description: str
    # 行动步骤计数
    action_step_count: int
    # 执行结果
    current_result: str
