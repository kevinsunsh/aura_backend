import re
import asyncio
from loguru import logger
import uuid
import json
import random
from typing import Dict, Any, Callable, Optional, List
from datetime import datetime
from enum import Enum
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# from agents.graphs.thinking_graph import builder as thinking_graph_builder
# from agents.graphs.observing_graph import builder as observing_graph_builder
# from agents.graphs.replying_graph import builder as replying_graph_builder
# from agents.graphs.speaking_graph import builder as speaking_graph_builder
# from agents.graphs.muttering_graph import builder as muttering_graph_builder
# from agents.graphs.recalling_graph import builder as recalling_graph_builder
# from agents.graphs.memorizing_graph import builder as memorizing_graph_builder
from .aura_memory.message_store import MessageStore, Message
from utils.utils import performance_point_context
from .task_manager import TaskManager, TaskType, TaskStateType
from configuration import get_db_conn_string, get_chat_model_by_type
from agents.prompts.replying_prompt import (
    REPLYING_GENERATOR_DIRECT_PROMPT,
    REPLYING_CHECK_PROMPT
)
from agents.aura_memory.chat_stream import ChatStreamManager
from utils.utils import start_performance_point, end_performance_point
from utils.todo_mock_func import (
    _build_chat_history_str
)
from langchain_core.messages import SystemMessage
from api_protocol.constant import *

