import re
import asyncio
from loguru import logger
from datetime import datetime
from typing import Dict, Any, Callable, List
from agents.agent_memory.configuration import get_chat_model_by_type
from api_protocol.constant import *
from langchain_core.messages import SystemMessage
from langchain_core.messages import HumanMessage, AIMessage

class StreamingTagParser:
    def __init__(self, tag_callback=None):
        self.buffer: List[str] = []  # 保持完整的token列表
        self.state = "OUTSIDE"  # 初始状态：OUTSIDE
        self.tag_callback = tag_callback
        
        # 标签相关状态
        self.current_tag_type: str = ""  # 'speak', 'action', 'psych', 'scene'
        self.current_tag_attribute: str = ""  # 标签的属性值（如mood）
    # 接收新的文本块并处理（保持token完整性）
    async def feed(self, chunk: str):
        """接收新的文本块并处理（保持token完整性）"""
        # 不分割token，直接将完整chunk作为单个token处理
        if chunk:  # 只有非空chunk才添加
            self.buffer.append(chunk)
        await self._process_buffer()
    # 处理缓冲区内容
    async def _process_buffer(self):
        """处理缓冲区内容"""
        while self.buffer:
            processed = False
            
            if self.state == "OUTSIDE":
                processed = await self._handle_outside()
            elif self.state == "IN_TAG_NAME":
                processed = await self._handle_in_tag_name()
            elif self.state == "IN_TAG_ATTRIBUTE":
                processed = await self._handle_in_tag_attribute()
            elif self.state == "IN_TAG_CONTENT":
                processed = await self._handle_in_tag_content()
                
            if not processed:
                break
    # 处理OUTSIDE状态：查找<开始符
    async def _handle_outside(self):
        """处理OUTSIDE状态：查找<开始符"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找第一个<的位置
        tag_start_pos = token.find('<')
        if tag_start_pos != -1:
            # 找到了开始符
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果<前面有内容，根据规范应该忽略
            
            # 如果<后面还有内容，放回剩余部分
            if tag_start_pos + 1 < len(token):
                self.buffer.insert(0, token[tag_start_pos + 1:])
            
            self.state = "IN_TAG_NAME"
            self.current_tag_type = ""
            self.current_tag_attribute = ""
            return True
        else:
            # 没找到<，忽略整个token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_NAME状态：查找标签名称
    async def _handle_in_tag_name(self):
        """处理标签名称"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找:或>的位置
        colon_pos = token.find(':')
        close_pos = token.find('>')
        
        if colon_pos != -1 and (close_pos == -1 or colon_pos < close_pos):
            # 找到:且在>之前
            tag_name = self.current_tag_type + token[:colon_pos]
            self.current_tag_type = tag_name
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果:后面还有内容，放回剩余部分
            if colon_pos + 1 < len(token):
                self.buffer.insert(0, token[colon_pos + 1:])
            
            self.state = "IN_TAG_ATTRIBUTE"
            return True
        elif close_pos != -1:
            # 找到>，没有属性
            tag_name = self.current_tag_type + token[:close_pos]
            self.current_tag_type = tag_name
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果>后面还有内容，放回剩余部分
            if close_pos + 1 < len(token):
                self.buffer.insert(0, token[close_pos + 1:])
            
            # 发送标签开始事件
            if self.tag_callback:
                attributes = {}
                if len(self.current_tag_attribute) > 0:
                    # 如果是speak标签，attribute就是mood
                    if self.current_tag_type == "speak":
                        attributes["mood"] = self.current_tag_attribute
                    else:
                        attributes["attribute"] = self.current_tag_attribute
                
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "start",
                    "attributes": attributes
                })
            
            self.state = "IN_TAG_CONTENT"
            return True
        else:
            # 没找到:或>，整个token都是标签名的一部分
            self.current_tag_type += token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_ATTRIBUTE状态：查找标签属性
    async def _handle_in_tag_attribute(self):
        """处理标签属性"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找>的位置
        close_pos = token.find('>')
        if close_pos != -1:
            # 找到>
            attribute = self.current_tag_attribute + token[:close_pos]
            self.current_tag_attribute = attribute
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果>后面还有内容，放回剩余部分
            if close_pos + 1 < len(token):
                self.buffer.insert(0, token[close_pos + 1:])
            
            # 发送标签开始事件
            if self.tag_callback:
                attributes = {}
                if len(self.current_tag_attribute) > 0:
                    attributes["attribute"] = self.current_tag_attribute
                
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "start",
                    "attributes": attributes
                })
            
            self.state = "IN_TAG_CONTENT"
            return True
        else:
            # 没找到>，整个token都是属性的一部分
            self.current_tag_attribute += token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_CONTENT状态：查找标签内容
    async def _handle_in_tag_content(self):
        """处理标签内容直到遇到下一个<"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找下一个<的位置（新标签开始）
        next_tag_pos = token.find('<')
        if next_tag_pos != -1:
            # 找到下一个标签开始，当前标签内容结束
            content = token[:next_tag_pos]
            
            if content and self.tag_callback:
                # 发送标签内容流
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "streaming",
                    "content": content
                })
            # 发送标签结束事件
            if self.tag_callback:
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "end"
                })
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 将剩余部分放回缓冲区
            if next_tag_pos < len(token):
                self.buffer.insert(0, token[next_tag_pos:])
            
            # 重置状态，准备处理下一个标签
            self.current_tag_type = ""
            self.current_tag_attribute = ""
            self.state = "OUTSIDE"  # 重置状态，准备处理下一个标签
            return True
        else:
            # 没找到下一个<，整个token都是当前标签内容
            if token and self.tag_callback:
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "streaming",
                    "content": token
                })
            self.buffer.pop(0)
            return True
    # 处理结束事件
    async def end(self):
        if self.tag_callback:
            await self.tag_callback({
                "tag": self.current_tag_type,
                "status": "end"
            })

