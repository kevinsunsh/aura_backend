import asyncio
import logging
import uuid
from typing import Dict, Any, Callable
from datetime import datetime
from enum import Enum
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.graphs.main_graph import builder
from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStream, ChatStreamManager

logger = logging.getLogger(__name__)

class TaskType(Enum):
    """任务类型枚举"""
    PROCESS = "process"  # 主要处理任务
    QUICK_REPLY = "quick_reply"  # 快速回复任务

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
        self.processing_task = None  # 存储不同类型的处理任务
        self.task_lock = asyncio.Lock()
        self.is_running = True
        # self.process_task_status = "idle"  # 主处理任务状态: idle, waiting, processing, finished
    
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
            # 取消之前的任务（如果存在）
            await self._cancel_existing_task()
            
            # 启动新的异步任务
            task = asyncio.create_task(
                self._process_text_task(chat_stream)
            )
            
            # 记录任务
            async with self.task_lock:
                self.processing_task = task
            
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

    async def _cancel_existing_task(self):
        """取消现有的处理任务"""
        async with self.task_lock:
            if self.processing_task:
                task = self.processing_task
                if not task.done():
                    logger.info(f"取消现有的处理任务")
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=1.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"取消任务超时")
                    except asyncio.CancelledError:
                        logger.debug(f"任务已成功取消")
                    except Exception as e:
                        logger.error(f"取消任务时出错: {e}")
                
                # 清理任务记录
                self.processing_task = None
    
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
                graph = builder.compile(checkpointer=checkpointer)
                
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
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "type": "stream_chunk",
                                                "content": str(message_obj.content),
                                                "chat_id": chat_stream.chat_id
                                            })
                            elif "updates" in event:
                                type, message_obj = event
                                if "check_user_message" in message_obj:
                                    if message_obj["check_user_message"]["aura_response"] == "waiting":
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "type": "waiting",
                                                "message": "正在处理您的消息..."
                                            })
                                    elif message_obj["check_user_message"]["aura_response"] == "ready":
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "type": "ready",
                                                "message": "准备开始响应..."
                                            })
                                elif "response_user_message" in message_obj:
                                    if message_obj["response_user_message"]["aura_response"] == "finished":
                                        if self.websocket_send_callback:
                                            await self.websocket_send_callback({
                                                "type": "end",
                                                "message": "处理完成"
                                            })
                                        break  # 处理完成，退出循环
                except asyncio.TimeoutError:
                    logger.warning(f"聊天任务超时: chat_id={chat_stream.chat_id}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback({
                            "type": "error",
                            "message": "处理超时，请重试"
                        })
        
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"聊天任务被取消: chat_id={chat_stream.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"聊天任务处理失败: chat_id={chat_stream.chat_id}, error={str(e)}")
            if self.websocket_send_callback:
                try:
                    await self.websocket_send_callback({
                        "type": "error",
                        "message": f"处理失败: {str(e)}"
                    })
                except Exception as send_error:
                    logger.error(f"发送错误消息失败: {send_error}")
        finally:
            # 清理任务记录
            async with self.task_lock:
                self.processing_task = None
    
    async def cleanup(self):
        """清理资源"""
        await self._cancel_existing_task()
        logger.info("MessageProcessorText资源清理完成")
