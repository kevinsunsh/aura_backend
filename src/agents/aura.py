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
# 配置LangChain日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langchain")
logger.setLevel(logging.INFO)

class ChatRequest(BaseModel):
    """
    聊天请求模型
    """
    user_id: str
    message: str  # 文本消息
    audio: Optional[str] = None  # 可选的音频数据（base64编码）
    audio_format: Optional[str] = None  # 音频格式（如 "wav", "mp3" 等）

class AuraAgent:
    _instance = None
    def __init__(self):
        self.graph = None
        self.thread = None
        self.message_store = None
        self.knowledge_graph = None
        self.db_conn_string = f"postgres://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}?sslmode=disable"
        # 添加任务队列管理
        self.user_tasks = {}  # 存储每个用户的活跃任务 {user_id: task}
        self.task_lock = asyncio.Lock()  # 用于同步访问任务字典
        # WebSocket相关
        self.websocket_connections = {}  # 存储WebSocket连接 {user_id: websocket}
        self.websocket_lock = asyncio.Lock()  # 用于同步访问WebSocket连接字典
    
    @classmethod
    def get_instance(cls) -> 'AuraAgent':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # WebSocket连接管理方法
    async def add_websocket_connection(self, user_id: str, websocket):
        """添加WebSocket连接"""
        async with self.websocket_lock:
            self.websocket_connections[user_id] = websocket
            logger.info(f"用户 {user_id} 已连接 WebSocket")

    async def remove_websocket_connection(self, user_id: str):
        """移除WebSocket连接"""
        async with self.websocket_lock:
            if user_id in self.websocket_connections:
                del self.websocket_connections[user_id]
                logger.info(f"用户 {user_id} 已断开 WebSocket 连接")
        
        # 取消用户的聊天任务
        await self._cancel_user_task(user_id)

    async def send_websocket_message(self, user_id: str, message: dict):
        """发送WebSocket消息"""
        async with self.websocket_lock:
            if user_id in self.websocket_connections:
                try:
                    websocket = self.websocket_connections[user_id]
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"发送消息给用户 {user_id} 失败: {str(e)}")
                    await self.remove_websocket_connection(user_id)

    async def _cancel_user_task(self, user_id: str):
        """取消指定用户的现有任务"""
        async with self.task_lock:
            if user_id in self.user_tasks:
                task = self.user_tasks[user_id]
                if not task.done():
                    logger.info(f"取消用户 {user_id} 的现有任务")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.user_tasks[user_id]

    async def _add_user_task(self, user_id: str, task: asyncio.Task):
        """添加用户任务到队列"""
        async with self.task_lock:
            self.user_tasks[user_id] = task

    async def _remove_user_task(self, user_id: str):
        """从队列中移除用户任务"""
        async with self.task_lock:
            if user_id in self.user_tasks:
                del self.user_tasks[user_id]

    async def get_active_tasks_info(self):
        """获取当前活跃任务的信息"""
        async with self.task_lock:
            tasks_info = {}
            for user_id, task in self.user_tasks.items():
                tasks_info[user_id] = {
                    "done": task.done(),
                    "cancelled": task.cancelled(),
                    "exception": task.exception() if task.done() and task.exception() else None
                }
            return tasks_info

    @staticmethod
    async def _process_chat_task(chat_request: ChatRequest):
        """异步处理聊天任务，直接发送WebSocket消息"""
        agent = AuraAgent.get_instance()
        
        try:
            # 处理输入数据
            input_data = {
                "user_id": chat_request.user_id,
                "user_input": chat_request.message,
                "user_input_at": datetime.now().timestamp()
            }
            
            # 如果有音频数据，添加到输入中
            if chat_request.audio:
                input_data["audio"] = chat_request.audio
                input_data["audio_format"] = chat_request.audio_format or "wav"
                logger.info(f"收到音频输入，格式: {input_data['audio_format']}")
            async with AsyncPostgresSaver.from_conn_string(agent.db_conn_string) as checkpointer:
                agent.graph = builder.compile(checkpointer=checkpointer)
                async for event in agent.graph.astream(input_data, agent.thread, stream_mode=["updates", "messages"]):
                    try:
                        # 解析messages事件中的AIMessageChunk内容
                        if "messages" in event:
                            type, message_tuple = event
                            if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                # 第一个元素是消息类型，第二个元素是消息对象
                                message_obj, message_meta = message_tuple
                                if message_obj.content and message_meta["langgraph_node"] == "response_user_message":
                                    await agent.send_websocket_message(chat_request.user_id, {
                                        "type": "stream_chunk",
                                        "content": str(message_obj.content),
                                        "user_id": chat_request.user_id
                                    })
                        elif "updates" in event:
                            type, message_obj = event
                            if "check_user_message" in message_obj:
                                if message_obj["check_user_message"]["aura_response"] == "waiting":
                                    await agent.send_websocket_message(chat_request.user_id, {
                                        "type": "waiting",
                                        "message": "正在处理您的消息..."
                                    })
                                elif message_obj["check_user_message"]["aura_response"] == "ready":
                                    await agent.send_websocket_message(chat_request.user_id, {
                                        "type": "ready",
                                        "message": "准备开始响应..."
                                    })
                            elif "response_user_message" in message_obj:
                                if message_obj["response_user_message"]["aura_response"] == "finished":
                                    await agent.send_websocket_message(chat_request.user_id, {
                                        "type": "end",
                                        "message": "处理完成"
                                    })
                    except Exception as e:
                        logger.error(f"处理事件失败: {str(e)}")
                        await agent.send_websocket_message(chat_request.user_id, {
                            "type": "error",
                            "message": f"处理失败: {str(e)}"
                        })
                        continue
        
        except Exception as e:
            logger.error(f"Error in chat processing: {str(e)}")
            await agent.send_websocket_message(chat_request.user_id, {
                "type": "error",
                "message": f"处理失败: {str(e)}"
            })

    async def process_websocket_chat(self, user_id: str, user_input: str, audio_data: str = None, audio_format: str = None):
        """处理WebSocket聊天消息，异步任务方式（非阻塞）"""
        # 取消用户的聊天任务
        await self._cancel_user_task(user_id)
        logger.info(f"取消用户 {user_id} 的聊天任务，开始新任务")
        
        try:
            # 创建聊天请求
            chat_request = ChatRequest(
                user_id=user_id,
                message=user_input,
                audio=audio_data,
                audio_format=audio_format
            )
            
            # 启动异步聊天任务（直接发送WebSocket消息）
            chat_task = asyncio.create_task(self._process_chat_task(chat_request))
            await self._add_user_task(user_id, chat_task)
            
        except Exception as e:
            logger.error(f"处理聊天消息失败: {str(e)}")
            await self.send_websocket_message(user_id, {
                "type": "error",
                "message": f"处理失败: {str(e)}"
            })

    async def handle_websocket_connection(self, websocket, user_id: str):
        """处理WebSocket连接，包括消息循环和异常处理（支持并发消息处理）"""
        await websocket.accept()
        await self.add_websocket_connection(user_id, websocket)
        self.thread = {
            "configurable": {
                "user_id": user_id,
                "thread_id": user_id
            }
        }
        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # 验证消息格式
                if "message" not in message_data:
                    await self.send_websocket_message(user_id, {
                        "type": "error",
                        "message": "消息格式错误，缺少 'message' 字段"
                    })
                    continue
                
                user_input = message_data["message"]
                audio_data = message_data.get("audio")  # 可选的音频数据
                audio_format = message_data.get("audio_format")  # 可选的音频格式
                
                # 发送开始处理的消息
                await self.send_websocket_message(user_id, {
                    "type": "start",
                    "message": "开始处理您的消息..."
                })

                logger.info(f"收到用户 {user_id} 的消息: {user_input}")
                
                # 启动异步聊天任务（非阻塞，立即返回，会取消旧任务）
                await self.process_websocket_chat(user_id, user_input, audio_data, audio_format)
                
        except WebSocketDisconnect:
            await self.remove_websocket_connection(user_id)
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {str(e)}")
            await self.remove_websocket_connection(user_id)

