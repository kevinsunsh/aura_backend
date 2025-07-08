from typing import List, Dict, TypedDict, Optional, Any

class BaseState(TypedDict):
    """
    基础状态
    """
    chat_id: str  # Chat ID
    user_id: str  # 用户ID

class KnowledgeState(TypedDict):
    """
    知识状态
    """
    knowledge_info_str: str

class GoalState(TypedDict):
    """
    对话目标状态
    """
    goals_str: str

class ObserveState(TypedDict):
    """
    观察状态
    """
    processed_chat_history_str: str  # 已处理聊天历史字符串
    unprocessed_chat_history_str: str  # 未处理聊天历史字符串
    last_bot_message_time: Optional[float]  # 机器人最后发言时间
    last_user_message_time: Optional[float]  # 用户最后发言时间

class ActionState(TypedDict):
    """
    行动状态
    """
    action_history: List[Dict[str, str]]
    current_action: Optional[str]  # 当前行动
    action_reason: str  # 行动原因
    last_successful_action: Optional[str]  # 上一次成功的行动
