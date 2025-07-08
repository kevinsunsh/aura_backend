from enum import Enum
import asyncio
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class StreamingActionType(Enum):
    """流式行动类型枚举"""
    RESPONSE = "response"
    # FOLLOW_UP = "follow_up"
    # LISTENING = "listening"
    WAITING = "waiting"

class StreamingTaskAction:
    """流式任务行动"""
    action_type: StreamingActionType = StreamingActionType.WAITING
    action_reason: str = ""

class ThinkingActionType(Enum):
    """思考行动类型枚举"""
    THINKING = "thinking"
    WAITING = "waiting"

class ThinkingTaskAction:
    """思考任务行动"""
    action_type: ThinkingActionType = ThinkingActionType.WAITING
    action_reason: str = ""

class StreamingTask:
    def __init__(self, task_handle: asyncio.Task):
        self.action_state: StreamingTaskAction = StreamingTaskAction()
        self.task_handle = task_handle
        self.task_id = None
        self.task_lock = asyncio.Lock()

class ThinkingTask:
    def __init__(self, task_handle: asyncio.Task):
        self.action_state: ThinkingTaskAction = ThinkingTaskAction()
        self.task_handle = task_handle
        self.task_id = None
        self.task_lock = asyncio.Lock()

class TaskManager:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, streaming_task_handle: asyncio.Task = None, thinking_task_handle: asyncio.Task = None):
        if not self._initialized:
            if streaming_task_handle is None or thinking_task_handle is None:
                raise ValueError("TaskManager 初始化时需要提供 streaming_task_handle 和 thinking_task_handle")
            
            self._streaming_task: StreamingTask = StreamingTask(
                task_handle=streaming_task_handle
            )
            self._thinking_task: ThinkingTask = ThinkingTask(
                task_handle=thinking_task_handle
            )
            self._initialized = True
    
    @classmethod
    def get_instance(cls) -> 'TaskManager':
        """获取TaskManager单例实例"""
        if cls._instance is None:
            raise RuntimeError("TaskManager 尚未初始化，请先调用 TaskManager(streaming_task_handle, thinking_task_handle)")
        return cls._instance
    
    @classmethod
    def initialize(cls, streaming_task_handle: asyncio.Task, thinking_task_handle: asyncio.Task) -> 'TaskManager':
        """初始化TaskManager单例"""
        if cls._instance is None:
            cls._instance = cls(streaming_task_handle, thinking_task_handle)
        elif not cls._initialized:
            # 如果实例存在但未初始化，重新初始化
            cls._instance.__init__(streaming_task_handle, thinking_task_handle)
        return cls._instance
    
    async def set_streaming_action(self, action: StreamingActionType, reason: str = ""):
        """设置流式行动（线程安全）"""
        if self._streaming_task:
            async with self._streaming_task.task_lock:
                self._streaming_task.action_state.action_type = action
                self._streaming_task.action_state.action_reason = reason
                logger.info(f"流式行动已设置: {action.value}, 原因: {reason}")
    
    def get_streaming_action(self) -> StreamingTaskAction:
        """获取流式状态（线程安全）"""
        # with self._streaming_state_lock: return self._streaming_state
        return self._streaming_task.action_state if self._streaming_task else None
    
    async def set_thinking_action(self, action: ThinkingActionType, reason: str = ""):
        """设置思考行动（线程安全）"""
        if self._thinking_task:
            async with self._thinking_task.task_lock:
                self._thinking_task.action_state.action_type = action
                self._thinking_task.action_state.action_reason = reason
                logger.info(f"思考行动已设置: {action.value}, 原因: {reason}")
    
    def get_thinking_action(self) -> ThinkingTaskAction:
        """获取思考状态（线程安全）"""
        return self._thinking_task.action_state if self._thinking_task else None
    
    def cleanup(self):
        """清理任务"""
        if self._streaming_task:
            self._streaming_task.task_handle.cancel()
        if self._thinking_task:
            self._thinking_task.task_handle.cancel()
    
    @classmethod
    def reset_instance(cls):
        """重置单例实例（主要用于测试）"""
        if cls._instance:
            cls._instance.cleanup()
        cls._instance = None
        cls._initialized = False
