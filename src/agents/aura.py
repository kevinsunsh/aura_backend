import json
import uuid
import logging
import asyncio
import requests
import base64
from pydantic import BaseModel
from enum import Enum
from typing import Optional, Callable, Any, Dict
from datetime import datetime
from fastapi import WebSocketDisconnect
# 配置相关
from config import settings

from .aura_memory.message_store import MessageStore
from .aura_memory.chat_stream import ChatStreamManager
from .message_processor_audio import MessageProcessorAudio
from .message_processor_text import MessageProcessorText
from utils.utils import performance_point_context

# 配置LangChain日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langchain")
logger.setLevel(logging.INFO)

class MessageType(Enum):
    """消息类型枚举"""
    TEXT = "text"
    AUDIO = "audio"
    UNSUPPORTED = "unsupported"

class AuraAgent:
    _instance = None
    @staticmethod
    def get_instance():
        if AuraAgent._instance is None:
            AuraAgent._instance = AuraAgent()
        return AuraAgent._instance
    
    def __init__(self):
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

        # WebSocket相关
        self.websocket_connection = None  # 存储WebSocket连接
        self.websocket_lock = asyncio.Lock()  # 用于同步访问WebSocket连接
        
        self.message_processor_text = MessageProcessorText(
            message_store=self.message_store,
            chat_stream_manager=self.chat_stream_manager,
            db_conn_string=self.db_conn_string,
            websocket_send_callback=self.send_websocket_message
        )
        self.message_processor_audio = MessageProcessorAudio(
            message_store=self.message_store,
            chat_stream_manager=self.chat_stream_manager,
            db_conn_string=self.db_conn_string,
            websocket_send_callback=self.send_websocket_message
        )
    
    # WebSocket连接管理方法
    async def set_websocket_connection(self, websocket):
        """设置WebSocket连接"""
        async with self.websocket_lock:
            self.websocket_connection = websocket
            logger.info(f"用户已连接 WebSocket")
    
    async def remove_websocket_connection(self):
        """移除WebSocket连接"""
        # 先获取锁，移除WebSocket连接
        async with self.websocket_lock:
            if self.websocket_connection:
                self.websocket_connection = None
                logger.info(f"用户已断开 WebSocket 连接")

        # 在锁外进行清理操作，避免死锁
        try:
            # 清理文本消息处理器
            if hasattr(self, 'message_processor_text'):
                await self.message_processor_text.cleanup()
            
            # 清理消息分发器
            if hasattr(self, 'message_processor_audio'):
                await self.message_processor_audio.cleanup()

            # 释放聊天流锁
            if hasattr(self, 'chat_stream') and self.chat_stream:
                try:
                    self.chat_stream_manager.release_lock(self.chat_stream.chat_id)
                    logger.info(f"已释放聊天流锁: {self.chat_stream.chat_id}")
                except Exception as e:
                    logger.error(f"释放聊天流锁时出错: {e}")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
    
    async def send_websocket_message(self, message: dict):
        """发送WebSocket消息"""
        async with self.websocket_lock:
            if self.websocket_connection:
                try:
                    await self.websocket_connection.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"发送消息失败: {str(e)}")
                    await self.remove_websocket_connection()

    def _determine_message_type(self, message_data: Dict[str, Any]) -> MessageType:
        """确定消息类型"""
        if "message" in message_data and message_data["message"]:
            return MessageType.TEXT
        elif "audio" in message_data and message_data["audio"]:
            return MessageType.AUDIO
        else:
            return MessageType.UNSUPPORTED

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
        
        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_text()
                message_data = json.loads(data)

                message_type = self._determine_message_type(message_data)
                
                if message_type == MessageType.TEXT:
                    await self.message_processor_text.handle_text_message(message_data, self.chat_stream)
                elif message_type == MessageType.AUDIO:
                    await self.message_processor_audio.handle_audio_message(message_data, self.chat_stream)
                else:
                    logger.warning(f"不支持的消息类型: {message_type}")
                
        except WebSocketDisconnect:
            await self.remove_websocket_connection()
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {str(e)}")
            await self.remove_websocket_connection()
        finally:
            # 清理资源
            await self.cleanup()

    async def cleanup(self):
        """清理所有资源"""
        try:
            # 移除WebSocket连接
            await self.remove_websocket_connection()
            logger.info("AuraAgent 资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
