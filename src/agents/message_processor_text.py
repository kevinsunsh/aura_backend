import asyncio
import logging
import uuid
import json
import random
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from enum import Enum
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.graphs.thinking_graph import builder as thinking_graph_builder
from agents.graphs.observing_graph import builder as observing_graph_builder
from agents.graphs.replying_graph import builder as replying_graph_builder
from agents.graphs.speaking_graph import builder as speaking_graph_builder
from agents.graphs.muttering_graph import builder as muttering_graph_builder
from agents.graphs.recalling_graph import builder as recalling_graph_builder
from agents.graphs.memorizing_graph import builder as memorizing_graph_builder
from .aura_memory.message_store import MessageStore, Message
from utils.utils import performance_point_context
from .task_manager import TaskManager, TaskType, TaskStateType
from configuration import get_db_conn_string
from api_protocol.constant import *

logger = logging.getLogger(__name__)

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""
    def __init__(self, 
                 chat_id: str,
                 user_id: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = chat_id
        self.user_id = user_id
        self.websocket_send_callback = websocket_send_callback
    
    async def start(self):
        TaskManager.initialize(
            replying_task_handle=asyncio.create_task(
                self._replying_response_task()
            ),
            speaking_task_handle=asyncio.create_task(
                self._speaking_response_task()
            ),
            muttering_task_handle=asyncio.create_task(
                self._muttering_process_task()
            ),
            thinking_task_handle=asyncio.create_task(
                self._thinking_process_task()
            ),
            observing_task_handle=asyncio.create_task(
                self._observing_process_task()
            ),
            recalling_task_handle=asyncio.create_task(
                self._recalling_process_task()
            ),
            memorizing_task_handle=asyncio.create_task(
                self._memorizing_process_task()
            )
        )
        # await TaskManager.get_instance().set_task_state(TaskType.THINKING, TaskStateType.RUNNING)
        await TaskManager.get_instance().set_task_state(TaskType.OBSERVING, TaskStateType.RUNNING)
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.RECALLING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MEMORIZING, TaskStateType.RUNNING)

    async def user_input_interruption(self):
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.PAUSED)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.PAUSED)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.PAUSED)

    async def user_input_resume(self):
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)

    async def handle_text_message(self, 
                                message_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理文本消息"""
        try:
            # 支持统一协议格式的payload_msg
            user_input = None
            if "message" in message_data and message_data["message"]:
                # 向后兼容：直接message字段
                user_input = message_data["message"]
            
            if not user_input:
                return {
                    "success": False,
                    "error": "消息中没有找到有效的文本内容",
                    "message_type": "text"
                }
            
            # 创建消息对象
            message = Message(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_id,
                user_id=self.user_id,
                platform="default",
                m_type="text",
                content=user_input,
                data=message_data.get("data", {}),
                created_at=int(datetime.now().timestamp() * 1000)
            )
            
            # 存储到消息存储
            MessageStore.get_instance().add_message(message)
            await self.user_input_resume()

            logger.info(f"文本消息已存储: chat_id={self.chat_id}, content_length={len(user_input)}")
            
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
    
    async def _muttering_process_task(self):
        """自言自语任务"""
        try:
            logger.info(f"开始自言自语任务: chat_id={self.chat_id}")
                        # 处理输入数据
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"streaming_{self.chat_id}"
                }
            }

            graph = muttering_graph_builder.compile()
            while True:
                async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                    # 解析messages事件中的AIMessageChunk内容
                    type, message_tuple = event
                    if "updates" == type:
                        if "generate_muttering" in message_tuple:
                            if message_tuple["generate_muttering"]["muttering_response"] == "finished":
                                if self.websocket_send_callback:
                                    await self.websocket_send_callback({
                                        "event": ServerEvent.MutteringResponse,
                                        "payload_msg": {
                                            "content": message_tuple["generate_muttering"]["muttering_content"]
                                        }
                                    })
                                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"自言自语任务被取消: chat_id={self.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"自言自语任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    async def _replying_response_task(self):
        """回复任务"""
        try:
            logger.info(f"开始回复任务: chat_id={self.chat_id}")
                        # 处理输入数据
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"streaming_{self.chat_id}"
                }
            }

            graph = replying_graph_builder.compile()
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
                                        "event": ServerEvent.ChatResponse,
                                        "payload_msg": {
                                            "content": str(message_obj.content)
                                        }
                                    })
                    if "updates" == type:
                        if "generate_reply" in message_tuple:
                            if message_tuple["generate_reply"]["replaying_response"] == "finished":
                                if self.websocket_send_callback:
                                    await self.websocket_send_callback({
                                        "event": ServerEvent.ChatEnded,
                                    })
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"回复任务被取消: chat_id={self.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"回复任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    async def _speaking_response_task(self):
        """说话任务"""
        try:
            logger.info(f"开始说话任务: chat_id={self.chat_id}")
                        # 处理输入数据
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"streaming_{self.chat_id}"
                }
            }

            # 使用优化的异步PostgreSQL连接
            async with AsyncPostgresSaver.from_conn_string(get_db_conn_string()) as checkpointer:
                graph = speaking_graph_builder.compile(checkpointer=checkpointer)
                while True:
                    async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
                        # 解析messages事件中的AIMessageChunk内容
                        type, message_tuple = event
                        if "messages" == type:
                            if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                # 第一个元素是消息类型，第二个元素是消息对象
                                message_obj, message_meta = message_tuple
                                if message_obj.content and message_meta["langgraph_node"] == "generate_new_message":
                                    if self.websocket_send_callback:
                                        await self.websocket_send_callback({
                                            "event": ServerEvent.ChatResponse,
                                            "payload_msg": {
                                                "content": str(message_obj.content)
                                            }
                                        })
                        if "updates" == type:
                            if "generate_new_message" in message_tuple:
                                if message_tuple["generate_new_message"]["speaking_response"] == "finished":
                                    if self.websocket_send_callback:
                                        await self.websocket_send_callback({
                                            "event": ServerEvent.ChatEnded,
                                        })
                            # if "listen_for_user" in message_tuple:
                            #     if message_tuple["listen_for_user"]["streaming_response"] == "finished":
                            #         if self.websocket_send_callback:
                            #             await self.websocket_send_callback({
                            #                 "event": ServerEvent.ChatEnded,
                            #             })
        except asyncio.CancelledError:
            # 只在最外层处理取消，记录日志但不重新抛出
            logger.info(f"说话任务被取消: chat_id={self.chat_id}")
            # 不重新抛出，让任务自然结束
        except Exception as e:
            logger.error(f"说话任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    async def _thinking_process_task(self):
        """异步处理思考任务"""
        try:
            # 处理输入数据
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"thinking_{self.chat_id}"
                }
            }
            
            # 使用优化的异步PostgreSQL连接
            # async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                # graph = thinking_graph_builder.compile(checkpointer=checkpointer)
            graph = thinking_graph_builder.compile()
            while True:
                async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                    type, message_tuple = event
                    if "updates" == type:
                        pass
        except asyncio.CancelledError:
            logger.info(f"思考任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.error(f"思考任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    async def _observing_process_task(self):
        """异步处理观察任务"""
        try:
            # 处理输入数据
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"observing_{self.chat_id}",
                }
            }
            
            # 使用优化的异步PostgreSQL连接
            # async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
                # graph = observing_graph_builder.compile(checkpointer=checkpointer)
            graph = observing_graph_builder.compile()
            while True:
                async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                    type, message_tuple = event
                    if "updates" == type:
                        pass
        except asyncio.CancelledError:
            logger.info(f"观察任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.error(f"观察任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    async def _recalling_process_task(self):
        """异步处理回忆任务"""
        try:
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"recalling_{self.chat_id}"
                }
            }
            graph = recalling_graph_builder.compile()
            while True:
                async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                    type, message_tuple = event
                    if "updates" == type:
                        pass
        except asyncio.CancelledError:
            logger.info(f"回忆任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.error(f"回忆任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    async def _memorizing_process_task(self):
        """异步处理记忆任务"""
        try:
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
            }
            thread = {
                "configurable": {
                    "thread_id": f"memorizing_{self.chat_id}"
                }
            }
            graph = memorizing_graph_builder.compile()
            while True:
                async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
                    type, message_tuple = event
                    if "updates" == type:
                        pass
        except asyncio.CancelledError:
            logger.info(f"记忆任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.error(f"记忆任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    async def cleanup(self):
        """清理资源"""
        try:
            with performance_point_context("取消所有任务"):
                # 获取所有需要取消的任务类型
                TaskManager.get_instance().cleanup()
                logger.info("MessageProcessorText资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时发生异常: {e}")
