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

from agents.states.memorizing_state import MemorizingTaskState
from configuration.config import GraphConfiguration
from loguru import logger
from agents.agent_memory.message_store import MessageStore, Message
from agents.agent_memory.Hippocampus import hippocampus_manager
from agents.agent_memory.memory_monitor import monitor_memory_operation, get_memory_monitor
from agents.task.task_manager import TaskManager, TaskType, TaskStateType



async def _memorize_knowledge(state: MemorizingTaskState, config: RunnableConfig):
    """将当前对话内容存储到海马体记忆系统中"""
    try:
        await asyncio.sleep(1)
        if TaskManager.get_instance().get_task_state(TaskType.MEMORIZING) == TaskStateType.PAUSED:
            return Command(goto=END)
        
        # 确保海马体管理器已初始化
        if not hippocampus_manager._initialized:
            hippocampus_manager.initialize()
        
        await hippocampus_manager.build_memory()
        # await hippocampus_manager.consolidate_memory()
        return Command(
            goto=END
        )
    except Exception as e:
        logger.error(f"存储记忆到海马体时出错: {str(e)}")
        # 出错时返回错误信息
        return Command(
            goto=END
        )

# 创建StateGraph
builder = StateGraph(MemorizingTaskState, config_schema=GraphConfiguration)

# 添加记忆存储节点
builder.add_node("memorize_knowledge", _memorize_knowledge)

# 添加边
builder.add_edge(START, "memorize_knowledge")
