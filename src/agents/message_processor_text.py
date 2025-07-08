import asyncio
import logging
import uuid
import json
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from enum import Enum
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.graphs.thinking_graph import builder as background_graph_builder
from agents.graphs.streaming_graph import builder as streaming_graph_builder
from agents.task_manager import StreamingActionType, ThinkingActionType
from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStream, ChatStreamManager
from .configuration import ServerEventEnum
from utils.utils import performance_point_context
from .task_manager import TaskManager

logger = logging.getLogger(__name__)

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""
    def __init__(self, 
                 message_store: MessageStore,
                 chat_stream: ChatStream,
                 chat_stream_manager: ChatStreamManager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.message_store = message_store
        self.chat_stream = chat_stream
        self.chat_stream_manager = chat_stream_manager
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
    
    async def start(self):
        TaskManager.initialize(
            streaming_task_handle=asyncio.create_task(
                self._streaming_response_task(self.chat_stream)
            ),
            thinking_task_handle=asyncio.create_task(
                self._background_process_task(self.chat_stream)
            )
        )
        await TaskManager.get_instance().set_thinking_action(ThinkingActionType.THINKING)
        await TaskManager.get_instance().set_streaming_action(StreamingActionType.WAITING)
    
    async def user_input_interruption(self):
        await TaskManager.get_instance().set_streaming_action(StreamingActionType.WAITING)
    
    async def handle_text_message(self, 
                                message_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理文本消息"""
        try:
            # 支持统一协议格式的payload_msg
            user_input = None
            if "message" in message_data and message_data["message"]:
                # 向后兼容：直接message字段
                user_input = message_data["message"]
            elif "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
                if isinstance(payload_msg, dict):
                    # JSON序列化的情况，从字典中提取文本
                    if "message" in payload_msg and payload_msg["message"]:
                        user_input = payload_msg["message"]
                    elif "text" in payload_msg and payload_msg["text"]:
                        user_input = payload_msg["text"]
                elif isinstance(payload_msg, str) and payload_msg.strip():
                    # JSON序列化的情况，payload_msg本身就是文本
                    user_input = payload_msg.strip()
            
            if not user_input:
                return {
                    "success": False,
                    "error": "消息中没有找到有效的文本内容",
                    "message_type": "text"
                }
            
            # 创建消息对象
            message = Message(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_stream.chat_id,
                user_id=self.chat_stream.chat_id,
                platform="default",
                m_type="text",
                content=user_input,
                data=message_data.get("data", {}),
                created_at=int(datetime.now().timestamp() * 1000)
            )
            
            # 存储到消息存储
            self.message_store.add_message(message)
            await TaskManager.get_instance().set_streaming_action(StreamingActionType.RESPONSE)

            logger.info(f"文本消息已存储: chat_id={self.chat_stream.chat_id}, content_length={len(user_input)}")
            
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

    async def _streaming_response_task(self, 
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
                    "chat_stream_manager": self.chat_stream_manager,
                }
            }

            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                graph = streaming_graph_builder.compile(checkpointer=checkpointer)
                while True:
                    async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
                        # 解析messages事件中的AIMessageChunk内容
                        type, message_tuple = event
                        if "messages" == type:
                            if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                # 第一个元素是消息类型，第二个元素是消息对象
                                message_obj, message_meta = message_tuple
                                if message_obj.content and message_meta["langgraph_node"] == "generate_reply":
                                    if self.websocket_send_callback:
                                        await self.websocket_send_callback({
                                            "event": ServerEventEnum.ChatResponse.value,
                                            "payload_msg": {
                                                "content": str(message_obj.content)
                                            }
                                        })
                        if "updates" == type:
                            if "generate_reply" in message_tuple:
                                if message_tuple["generate_reply"]["aura_response"] == "finished":
                                    if self.websocket_send_callback:
                                        await self.websocket_send_callback({
                                            "event": ServerEventEnum.ChatEnded.value
                                        })
                            # if "listen_for_user" in message_tuple:
                            #     if message_tuple["listen_for_user"]["aura_response"] == "finished":
                            #         if self.websocket_send_callback:
                            #             await self.websocket_send_callback({
                            #                 "event": ServerEventEnum.ChatEnded.value
                            #             })
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"流式任务被取消: chat_id={chat_stream.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"流式任务处理失败: chat_id={chat_stream.chat_id}, error={str(e)}")
        
    async def _background_process_task(self, 
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
                    "chat_stream_manager": self.chat_stream_manager,
                }
            }
            
            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                graph = background_graph_builder.compile(checkpointer=checkpointer)
                while True:
                    async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                        type, message_tuple = event
                        if "updates" == type:
                            pass
        except asyncio.CancelledError:
            logger.info(f"后台任务被取消: chat_id={chat_stream.chat_id}")
        except Exception as e:
            logger.error(f"后台任务处理失败: chat_id={chat_stream.chat_id}, error={str(e)}")
    
    async def cleanup(self):
        """清理资源"""
        try:
            with performance_point_context("取消所有任务"):
                # 获取所有需要取消的任务类型
                TaskManager.get_instance().cleanup()
                logger.info("MessageProcessorText资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时发生异常: {e}")
