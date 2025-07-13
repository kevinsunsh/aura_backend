import json
import uuid
import time
import asyncio
import re
from datetime import datetime
from typing import Optional, Dict, Any

from langchain_core.runnables import RunnableConfig

from langgraph.graph import START, END, StateGraph
from langgraph.types import Command

from agents.states.recalling_state import RecallingTaskState
from configuration import GraphConfiguration, global_config, get_chat_model_by_type
import logging
from agents.aura_memory.message_store import MessageStore, Message
from agents.aura_memory.Hippocampus import hippocampus_manager
from agents.aura_memory.memory_monitor import monitor_memory_operation, get_memory_monitor
from agents.task_manager import TaskManager, TaskType, TaskStateType
logger = logging.getLogger(__name__)

async def _recall_knowledge(state: RecallingTaskState, config: RunnableConfig):
    """从海马体记忆系统中检索相关记忆"""
    try:
        await asyncio.sleep(1)
        if TaskManager.get_instance().get_task_state(TaskType.RECALLING) == TaskStateType.PAUSED:
            return Command(goto=END)
        
        # 确保海马体管理器已初始化
        if not hippocampus_manager._initialized:
            hippocampus_manager.initialize()
        
        # 获取海马体实例
        hippocampus = hippocampus_manager.get_hippocampus()
        
        # 获取历史消息和用户输入
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        processed_chat_history_str = observing_task_shared_data.get("processed_chat_history_str", "还没有聊天记录。")
        unprocessed_chat_history_str = observing_task_shared_data.get("unprocessed_chat_history_str", "还没有聊天记录。")
        
        # 使用LLM从历史消息生成查询
        search_text = await _generate_search_query_from_history(
            processed_chat_history_str, 
            unprocessed_chat_history_str
        )
        
        if not search_text:
            logger.warning("LLM无法生成有效的查询文本，跳过记忆检索")
            return Command(
                goto=END
            )
        
        logger.info(f"LLM生成的查询文本: {search_text}")
        logger.info(f"开始从海马体记忆系统检索记忆")
        
        # 获取配置信息
        max_memory_num = global_config.memory.recall_max_memory_num
        max_memory_length = global_config.memory.recall_max_memory_length
        max_depth = global_config.memory.recall_max_depth
        fast_retrieval = global_config.memory.recall_fast_retrieval
        
        # 使用海马体组件进行记忆检索
        try:
            memories = await hippocampus.get_memory_from_text(
                text=search_text,
                max_memory_num=max_memory_num,
                max_memory_length=max_memory_length,
                max_depth=max_depth,
                fast_retrieval=fast_retrieval
            )
            
            # 格式化记忆结果
            formatted_memories = _format_memories_for_response(memories)
            
            # 计算检索置信度
            confidence = _calculate_recall_confidence(memories, search_text)
            
            logger.info(f"记忆检索完成，找到 {len(memories)} 条相关记忆")
            await TaskManager.get_instance().set_task_shared_data(TaskType.RECALLING, {
                "query": search_text,
                "knowledge": formatted_memories,
                "confidence": confidence,
                "timestamp": datetime.now().isoformat()
            })
            return Command(
                goto=END
            )
            
        except Exception as e:
            logger.error(f"记忆检索失败: {e}")
            # 尝试快速检索作为回退
            try:
                logger.info("尝试快速检索作为回退...")
                memories = await hippocampus.get_memory_from_text(
                    text=search_text,
                    max_memory_num=2,
                    max_memory_length=1,
                    max_depth=2,
                    fast_retrieval=True
                )
                
                formatted_memories = _format_memories_for_response(memories)
                confidence = _calculate_recall_confidence(memories, search_text)
                
                logger.info(f"记忆检索完成，找到 {len(memories)} 条相关记忆")
                await TaskManager.get_instance().set_task_shared_data(TaskType.RECALLING, {
                    "query": search_text,
                    "knowledge": formatted_memories,
                    "confidence": confidence,
                    "timestamp": datetime.now().isoformat()
                })
                
                logger.info(f"快速检索完成，找到 {len(memories)} 条相关记忆")
                
                return Command(
                    goto=END
                )
                
            except Exception as fallback_error:
                logger.error(f"快速检索也失败: {fallback_error}")
                return Command(
                    goto=END
                )
                
    except Exception as e:
        logger.error(f"回忆记忆时出错: {str(e)}")
        return Command(
            goto=END
        )

