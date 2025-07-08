from typing import TypedDict, Literal, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum

class UserInputCompletion(BaseModel):
    user_input_completion: str = Field(default="", description="尝试补全用户输入")
    user_input_completion_confidence: str = Field(default="", description="用户输入补全的置信度, 可选值: 非常肯定, 比较肯定, 不确定, 非常不确定")

class ConversationState(Enum):
    """对话状态枚举"""
    INIT = "初始化"
    RETHINKING = "重新思考"
    ANALYZING = "分析历史"
    PLANNING = "规划目标"
    GENERATING = "生成回复"
    CHECKING = "检查回复"
    SENDING = "发送消息"
    FETCHING = "获取知识"
    WAITING = "等待"
    LISTENING = "倾听"
    ENDED = "结束"
    JUDGING = "判断"
    IGNORED = "屏蔽"

class ActionType(Enum):
    """行动类型枚举"""
    DIRECT_REPLY = "direct_reply"
    SEND_NEW_MESSAGE = "send_new_message"
    FETCH_KNOWLEDGE = "fetch_knowledge"
    WAIT = "wait"
    LISTENING = "listening"
    RETHINK_GOAL = "rethink_goal"
    END_CONVERSATION = "end_conversation"
    BLOCK_AND_IGNORE = "block_and_ignore"

class MainState(TypedDict):
    """
    主状态 - 扩展以支持PFC模块
    """
    # 基础字段
    chat_id: str  # Chat ID
    user_id: str  # 用户ID
    waiting_for_user_message_at: Optional[float]  # 等待用户消息的时间戳
    aura_response: str  # Aura响应状态
    current_message: str  # 当前消息内容
    
    # PFC模块状态
    conversation_state: ConversationState  # 当前对话状态
    current_action: Optional[ActionType]  # 当前执行的行动
    action_reason: str  # 行动原因
    
    # 对话目标管理
    goals: List[Dict[str, str]]  # 对话目标列表 [{"goal": "目标", "reasoning": "原因"}]
    current_goal: Optional[str]  # 当前主要目标
    
    # 行动历史
    action_history: List[str]  # 行动历史记录
    last_successful_reply_action: Optional[str]  # 上一次成功的回复行动
    
    # 观察信息
    new_messages_count: int  # 新消息数量
    chat_history_str: str  # 聊天历史字符串
    unprocessed_messages: List[Dict[str, Any]]  # 未处理的消息列表
    
    # 知识管理
    knowledge_list: List[Dict[str, str]]  # 知识列表 [{"query": "查询", "knowledge": "知识", "source": "来源"}]
    
    # 时间管理
    last_bot_message_time: Optional[float]  # 机器人最后发言时间
    ignore_until_timestamp: Optional[float]  # 忽略直到的时间戳
    
    # 控制标志
    should_continue: bool  # 是否继续对话
    is_ignored: bool  # 是否被忽略
    
    # 错误处理
    error_message: Optional[str]  # 错误信息
    retry_count: int  # 重试次数
    
    # ReplyChecker相关
    reply_check_retry_count: int  # 回复检查重试次数
    last_bot_messages: List[str]  # 最近的机器人消息列表
    max_reply_check_retries: int  # 最大回复检查重试次数