history_check_interval = 20000 #ms

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""
    def __init__(self, 
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = None
        self.user_id = None
        self.websocket_send_callback = websocket_send_callback
        self.replying_task_handle: asyncio.Task = None
        self.save_message_tasks: List[asyncio.Task] = []
    
    async def start(self, chat_id: str, user_id: str, session_prompt: str = ""):
        self.chat_id = chat_id
        self.user_id = user_id
        self.session_prompt = session_prompt
        TaskManager.initialize()
        # await TaskManager.get_instance().set_task_state(TaskType.THINKING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.OBSERVING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.RECALLING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MEMORIZING, TaskStateType.RUNNING)

    async def user_input_interruption(self):
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.PAUSED)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.PAUSED)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.PAUSED)
        logger.info(f"用户输入打断，取消回复任务")
        if self.replying_task_handle:
            self.replying_task_handle.cancel()
    
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
            
            await self.user_input_resume()
            if self.replying_task_handle and not self.replying_task_handle.done():
                self.replying_task_handle.cancel()
                try:
                    await self.replying_task_handle
                except asyncio.CancelledError:
                    pass
            save_message_task_handle = asyncio.create_task(self._save_message_task(self.user_id, user_input))
            self.save_message_tasks.append(save_message_task_handle)
            self.save_message_tasks = [task for task in self.save_message_tasks if not task.done()]
            replying_task_handle = asyncio.create_task(self._replying_response_task(user_input))
            self.replying_task_handle = replying_task_handle
            logger.info(f"文本消息已存储: chat_id={self.chat_id}, content_length={len(user_input)}")
            
            return {
                "success": True,
                "message_type": "text",
                "msg_id": str(uuid.uuid4()),
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
    
    async def _save_message_task(self, user_id: str, message_str: str, update_checked_at: bool = False):
        """保存消息任务"""
        try:
            # 创建消息对象
            message = Message(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_id,
                user_id=user_id,
                platform="default",
                m_type="text",
                content=message_str,
                data={},
                created_at=int(datetime.now().timestamp() * 1000)
            )
            # 存储到消息存储
            MessageStore.get_instance().add_message(message)
            if update_checked_at:
                ChatStreamManager.get_instance().update_chat_stream_checked_at(self.chat_id)
        except Exception as e:
            logger.error(f"保存消息任务失败: {e}")
    
    # async def _muttering_process_task(self):
    #     """自言自语任务"""
    #     try:
    #         logger.debug(f"开始自言自语任务: chat_id={self.chat_id}")
    #                     # 处理输入数据
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"streaming_{self.chat_id}"
    #             }
    #         }

    #         graph = muttering_graph_builder.compile()
    #         while True:
    #             async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
    #                 # 解析messages事件中的AIMessageChunk内容
    #                 type, message_tuple = event
    #                 if "updates" == type:
    #                     if "generate_muttering" in message_tuple:
    #                         if message_tuple["generate_muttering"]["muttering_response"] == "finished":
    #                             if self.websocket_send_callback:
    #                                 await self.websocket_send_callback({
    #                                     "event": ServerEvent.MutteringResponse,
    #                                     "payload_msg": {
    #                                         "content": message_tuple["generate_muttering"]["muttering_content"]
    #                                     }
    #                                 })
    #                                 await asyncio.sleep(1)
    #     except asyncio.CancelledError:
    #         # 只在最外层处理取消，记录日志但不重新抛出
    #         logger.info(f"自言自语任务被取消: chat_id={self.chat_id}")
    #         # 不重新抛出，让任务自然结束
    #     except Exception as e:
    #         logger.error(f"自言自语任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    async def _replying_response_task(self, user_input: str):
        try:
            # 获取新消息
            now_timestamp = int(datetime.now().timestamp() * 1000)
            history_messages = MessageStore.get_instance().get_messages_by_time_range(
                self.chat_id, 
                now_timestamp - history_check_interval, 
                now_timestamp
            )
            
            # 更新观察信息
            chat_history_str = _build_chat_history_str(history_messages)
            chat_history_str += f"{self.user_id}说: {user_input}\n"
            logger.debug(f"observe_conversation chat_history_str: {chat_history_str}")

            # plan_model = get_chat_model_by_type("pfc_action_planner")
            # check_prompt = REPLYING_CHECK_PROMPT.format(chat_history_str=chat_history_str)
            # check_response = await plan_model.ainvoke([
            #     SystemMessage(content=check_prompt)
            # ])
            # if "false" in check_response.content.lower():
            #     return
            
            # 使用LLM生成立即回复
            chat_model = get_chat_model_by_type("pfc_chat")
            thinking_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.THINKING)
            goals_str = thinking_task_shared_data.get("goals_str", "")
            knowledge_info_str = thinking_task_shared_data.get("knowledge_info_str", "")
            persona_text = self.session_prompt
            logger.bind(tag="BASE").info(f"persona_text: {persona_text}")
            # 格式化提示词
            prompt = REPLYING_GENERATOR_DIRECT_PROMPT.format(
                persona_text=persona_text,
                goals_str=goals_str,
                knowledge_info_str=knowledge_info_str,
                chat_history_str=chat_history_str
            )
            # 生成立即回复
            final_response = ""
            logger.debug(f"开始回复 delay: {int(datetime.now().timestamp() * 1000) - now_timestamp}ms")
            async for chunk in chat_model.astream([
                SystemMessage(content=prompt)
            ],
            extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    logger.debug(f"生成回复内容 delay: {int(datetime.now().timestamp() * 1000) - now_timestamp}ms")
                    if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.PAUSED:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    logger.debug(f"生成回复内容: {chunk.content}")
                    final_response += chunk.content
                    if self.websocket_send_callback:
                        await self.websocket_send_callback({
                            "event": ServerEvent.ChatResponse,
                            "payload_msg": {
                                "content": str(chunk.content)
                            }
                        })
            if self.websocket_send_callback:
                await self.websocket_send_callback({
                    "event": ServerEvent.ChatEnded,
                })
            save_message_task_handle = asyncio.create_task(self._save_message_task("aura", final_response, update_checked_at=True))
            self.save_message_tasks.append(save_message_task_handle)
        except asyncio.CancelledError:
            logger.info(f"回复任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.error(f"生成被动回复时出错: {str(e)}")
    
    # async def _replying_response_task(self):
    #     """回复任务"""
    #     try:
    #         logger.info(f"开始回复任务: chat_id={self.chat_id}")
    #                     # 处理输入数据
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"streaming_{self.chat_id}"
    #             }
    #         }
    #         async with AsyncPostgresSaver.from_conn_string(get_db_conn_string()) as checkpointer:
    #             graph = replying_graph_builder.compile(checkpointer=checkpointer)
    #             while True:
    #                 async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
    #                     # 解析messages事件中的AIMessageChunk内容
    #                     type, message_tuple = event
    #                     if "messages" == type:
    #                         if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
    #                             # 第一个元素是消息类型，第二个元素是消息对象
    #                             message_obj, message_meta = message_tuple
    #                             if message_obj.content and message_meta["langgraph_node"] == "generate_reply":
    #                                 if self.websocket_send_callback:
    #                                     await self.websocket_send_callback({
    #                                         "event": ServerEvent.ChatResponse,
    #                                         "payload_msg": {
    #                                             "content": str(message_obj.content)
    #                                         }
    #                                     })
    #                     if "updates" == type:
    #                         if "generate_reply" in message_tuple:
    #                             if message_tuple["generate_reply"]["replaying_response"] == "finished":
    #                                 if self.websocket_send_callback:
    #                                     await self.websocket_send_callback({
    #                                         "event": ServerEvent.ChatEnded,
    #                                     })
    #     except asyncio.CancelledError:
    #         # 只在最外层处理取消，记录日志但不重新抛出
    #         logger.info(f"回复任务被取消: chat_id={self.chat_id}")
    #         # 不重新抛出，让任务自然结束
    #     except Exception as e:
    #         logger.error(f"回复任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    # async def _speaking_response_task(self):
    #     """说话任务"""
    #     try:
    #         logger.info(f"开始说话任务: chat_id={self.chat_id}")
    #                     # 处理输入数据
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"streaming_{self.chat_id}"
    #             }
    #         }

    #         # 使用优化的异步PostgreSQL连接
    #         async with AsyncPostgresSaver.from_conn_string(get_db_conn_string()) as checkpointer:
    #             graph = speaking_graph_builder.compile(checkpointer=checkpointer)
    #             while True:
    #                 async for event in graph.astream(input_data, thread, stream_mode=["updates", "messages"]):
    #                     # 解析messages事件中的AIMessageChunk内容
    #                     type, message_tuple = event
    #                     if "messages" == type:
    #                         if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
    #                             # 第一个元素是消息类型，第二个元素是消息对象
    #                             message_obj, message_meta = message_tuple
    #                             if message_obj.content and message_meta["langgraph_node"] == "generate_new_message":
    #                                 if self.websocket_send_callback:
    #                                     await self.websocket_send_callback({
    #                                         "event": ServerEvent.ChatResponse,
    #                                         "payload_msg": {
    #                                             "content": str(message_obj.content)
    #                                         }
    #                                     })
    #                     if "updates" == type:
    #                         if "generate_new_message" in message_tuple:
    #                             if message_tuple["generate_new_message"]["speaking_response"] == "finished":
    #                                 if self.websocket_send_callback:
    #                                     await self.websocket_send_callback({
    #                                         "event": ServerEvent.ChatEnded,
    #                                     })
    #                         # if "listen_for_user" in message_tuple:
    #                         #     if message_tuple["listen_for_user"]["streaming_response"] == "finished":
    #                         #         if self.websocket_send_callback:
    #                         #             await self.websocket_send_callback({
    #                         #                 "event": ServerEvent.ChatEnded,
    #                         #             })
    #     except asyncio.CancelledError:
    #         # 只在最外层处理取消，记录日志但不重新抛出
    #         logger.info(f"说话任务被取消: chat_id={self.chat_id}")
    #         # 不重新抛出，让任务自然结束
    #     except Exception as e:
    #         logger.error(f"说话任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    # async def _thinking_process_task(self):
    #     """异步处理思考任务"""
    #     try:
    #         # 处理输入数据
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"thinking_{self.chat_id}"
    #             }
    #         }
            
    #         # 使用优化的异步PostgreSQL连接
    #         # async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
    #             # graph = thinking_graph_builder.compile(checkpointer=checkpointer)
    #         graph = thinking_graph_builder.compile()
    #         while True:
    #             async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
    #                 type, message_tuple = event
    #                 if "updates" == type:
    #                     pass
    #     except asyncio.CancelledError:
    #         logger.info(f"思考任务被取消: chat_id={self.chat_id}")
    #     except Exception as e:
    #         logger.error(f"思考任务处理失败: chat_id={self.chat_id}, error={str(e)}")
    
    # async def _observing_process_task(self):
    #     """异步处理观察任务"""
    #     try:
    #         # 处理输入数据
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"observing_{self.chat_id}",
    #             }
    #         }
            
    #         # 使用优化的异步PostgreSQL连接
    #         # async with AsyncPostgresSaver.from_conn_string(self.db_conn_string) as checkpointer:
    #             # graph = observing_graph_builder.compile(checkpointer=checkpointer)
    #         graph = observing_graph_builder.compile()
    #         while True:
    #             async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
    #                 type, message_tuple = event
    #                 if "updates" == type:
    #                     pass
    #     except asyncio.CancelledError:
    #         logger.info(f"观察任务被取消: chat_id={self.chat_id}")
    #     except Exception as e:
    #         logger.error(f"观察任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    # async def _recalling_process_task(self):
    #     """异步处理回忆任务"""
    #     try:
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"recalling_{self.chat_id}"
    #             }
    #         }
    #         graph = recalling_graph_builder.compile()
    #         while True:
    #             async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
    #                 type, message_tuple = event
    #                 if "updates" == type:
    #                     pass
    #     except asyncio.CancelledError:
    #         logger.info(f"回忆任务被取消: chat_id={self.chat_id}")
    #     except Exception as e:
    #         logger.error(f"回忆任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    # async def _memorizing_process_task(self):
    #     """异步处理记忆任务"""
    #     try:
    #         input_data = {
    #             "chat_id": self.chat_id,
    #             "user_id": self.user_id,
    #         }
    #         thread = {
    #             "configurable": {
    #                 "thread_id": f"memorizing_{self.chat_id}"
    #             }
    #         }
    #         graph = memorizing_graph_builder.compile()
    #         while True:
    #             async for event in graph.astream(input_data, thread, stream_mode=["updates"]):
    #                 type, message_tuple = event
    #                 if "updates" == type:
    #                     pass
    #     except asyncio.CancelledError:
    #         logger.info(f"记忆任务被取消: chat_id={self.chat_id}")
    #     except Exception as e:
    #         logger.error(f"记忆任务处理失败: chat_id={self.chat_id}, error={str(e)}")

    async def cleanup(self):
        """清理资源"""
        logger.info("MessageProcessorText资源清理完成")