async def _generate_search_query_from_history(
    processed_chat_history_text: str,
    unprocessed_chat_history_text: str
) -> str:
    """使用LLM从历史消息生成搜索查询"""
    try:
        # 获取LLM模型
        model = get_chat_model_by_type("memory_summary")
        
        # 构建历史消息文本
        history_text = processed_chat_history_text + "\n" + unprocessed_chat_history_text
        if history_text and history_text.strip():
            history_text = history_text.strip()
        
        if not history_text:
            logger.warning("没有可用的历史消息")
            return ""
        
        # 构建LLM提示词
        prompt = f"""基于以下对话历史，生成一个简洁的搜索查询来检索相关记忆。

对话历史：
{history_text}

请分析对话历史和用户输入，生成一个包含关键信息的搜索查询。查询应该：
1. 包含对话中的主要话题和关键词
2. 反映用户当前关注的内容
3. 简洁明了，不超过50个字符
4. 使用中文

只返回搜索查询，不要其他内容。如果无法生成有效查询，返回"无有效查询"。

搜索查询："""
        
        # 使用LLM生成查询
        response = await model.ainvoke(prompt)
        
        # 清理响应
        search_query = response.content.strip()
        
        # 移除引号和多余标点
        search_query = re.sub(r'^["""]|["""]$', '', search_query)
        search_query = re.sub(r'[^\w\s\u4e00-\u9fff]', '', search_query)
        
        # 检查是否生成了有效查询
        if not search_query or search_query == "无有效查询" or len(search_query) < 2:
            logger.warning("LLM生成的查询无效")
            return ""
        
        logger.info(f"LLM成功生成查询: {search_query}")
        return search_query
        
    except Exception as e:
        logger.error(f"使用LLM生成查询失败: {e}")
        return None

def _format_memories_for_response(memories: list) -> str:
    """格式化记忆结果用于响应"""
    try:
        if not memories:
            return "没有找到相关的记忆。"
        
        formatted_parts = []
        for i, (topic, memory) in enumerate(memories, 1):
            # 限制记忆长度
            if len(memory) > 200:
                memory = memory[:200] + "..."
            
            formatted_parts.append(f"{i}. 主题: {topic}\n   记忆: {memory}")
        
        return "\n\n".join(formatted_parts)
    except Exception as e:
        logger.warning(f"格式化记忆结果失败: {e}")
        return "记忆格式化失败。"

def _calculate_recall_confidence(memories: list, search_text: str) -> float:
    """计算记忆检索的置信度"""
    try:
        if not memories:
            return 0.0
        
        # 基于记忆数量和查询文本长度计算置信度
        memory_count = len(memories)
        query_length = len(search_text)
        
        # 记忆数量因子
        count_factor = min(1.0, memory_count / 3.0)
        
        # 查询长度因子
        length_factor = min(1.0, query_length / 50.0)
        
        # 综合置信度
        confidence = (count_factor + length_factor) / 2
        
        return max(0.0, min(1.0, confidence))
    except Exception as e:
        logger.warning(f"计算检索置信度失败: {e}")
        return 0.5

# 创建StateGraph
builder = StateGraph(RecallingTaskState, config_schema=GraphConfiguration)

# 添加记忆检索节点
builder.add_node("recall_knowledge", _recall_knowledge)

# 添加边
builder.add_edge(START, "recall_knowledge")
