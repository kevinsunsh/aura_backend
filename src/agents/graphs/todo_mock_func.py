import logging
from typing import List, Dict
from agents.aura_memory.message_store import Message

logger = logging.getLogger(__name__)

def _get_persona_text() -> str:
    """获取人设文本"""
    # 这里可以从配置中获取人设信息
    return "你的名字是aura，性格温和友善，喜欢帮助朋友解决问题。"

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

def _build_chat_history_str(messages: List[Message]) -> str:
    """构建聊天历史字符串"""
    chat_history_str = ""
    for msg in messages:
        chat_history_str += f"{msg.user_id}: {msg.content}\n"
    return chat_history_str
