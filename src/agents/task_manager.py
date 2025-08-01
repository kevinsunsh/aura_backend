from enum import Enum
import asyncio
from typing import Optional, Dict, Any
from loguru import logger

class TaskStateType(Enum):
    """任务状态类型枚举"""
    READY = "ready"
    RUNNING = "running"
    FINISHED = "finished"
    COMMITTING = "committing"

class TaskMetadata:
    """任务元数据"""
    task_state: TaskStateType = TaskStateType.READY
    shared_data: Dict[str, Any] = {}

class AgentTask:
    def __init__(self):
        self.metadata: TaskMetadata = TaskMetadata()
        self.task_lock = asyncio.Lock()

class TaskType(Enum):
    SINGING = "singing"

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Boolean,
    Text,
    Float, 
    DateTime,
    Double,
    UniqueConstraint,
    Index,
    BigInteger
)
from agents.aura_memory.database.database import Base, Database
import threading
from loguru import logger
import time
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from utils.utils import performance_point_context
from configuration.config import get_db_conn_string

class TaskModel(Base):
    """任务数据库模型"""
    __tablename__ = 'tasks'

    user_id = Column(String, primary_key=True)
    task_id = Column(String, primary_key=True)
    task_type = Column(String, nullable=False)
    task_state = Column(String, nullable=False)
    task_data = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    task_locked = Column(Boolean, nullable=False, default=False)  # 处理器锁
    task_heartbeat = Column(BigInteger, nullable=False, default=0)  # 处理器心跳

    # 索引
    __table_args__ = (
        Index('idx_chat_streams_chatstream_checked_at', 'chatstream_checked_at'),
        Index('idx_chat_streams_created_at', 'created_at'),
    )

class TaskManager:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
    
    @classmethod
    def get_instance(cls) -> 'TaskManager':
        """获取TaskManager单例实例"""
        if cls._instance is None:
            raise RuntimeError("TaskManager 尚未初始化，请先调用 TaskManager(streaming_task_handle, thinking_task_handle)")
        return cls._instance
    
    @classmethod
    def initialize(cls) -> 'TaskManager':
        """初始化TaskManager单例"""
        if cls._instance is None:
            cls._instance = cls()
        if not cls._initialized:
            # 如果实例存在但未初始化，重新初始化
            cls._instance.__init__()
        return cls._instance
    
    async def set_task_state(self, task_type: TaskType, state: TaskStateType):
        """设置任务状态（线程安全）"""
        if task_type in self._task_map:
            async with self._task_map[task_type].task_lock:
                self._task_map[task_type].metadata.task_state = state
                logger.debug(f"任务状态已设置: {task_type.value}, 状态: {state.value}")
    
    def get_task_state(self, task_type: TaskType) -> TaskStateType:
        """获取任务状态（线程安全）"""
        if task_type in self._task_map:
            return self._task_map[task_type].metadata.task_state
        return None
    
    async def set_task_shared_data(self, task_type: TaskType, data: Dict[str, Any]):
        """设置任务共享数据（线程安全）"""
        if task_type in self._task_map:
            async with self._task_map[task_type].task_lock:
                self._task_map[task_type].metadata.shared_data = data
                logger.debug(f"任务共享数据已设置: {task_type.value}, 数据: {data}")
    
    async def get_task_shared_data(self, task_type: TaskType) -> Dict[str, Any]:
        """获取任务共享数据（线程安全）"""
        if task_type in self._task_map:
            return self._task_map[task_type].metadata.shared_data
        return None
    
    @classmethod
    def reset_instance(cls):
        """重置单例实例（主要用于测试）"""
        cls._instance = None
        cls._initialized = False
