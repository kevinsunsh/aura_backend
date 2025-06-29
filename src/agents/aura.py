import json
import uuid
import logging
import asyncio
import requests
from pydantic import BaseModel
from typing import Optional, Callable, Any, Dict
from datetime import datetime
from fastapi import WebSocketDisconnect
# 配置相关
from config import settings

from agents.graphs.main_graph import builder

# LangGraph checkpoint 相关
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStreamManager
from utils.utils import performance_point_context
# 配置LangChain日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langchain")
logger.setLevel(logging.INFO)

class ChatRequest(BaseModel):
    """
    聊天请求模型
    """
    chat_id: str
    message: str  # 文本消息
    audio: Optional[str] = None  # 可选的音频数据（base64编码）
    audio_format: Optional[str] = None  # 音频格式（如 "wav", "mp3" 等）

class AuraAgent:
    _instance = None
    @staticmethod
    def get_instance():
        if AuraAgent._instance is None:
            AuraAgent._instance = AuraAgent()
        return AuraAgent._instance
    
    def __init__(self):
        self.graph = None
        self.thread = None
        self.chat_stream = None
        
        # 统一使用postgresql驱动，禁用SSL以提高连接速度
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"  # 禁用SSL以提高连接速度
        )
        
        # 初始化数据库组件
        self.message_store = MessageStore(self.db_conn_string)
        self.chat_stream_manager = ChatStreamManager(self.db_conn_string)

        # 添加任务队列管理
        self.user_task = None
        self.task_lock = asyncio.Lock()  # 用于同步访问任务
        # WebSocket相关
        self.websocket_connection = None  # 存储WebSocket连接
        self.websocket_lock = asyncio.Lock()  # 用于同步访问WebSocket连接
    
    # WebSocket连接管理方法
    async def set_websocket_connection(self, websocket):
        """设置WebSocket连接"""
        async with self.websocket_lock:
            self.websocket_connection = websocket
            logger.info(f"用户已连接 WebSocket")

    async def remove_websocket_connection(self):
        """移除WebSocket连接"""
        async with self.websocket_lock:
            if self.websocket_connection:
                self.websocket_connection = None
                logger.info(f"用户已断开 WebSocket 连接")
        
        # 取消用户的聊天任务
        await self._cancel_user_task()
        
        # 释放聊天流锁
        if hasattr(self, 'chat_stream') and self.chat_stream:
            try:
                self.chat_stream_manager.release_lock(self.chat_stream.chat_id)
                logger.info(f"已释放聊天流锁: {self.chat_stream.chat_id}")
            except Exception as e:
                logger.error(f"释放聊天流锁时出错: {e}")

    async def send_websocket_message(self, message: dict):
        """发送WebSocket消息"""
        async with self.websocket_lock:
            if self.websocket_connection:
                try:
                    await self.websocket_connection.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"发送消息失败: {str(e)}")
                    await self.remove_websocket_connection()

    async def _cancel_user_task(self):
        """取消当前用户的现有任务"""
        async with self.task_lock:
            if self.user_task and not self.user_task.done():
                logger.info(f"取消用户的现有任务")
                self.user_task.cancel()
                try:
                    # 使用超时等待任务取消，避免无限等待
                    await asyncio.wait_for(self.user_task, timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning("任务取消超时，强制清理")
                except asyncio.CancelledError:
                    logger.debug("任务已成功取消")
                except Exception as e:
                    logger.error(f"取消任务时出错: {e}")
                finally:
                    # 确保任务被清理
                    if not self.user_task.done():
                        logger.warning("任务仍在运行，强制清理")

    async def _set_user_task(self, task: asyncio.Task):
        """设置当前用户任务"""
        async with self.task_lock:
            self.user_task = task

    async def _remove_user_task(self):
        """移除当前用户任务"""
        async with self.task_lock:
            if self.user_task:
                self.user_task = None

    async def _process_chat_task(self, chat_request: ChatRequest):
        """异步处理聊天任务，直接发送WebSocket消息"""
        try:
            # 处理输入数据
            input_data = {
                "chat_id": chat_request.chat_id,
            }
            
            # 如果有音频数据，添加到输入中
            if chat_request.audio:
                input_data["audio"] = chat_request.audio
                input_data["audio_format"] = chat_request.audio_format or "wav"
                logger.info(f"收到音频输入，格式: {input_data['audio_format']}")
            
            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                self.graph = builder.compile(checkpointer=checkpointer)
                
                # 使用超时机制避免无限等待
                try:
                    async with asyncio.timeout(300):  # 5分钟超时
                        async for event in self.graph.astream(input_data, self.thread, stream_mode=["updates", "messages"]):
                            # 解析messages事件中的AIMessageChunk内容
                            if "messages" in event:
                                type, message_tuple = event
                                if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                    # 第一个元素是消息类型，第二个元素是消息对象
                                    message_obj, message_meta = message_tuple
                                    if message_obj.content and message_meta["langgraph_node"] == "response_user_message":
                                        await self.send_websocket_message({
                                            "type": "stream_chunk",
                                            "content": str(message_obj.content),
                                            "chat_id": chat_request.chat_id
                                        })
                            elif "updates" in event:
                                type, message_obj = event
                                if "check_user_message" in message_obj:
                                    if message_obj["check_user_message"]["aura_response"] == "waiting":
                                        await self.send_websocket_message({
                                            "type": "waiting",
                                            "message": "正在处理您的消息..."
                                        })
                                    elif message_obj["check_user_message"]["aura_response"] == "ready":
                                        await self.send_websocket_message({
                                            "type": "ready",
                                            "message": "准备开始响应..."
                                        })
                                elif "response_user_message" in message_obj:
                                    if message_obj["response_user_message"]["aura_response"] == "finished":
                                        await self.send_websocket_message({
                                            "type": "end",
                                            "message": "处理完成"
                                        })
                                        break  # 处理完成，退出循环
                except asyncio.TimeoutError:
                    logger.warning("聊天任务超时")
                    await self.send_websocket_message({
                        "type": "error",
                        "message": "处理超时，请重试"
                    })
        
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info("聊天任务被取消")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"Error in chat processing: {str(e)}")
            try:
                await self.send_websocket_message({
                    "type": "error",
                    "message": f"处理失败: {str(e)}"
                })
            except Exception as send_error:
                logger.error(f"发送错误消息失败: {send_error}")

    async def process_websocket_chat(self, chat_id: str, user_input: str, audio_data: str = None, audio_format: str = None):
        """处理WebSocket聊天消息，异步任务方式（单连接处理）"""
        # 取消用户的聊天任务
        await self._cancel_user_task()
        logger.info(f"取消用户 {chat_id} 的聊天任务，开始新任务")
        
        try:
            # 创建聊天请求
            chat_request = ChatRequest(
                chat_id=chat_id,
                message=user_input,
                audio=audio_data,
                audio_format=audio_format
            )
            
            # 启动异步聊天任务（直接发送WebSocket消息）
            chat_task = asyncio.create_task(self._process_chat_task(chat_request))
            # def cleanup(task):
            #     if task.cancelled():
            #         logger.info("Task was cancelled.")
            #     elif task.done():
            #         logger.info("Task completed.")
            # chat_task.add_done_callback(cleanup)
            await self._set_user_task(chat_task)
            
        except Exception as e:
            logger.error(f"处理聊天消息失败: {str(e)}")
            await self.send_websocket_message({
                "type": "error",
                "message": f"处理失败: {str(e)}"
            })

    async def handle_websocket_connection(self, websocket, chat_id: str):
        """处理WebSocket连接，包括消息循环和异常处理（单连接处理）"""
        with performance_point_context("获取聊天流"):
            self.chat_stream = self.chat_stream_manager.get_or_create_chat_stream(chat_id)
        with performance_point_context("聊天流加锁"):
            locked = self.chat_stream_manager.acquire_lock(chat_id)
            if not locked:
                logger.warning(f"加锁失败: chat_id={chat_id}")
                return

        await websocket.accept()
        await self.set_websocket_connection(websocket)
        self.thread = {
            "configurable": {
                "user_id": chat_id,
                "thread_id": chat_id,
                "message_store": self.message_store,
                "chat_stream": self.chat_stream,
                "chat_stream_manager": self.chat_stream_manager
            }
        }
        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # 验证消息格式
                if "message" not in message_data:
                    await self.send_websocket_message({
                        "type": "error",
                        "message": "消息格式错误，缺少 'message' 字段"
                    })
                    continue
                
                user_input = message_data["message"]
                audio_data = message_data.get("audio")  # 可选的音频数据
                audio_format = message_data.get("audio_format")  # 可选的音频格式
                
                with performance_point_context("添加消息"):
                    message = Message(
                        msg_id=str(uuid.uuid4()),
                        chat_id=chat_id,
                        user_id=chat_id,
                        platform="default",
                        m_type="text",
                        content=user_input,
                        data={},
                        created_at=int(datetime.now().timestamp() * 1000)
                    )
                    self.message_store.add_message(message)
                
                # 发送开始处理的消息
                await self.send_websocket_message({
                    "type": "start",
                    "message": "开始处理您的消息..."
                })

                logger.info(f"收到用户 {chat_id} 的消息: {user_input}")
                
                # 启动异步聊天任务（非阻塞，立即返回，会取消旧任务）
                await self.process_websocket_chat(chat_id, user_input, audio_data, audio_format)
                
        except WebSocketDisconnect:
            await self.remove_websocket_connection()
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {str(e)}")
            await self.remove_websocket_connection()

    async def cleanup(self):
        """清理所有资源"""
        try:
            # 取消当前用户任务
            await self._cancel_user_task()
            
            # 移除WebSocket连接
            await self.remove_websocket_connection()
            
            # 释放聊天流锁
            if hasattr(self, 'chat_stream') and self.chat_stream:
                try:
                    self.chat_stream_manager.release_lock(self.chat_stream.chat_id)
                except Exception as e:
                    logger.error(f"释放聊天流锁时出错: {e}")
            
            logger.info("AuraAgent 资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")

    def __del__(self):
        """析构方法，确保资源清理"""
        try:
            # 在析构时尝试清理，但不要阻塞
            if hasattr(self, 'user_task') and self.user_task and not self.user_task.done():
                logger.warning("检测到未完成的任务，尝试清理")
        except Exception:
            # 忽略析构时的异常
            pass


