from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum

class RelatedItem(BaseModel):
    item_name: str = Field(description="相关物品的名称")
    item_description: str = Field(description="相关物品的描述")
    top_left_corner: List[int] = Field(default_factory=list, description="相关物品在画面中的左上角位置，格式为[x, y]")
    bottom_right_corner: List[int] = Field(default_factory=list, description="相关物品在画面中的右下角位置，格式为[x, y]")

class PlannerResponse(BaseModel):
    need_planner_response: bool = Field(description="是否需要规划")
    goal_to_plan: str = Field(description="规划的目标")
    related_items: List[RelatedItem] = Field(default_factory=list, description="规划中相关物品在画面中的位置")

class SpeakingTaskState(TypedDict):
    """
    流式回复状态
    """
    user_id: str
    session_id: str
    user_input: str
    final_response: str