class MessageProcessorText:
    """文本消息处理器，负责处理文本消息并启动aura聊天任务"""

    def __init__(self, 
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None,
                 process_timer: Any = None):
        self.chat_id = None
        self.user_id = None
        self.websocket_send_callback = websocket_send_callback
        self.process_timer = process_timer
        self.parser = StreamingTagParser(tag_callback=self.tag_callback)
        self.request_tasks = []
        self.dismiss_tasks = []
    
    async def tag_callback(self, payload):
        if payload["tag"] == "speak":
            if payload["status"] == "start":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatResponseParams,
                        "payload_msg": {
                            "params": payload["attributes"]
                        }
                    })
            elif payload["status"] == "streaming":
                if self.websocket_send_callback:
                    content = payload["content"].replace('\n', '').replace('\r', '')
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatResponse,
                        "payload_msg": {
                            "content": content
                        }
                    })
            elif payload["status"] == "end":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatResponseEnd,
                    })
        elif payload["tag"] == "scene":
            if payload["status"] == "start":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEnvDescParams,
                        "payload_msg": {
                            "params": payload["attributes"]
                        }
                    })
            elif payload["status"] == "streaming":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEnvDesc,
                        "payload_msg": {
                            "content": payload["content"]
                        }
                    })
            elif payload["status"] == "end":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEnvDescEnd,
                    })
        elif payload["tag"] == "action":
            if payload["status"] == "start":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatActionParams,
                        "payload_msg": {
                            "params": payload["attributes"]
                        }
                    })
            elif payload["status"] == "streaming":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatAction,
                        "payload_msg": {
                            "content": payload["content"]
                        }
                    })
            elif payload["status"] == "end":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatActionEnd,
                    })
        elif payload["tag"] == "psych":
            if payload["status"] == "start":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEmotionParams,
                        "payload_msg": {
                            "params": payload["attributes"]
                        }
                    })
            elif payload["status"] == "streaming":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEmotion,
                        "payload_msg": {
                            "content": payload["content"]
                        }
                    })
            elif payload["status"] == "end":
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatEmotionEnd,
                    })
        elif payload["tag"] == "request_task":
            if payload["status"] == "start":
                task_string = ""
                for key, value in payload['attributes'].items():
                    task_string += f"{key}=\"{value}\" "
                self.request_tasks.append(f"<task {task_string} />")
            elif payload["status"] == "streaming":
                pass
            elif payload["status"] == "end":
                pass
        elif payload["tag"] == "dismiss_task":
            if payload["status"] == "start":
                task_string = ""
                for key, value in payload['attributes'].items():
                    task_string += f"{key}=\"{value}\" "
                self.dismiss_tasks.append(f"<task {task_string} />")
            elif payload["status"] == "streaming":
                pass
            elif payload["status"] == "end":
                pass
    
    async def start(self, chat_id: str, user_id: str):
        self.chat_id = chat_id
        self.user_id = user_id
        self.is_interruption = False
        self.interruption_lock = asyncio.Lock()
    
    async def user_input_interruption(self):
        async with self.interruption_lock:
            self.is_interruption = True
    
    async def user_input_resume(self):
        async with self.interruption_lock:
            self.is_interruption = False
    
    async def handle_message(self, prompts: list[dict]) -> Dict[str, Any]:
        """处理文本消息"""
        try:
            await self.user_input_resume()
            await self._replying_response_task(prompts)
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
    async def _replying_response_task(self, prompts: list[dict]):
        try:
            for prompt in prompts:
                logger.bind(tag="BASE").info(f"{prompt['role']}: {prompt['content']}")
            # 使用LLM生成立即回复
            # chat_model = get_chat_model_by_type("pfc_action_planner")
            # logger.bind(tag="DELAY").debug(f"get model delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
            # prompt = REPLYING_TASK_PROMPT.format(
            #     input_info=input_info,
            #     requirement=REPLYING_REQUIREMENT_PROMPT,
            #     mood=speaker_config["female_2"]["mood_str"],
            #     mood_level=MoodLevel.get_mood_level_str(),
            #     speech_rate=SpeechRate.get_speech_rate_str(),
            #     action="Tilt_head(for question)|Nod(for agreement)|No_action(for neutral/ignore)",
            #     request_tasks_prompt=TaskManager.get_instance().get_request_tasks_prompt(),
            #     dismiss_tasks_prompt=TaskManager.get_instance().get_dismiss_tasks_prompt()
            # )
            # character = CharacterManager().get_character_by_name("Seraphina")
            # system_preset = SystemPresetManager().get_system_preset_by_name("deepseek-R1 北棱预设v1.2 test(角色扮演特化)")
            # generator = PromptManager(
            #     chat_id="test_user_123444",
            #     user_id="test_user_123444",
            #     system_preset=system_preset,
            #     character=character,
            #     world_info_scanner=WorldInfoScanner()
            # )
            # prompts = await generator.generate(GenerationType.NORMAL, GenerationOptions())
            chat_model = get_chat_model_by_type("vlm")
            # messages = []
            # for prompt in prompts:
            #     logger.bind(tag="TASK").info(f"prompt: {prompt}")
            #     if prompt["role"] == "user":
            #         messages.append(HumanMessage(content=prompt["content"]))
            #     elif prompt["role"] == "assistant":
            #         messages.append(AIMessage(content=prompt["content"]))
            #     else:
            #         messages.append(SystemMessage(content=prompt["content"]))
            # 生成立即回复
            final_response = ""
            first_chunk = True
            logger.bind(tag="DELAY").info(f"start llm response delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
            async for chunk in chat_model.astream(prompts, extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    if self.is_interruption:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    final_response += chunk.content
                    if first_chunk:
                        first_chunk = False
                        logger.bind(tag="TTS").info(f"start streaming response delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
                    await self.parser.feed(chunk.content)
            await self.parser.end()
            if self.websocket_send_callback:
                await self.websocket_send_callback({
                    "event": ServerEvent.ChatEnded,
                    "payload_msg": {
                        "content": final_response,
                        "request_tasks": "".join(self.request_tasks),
                        "dismiss_tasks": "".join(self.dismiss_tasks)
                    }
                })
            logger.bind(tag="TASK").info(f"final_response: {final_response}, request_tasks: {self.request_tasks}, dismiss_tasks: {self.dismiss_tasks}")
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
