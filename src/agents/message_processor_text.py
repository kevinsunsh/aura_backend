import asyncio
import logging
import uuid
import json
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from enum import Enum
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.graphs.main_graph import builder as main_graph_builder
from agents.graphs.quick_graph import builder as quick_graph_builder
from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStream, ChatStreamManager
from .configuration import ServerEventEnum

logger = logging.getLogger(__name__)

class TaskType(Enum):
    """任务类型枚举"""
    PROCESS = "process"  # 正常处理任务
    QUICK_RESPONSE = "quick_response"  # 快速回复任务

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""
    
    def __init__(self, 
                 message_store: MessageStore,
                 chat_stream_manager: ChatStreamManager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.message_store = message_store
        self.chat_stream_manager = chat_stream_manager
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
        self.processing_tasks: Dict[TaskType, asyncio.Task] = {}  # 存储不同类型任务
        self.task_lock = asyncio.Lock()
        self.is_running = True
        
        # 激活任务相关
        self.active_task: Optional[TaskType] = None  # 当前激活的任务类型
        self.active_task_lock = asyncio.Lock()  # 激活任务的锁
    
    def can_replace_active_task(self, new_task_type: TaskType) -> bool:
        """
        判断新任务是否可以取代当前激活任务
        
        规则：
        1. 如果没有激活任务，任何任务都可以成为激活任务
        2. PROCESS任务可以取代QUICK_RESPONSE任务
        3. QUICK_RESPONSE任务不能取代PROCESS任务
        4. 同类型任务可以相互取代
        """
        if self.active_task is None:
            return True
        
        # PROCESS任务优先级最高，可以取代任何任务
        if new_task_type == TaskType.PROCESS:
            return True
        
        # QUICK_RESPONSE任务只能取代QUICK_RESPONSE任务
        if new_task_type == TaskType.QUICK_RESPONSE:
            return self.active_task == TaskType.QUICK_RESPONSE
        
        return False
    
    async def set_active_task(self, task_type: TaskType):
        """设置激活任务"""
        async with self.active_task_lock:
            self.active_task = task_type
            logger.info(f"设置激活任务: {task_type.value}")
    
    async def clear_active_task(self, task_type: TaskType):
        """清除激活任务（只有当清除的是当前激活任务时才清除）"""
        async with self.active_task_lock:
            if self.active_task == task_type:
                self.active_task = None
                logger.info(f"清除激活任务: {task_type.value}")
    
    async def check_and_set_active_task(self, task_type: TaskType) -> bool:
        """
        检查并设置激活任务
        返回True表示成功设置为激活任务，False表示被拒绝
        """
        # 先判断能否替换，记录旧任务类型
        async with self.active_task_lock:
            if self.active_task == task_type:
                return True
            can_replace = self.can_replace_active_task(task_type)
            old_task = self.active_task if can_replace else None
            if can_replace:
                self.active_task = task_type
                logger.info(f"设置激活任务: {task_type.value}")
            else:
                logger.info(f"新任务{task_type.value}无法取代当前激活任务{self.active_task.value if self.active_task else 'None'}")
                return False
        # 在锁外cancel旧任务，避免死锁
        if old_task is not None:
            await self._cancel_existing_task(old_task)
        return True
    
    def get_active_task_status(self) -> Dict[str, Any]:
        """
        获取当前激活任务状态
        返回包含激活任务类型和状态的字典
        """
        return {
            "active_task": self.active_task.value if self.active_task else None,
            "has_active_task": self.active_task is not None,
        }

    async def handle_text_message(self, 
                                message_data: Dict[str, Any], 
                                chat_stream: ChatStream) -> Dict[str, Any]:
        """处理文本消息"""
        try:
            user_input = message_data["message"]
            
            # 创建消息对象
            message = Message(
                msg_id=str(uuid.uuid4()),
                chat_id=chat_stream.chat_id,
                user_id=chat_stream.chat_id,
                platform="default",
                m_type="text",
                content=user_input,
                data=message_data.get("data", {}),
                created_at=int(datetime.now().timestamp() * 1000)
            )
            
            # 存储到消息存储
            self.message_store.add_message(message)
            
            logger.info(f"文本消息已存储: chat_id={chat_stream.chat_id}, content_length={len(user_input)}")
            
            await self.process_text_message(chat_stream)
            return {
                "success": True,
                "message_type": "text",
                "msg_id": message.msg_id,
                "content": user_input,
                "action": "process_text"
            }
            
        except Exception as e:
            logger.error(f"处理文本消息失败: {e}")
            return {
                "success": False,
                "error": f"处理文本消息失败: {str(e)}",
                "message_type": "text"
            }

    async def process_text_message(self, 
                                 chat_stream: ChatStream) -> Dict[str, Any]:
        """处理文本消息并启动aura聊天任务"""
        try:
            # 取消之前的处理任务（如果存在）
            await self._cancel_existing_task(TaskType.PROCESS)
            # 取消之前的快速回复任务（如果存在）
            await self._cancel_existing_task(TaskType.QUICK_RESPONSE)
            
            # 启动新的异步任务
            task = asyncio.create_task(
                self._process_text_task(chat_stream)
            )

            # 启动新的快速回复任务
            task_quick = asyncio.create_task(
                self._quick_response_task(chat_stream)
            )
            
            # 记录任务
            async with self.task_lock:
                self.processing_tasks[TaskType.PROCESS] = task
                self.processing_tasks[TaskType.QUICK_RESPONSE] = task_quick
            
            logger.info(f"已启动文本消息处理任务: chat_id={chat_stream.chat_id}")
            
            return {
                "success": True,
                "action": "task_started",
                "chat_id": chat_stream.chat_id
            }
            
        except Exception as e:
            logger.error(f"启动文本消息处理任务失败: {e}")
            return {
                "success": False,
                "error": f"启动处理任务失败: {str(e)}"
            }
    
    async def _cancel_existing_task(self, task_type: TaskType):
        """取消指定类型的现有任务"""
        task_to_cancel = None
        try:
            async with self.task_lock:
                if task_type in self.processing_tasks:
                    task_to_cancel = self.processing_tasks[task_type]
                    if not task_to_cancel.done():
                        logger.info(f"取消{task_type.value}任务")
                        task_to_cancel.cancel()
                    
                    # 清理任务记录
                    del self.processing_tasks[task_type]
            
            # 在锁外等待任务完成，避免死锁
            if task_to_cancel and not task_to_cancel.done():
                try:
                    await asyncio.wait_for(task_to_cancel, timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning(f"取消{task_type.value}任务超时")
                except asyncio.CancelledError:
                    logger.debug(f"{task_type.value}任务已成功取消")
                except Exception as e:
                    logger.error(f"取消{task_type.value}任务时出错: {e}")
        except Exception as e:
            logger.error(f"取消{task_type.value}任务时发生异常: {e}")

    async def _quick_response_task(self, 
                                 chat_stream: ChatStream):
        """快速回复任务"""
        try:
            logger.info(f"开始快速回复任务: chat_id={chat_stream.chat_id}")
                        # 处理输入数据
            input_data = {
                "chat_id": chat_stream.chat_id,
            }
            thread = {
                "configurable": {
                    "user_id": chat_stream.chat_id,
                    "thread_id": chat_stream.chat_id,
                    "message_store": self.message_store,
                    "chat_stream": chat_stream,
                    "chat_stream_manager": self.chat_stream_manager
                }
            }

            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                graph = quick_graph_builder.compile(checkpointer=checkpointer)
                
                # 使用超时机制避免无限等待
                try:
                    async with asyncio.timeout(10):  # 10秒超时
                        async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
                            # 解析messages事件中的AIMessageChunk内容
                            if "messages" in event:
                                type, message_tuple = event
                                if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                    # 第一个元素是消息类型，第二个元素是消息对象
                                    message_obj, message_meta = message_tuple
                                    if message_obj.content and message_meta["langgraph_node"] == "quick_response":
                                        # 检查是否可以激活这个任务
                                        can_activate = await self.check_and_set_active_task(TaskType.QUICK_RESPONSE)
                                        if can_activate:
                                            # 只有成功激活的任务才发送stream_chunk
                                            if self.websocket_send_callback:
                                                await self.websocket_send_callback({
                                                    "event": ServerEventEnum.ChatResponse.value,
                                                    "payload_msg": {
                                                        "content": str(message_obj.content)
                                                    }
                                                })
                                        else:
                                            # 如果无法激活，记录日志但不发送消息
                                            logger.info(f"QUICK_RESPONSE任务无法激活，跳过发送stream_chunk: chat_id={chat_stream.chat_id}")
                                            break  # 退出循环，因为无法激活
                            elif "updates" in event:
                                if "quick_response" in message_obj:
                                    if message_obj["quick_response"]["aura_response"] == "finished":
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "event": ServerEventEnum.ChatEnded.value
                                            })
                                        break  # 处理完成，退出循环
                except asyncio.TimeoutError:
                    logger.warning(f"聊天任务超时: chat_id={chat_stream.chat_id}")
        
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"快速回复任务被取消: chat_id={chat_stream.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"快速回复任务处理失败: chat_id={chat_stream.chat_id}, error={str(e)}")
        finally:
            # 清理任务记录和激活状态
            async with self.task_lock:
                if TaskType.QUICK_RESPONSE in self.processing_tasks:
                    del self.processing_tasks[TaskType.QUICK_RESPONSE]
            await self.clear_active_task(TaskType.QUICK_RESPONSE)
    
    async def _process_text_task(self, 
                               chat_stream: ChatStream):
        """异步处理聊天任务，基于原有的_process_text_task函数"""
        try:
            # 处理输入数据
            input_data = {
                "chat_id": chat_stream.chat_id,
            }
            thread = {
                "configurable": {
                    "user_id": chat_stream.chat_id,
                    "thread_id": chat_stream.chat_id,
                    "message_store": self.message_store,
                    "chat_stream": chat_stream,
                    "chat_stream_manager": self.chat_stream_manager
                }
            }
            
            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                graph = main_graph_builder.compile(checkpointer=checkpointer)
                
                # 使用超时机制避免无限等待
                try:
                    async with asyncio.timeout(300):  # 5分钟超时
                        async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
                            # 解析messages事件中的AIMessageChunk内容
                            if "messages" in event:
                                type, message_tuple = event
                                if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                    # 第一个元素是消息类型，第二个元素是消息对象
                                    message_obj, message_meta = message_tuple
                                    if message_obj.content and message_meta["langgraph_node"] == "response_user_message":
                                        # 检查是否可以激活这个任务
                                        can_activate = await self.check_and_set_active_task(TaskType.PROCESS)
                                        if can_activate:
                                            # 只有成功激活的任务才发送stream_chunk
                                            if self.websocket_send_callback:
                                                await self.websocket_send_callback({
                                                    "event": ServerEventEnum.ChatResponse.value,
                                                    "payload_msg": {
                                                        "content": str(message_obj.content)
                                                    }
                                                })
                                        else:
                                            # 如果无法激活，记录日志但不发送消息
                                            logger.info(f"PROCESS任务无法激活，跳过发送stream_chunk: chat_id={chat_stream.chat_id}")
                                            break  # 退出循环，因为无法激活
                            elif "updates" in event:
                                type, message_obj = event
                                # if "check_user_message" in message_obj:
                                #     if message_obj["check_user_message"]["aura_response"] == "waiting":
                                #         if self.websocket_send_callback:
                                #             await self.websocket_send_callback({
                                #                 "type": "waiting",
                                #                 "message": "正在处理您的消息..."
                                #             })
                                #     elif message_obj["check_user_message"]["aura_response"] == "ready":
                                #         if self.websocket_send_callback:
                                #             await self.websocket_send_callback({
                                #                 "type": "ready",
                                #                 "message": "准备开始响应..."
                                #             })
                                if "response_user_message" in message_obj:
                                    if message_obj["response_user_message"]["aura_response"] == "finished":
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "event": ServerEventEnum.ChatEnded.value
                                            })
                                        break  # 处理完成，退出循环
                except asyncio.TimeoutError:
                    logger.warning(f"聊天任务超时: chat_id={chat_stream.chat_id}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback({
                            "event": ServerEventEnum.ChatEnded.value
                        })
        
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"聊天任务被取消: chat_id={chat_stream.chat_id}")
        except Exception as e:
            logger.error(f"聊天任务处理失败: chat_id={chat_stream.chat_id}, error={str(e)}")
            if self.websocket_send_callback:
                try:
                    await self.websocket_send_callback({
                        "event": ServerEventEnum.ChatEnded.value
                    })
                except Exception as send_error:
                    logger.error(f"发送错误消息失败: {send_error}")
        finally:
            # 清理任务记录和激活状态
            async with self.task_lock:
                if TaskType.PROCESS in self.processing_tasks:
                    del self.processing_tasks[TaskType.PROCESS]
            await self.clear_active_task(TaskType.PROCESS)
    
    async def cleanup(self):
        """清理资源"""
        try:
            # 获取所有需要取消的任务类型
            task_types_to_cancel = list(self.processing_tasks.keys())
            
            # 取消所有任务
            for task_type in task_types_to_cancel:
                try:
                    await self._cancel_existing_task(task_type)
                except Exception as e:
                    logger.error(f"取消{task_type.value}任务时出错: {e}")
            
            # 清除激活任务状态
            async with self.active_task_lock:
                if self.active_task is not None:
                    logger.info(f"清理时清除激活任务: {self.active_task.value}")
                    self.active_task = None
            
            # 等待一小段时间确保所有异步任务都能正确结束
            await asyncio.sleep(0.2)
            
            # 清理所有任务记录
            async with self.task_lock:
                self.processing_tasks.clear()
            
            logger.info("MessageProcessorText资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时发生异常: {e}")
