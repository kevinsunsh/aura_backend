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
    knowledge_list: List[Dict[str, str]]

class GoalState(TypedDict):
    """
    对话目标状态
    """
    goals: List[Dict[str, str]]
    current_goal: Optional[str]  # 当前主要目标

class ObserveState(TypedDict):
    """
    观察状态
    """
    processed_chat_history_str: str  # 已处理聊天历史字符串
    unprocessed_chat_history_str: str  # 未处理聊天历史字符串
    last_bot_message_time: Optional[float]  # 机器人最后发言时间
    last_user_message_time: Optional[float]  # 用户最后发言时间
