from enum import Enum
import asyncio
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class TaskStateType(Enum):
    """任务状态类型枚举"""
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"

class TaskMetadata:
    """任务元数据"""
    task_state: TaskStateType = TaskStateType.PAUSED
    shared_data: Dict[str, Any] = {}

class AgentTask:
    def __init__(self, task_handle: asyncio.Task):
        self.metadata: TaskMetadata = TaskMetadata()
        self.task_handle = task_handle
        self.task_id = None
        self.task_lock = asyncio.Lock()

class TaskType(Enum):
    SPEAKING = "speaking"
    REPLYING = "replying"
    THINKING = "thinking"
    OBSERVING = "observing"

class TaskManager:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, replying_task_handle: asyncio.Task = None,
                    speaking_task_handle: asyncio.Task = None,
                    thinking_task_handle: asyncio.Task = None,
                    observing_task_handle: asyncio.Task = None):
        if not self._initialized:
            if replying_task_handle is None or speaking_task_handle is None or thinking_task_handle is None or observing_task_handle is None:
                raise ValueError("TaskManager 初始化时需要提供 replying_task_handle, speaking_task_handle, thinking_task_handle, observing_task_handle")
            
            self._task_map: Dict[TaskType, AgentTask] = {}
            self._task_map[TaskType.REPLYING] = AgentTask(
                task_handle=replying_task_handle
            )
            self._task_map[TaskType.SPEAKING] = AgentTask(
                task_handle=speaking_task_handle
            )
            self._task_map[TaskType.THINKING] = AgentTask(
                task_handle=thinking_task_handle
            )
            self._task_map[TaskType.OBSERVING] = AgentTask(
                task_handle=observing_task_handle
            )
            self._initialized = True
    
    @classmethod
    def get_instance(cls) -> 'TaskManager':
        """获取TaskManager单例实例"""
        if cls._instance is None:
            raise RuntimeError("TaskManager 尚未初始化，请先调用 TaskManager(streaming_task_handle, thinking_task_handle)")
        return cls._instance
    
    @classmethod
    def initialize(cls, replying_task_handle: asyncio.Task,
                    speaking_task_handle: asyncio.Task,
                    thinking_task_handle: asyncio.Task,
                    observing_task_handle: asyncio.Task) -> 'TaskManager':
        """初始化TaskManager单例"""
        if cls._instance is None:
            cls._instance = cls(replying_task_handle, speaking_task_handle, thinking_task_handle, observing_task_handle)
        elif not cls._initialized:
            # 如果实例存在但未初始化，重新初始化
            cls._instance.__init__(replying_task_handle, speaking_task_handle, thinking_task_handle, observing_task_handle)
        return cls._instance
    
    async def set_task_state(self, task_type: TaskType, state: TaskStateType):
        """设置任务状态（线程安全）"""
        if task_type in self._task_map:
            async with self._task_map[task_type].task_lock:
                self._task_map[task_type].metadata.task_state = state
                logger.info(f"任务状态已设置: {task_type.value}, 状态: {state.value}")
    
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
                logger.info(f"任务共享数据已设置: {task_type.value}, 数据: {data}")
    
    async def get_task_shared_data(self, task_type: TaskType) -> Dict[str, Any]:
        """获取任务共享数据（线程安全）"""
        if task_type in self._task_map:
            return self._task_map[task_type].metadata.shared_data
        return None
    
    def cleanup(self):
        """清理任务"""
        for task_type, task in self._task_map.items():
            task.task_handle.cancel()
    
    @classmethod
    def reset_instance(cls):
        """重置单例实例（主要用于测试）"""
        if cls._instance:
            cls._instance.cleanup()
        cls._instance = None
        cls._initialized = False
