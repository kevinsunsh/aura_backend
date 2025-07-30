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
    REPLYING_TASK_PROMPT,
    REPLYING_REQUIREMENT_PROMPT
)
from agents.aura_memory.chat_stream import ChatStreamManager
from utils.utils import start_performance_point, end_performance_point
from langchain_core.messages import SystemMessage
from api_protocol.constant import *
from agents.doubao_client.doubao_config import speaker_config, MoodLevel, SpeechRate
import re

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""
    def __init__(self, 
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = None
        self.user_id = None
        self.websocket_send_callback = websocket_send_callback
    
    async def start(self, chat_id: str, user_id: str):
        self.chat_id = chat_id
        self.user_id = user_id
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
    
    async def user_input_resume(self):
        await TaskManager.get_instance().set_task_state(TaskType.REPLYING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.SPEAKING, TaskStateType.RUNNING)
        # await TaskManager.get_instance().set_task_state(TaskType.MUTTERING, TaskStateType.RUNNING)
    
    async def handle_message(self, input_info: str) -> Dict[str, Any]:
        """处理文本消息"""
        try:
            await self.user_input_resume()
            await self._replying_response_task(input_info)
        except Exception as e:
            logger.error(f"处理文本消息失败: {e}")
    
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

    async def _replying_response_task(self, input_info: str):
        try:            
            # 使用LLM生成立即回复
            chat_model = get_chat_model_by_type("planner")
            prompt = REPLYING_TASK_PROMPT.format(
                input_info=input_info,
                requirement=REPLYING_REQUIREMENT_PROMPT,
                mood=speaker_config["female_2"]["mood_str"],
                mood_level=MoodLevel.get_mood_level_str(),
                speech_rate=SpeechRate.get_speech_rate_str(),
                action="Tilt_head(for question)|Nod(for agreement)|No_action(for neutral/ignore)"
            )
            # 生成立即回复
            final_response = ""

            # 状态机解析<response ...>流式内容
            state = "OUTSIDE"
            param_cache = {}
            response_buffer = ""
            end_tag = "</res>"
            async for chunk in chat_model.astream([
                SystemMessage(content=prompt)
            ],
            extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    if TaskManager.get_instance().get_task_state(TaskType.REPLYING) == TaskStateType.PAUSED:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    response_buffer += chunk.content
                    if state == "OUTSIDE":
                        idx = response_buffer.find("<res")
                        if idx != -1:
                            gt_idx = response_buffer.find(">", idx)
                            if gt_idx != -1:
                                tag_str = response_buffer[idx:gt_idx+1]
                                # 用key=value正则提取参数
                                params = dict(re.findall(r'(\w+)=([\w\-]+)', tag_str))
                                param_cache = {
                                    'mood': params.get('mood'),
                                    'mood_level': params.get('mood_level'),
                                    'speech_rate': params.get('speech_rate'),
                                    'action': params.get('action'),
                                }
                                # 解析出参数后立即发送一次消息，event 留 TODO
                                if self.websocket_send_callback:
                                    await self.websocket_send_callback({
                                        "event": ServerEvent.ChatResponseParams,
                                        "payload_msg": {
                                            "params": param_cache
                                        }
                                    })
                                state = "INSIDE"
                                response_buffer = response_buffer[gt_idx+1:]
                        else:
                            find_todo_idx = response_buffer.find("</todo_tasks>")
                            if find_todo_idx != -1:
                                # 匹配 <todo_tasks> 标签之间的内容
                                match = re.search(r"<todo_tasks>(.*?)</todo_tasks>", response_buffer, re.DOTALL)
                                todo_tasks = match.group(1).strip() if match else ""
                                logger.debug(f"找到可执行任务: {todo_tasks}")
                    elif state == "INSIDE":
                        end_idx = response_buffer.find(end_tag)
                        if end_idx != -1:
                            content_piece = response_buffer[:end_idx]
                            if content_piece:
                                logger.debug(f"生成回复内容: {content_piece}")
                                final_response += content_piece
                                if self.websocket_send_callback:
                                    await self.websocket_send_callback({
                                        "event": ServerEvent.ChatResponse,
                                        "payload_msg": {
                                            "content": str(content_piece)
                                        }
                                    })
                            response_buffer = response_buffer[end_idx+len(end_tag):]
                            state = "OUTSIDE"
                        else:
                            # 高效end_tag前缀判断逻辑：逐位比较，只要有一位不等立即break
                            max_check = min(len(response_buffer), len(end_tag))
                            matched = 0
                            for i in range(max_check):
                                if response_buffer[-max_check + i] == end_tag[i]:
                                    matched += 1
                                else:
                                    break
                            send_len = len(response_buffer) - matched
                            if send_len > 0:
                                content_piece = response_buffer[:send_len]
                                logger.debug(f"生成回复内容: {content_piece}")
                                final_response += content_piece
                                if self.websocket_send_callback:
                                    await self.websocket_send_callback({
                                        "event": ServerEvent.ChatResponse,
                                        "payload_msg": {
                                            "content": str(content_piece)
                                        }
                                    })
                                response_buffer = response_buffer[send_len:]
                            # 如果全部是前缀，先不发，等下次token
            if self.websocket_send_callback:
                await self.websocket_send_callback({
                    "event": ServerEvent.ChatEnded,
                    "payload_msg": {
                        "content": final_response
                    }
                })
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
