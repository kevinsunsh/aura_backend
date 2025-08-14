import re
import asyncio
from loguru import logger
from datetime import datetime
from typing import Dict, Any, Callable
from configuration import get_chat_model_by_type
from api_protocol.constant import *
from langchain_core.messages import SystemMessage
from langchain_core.messages import HumanMessage, AIMessage

class StreamingTagParser:
    def __init__(self, tag_callback=None):
        self.buffer = ""
        self.state = "OUTSIDE"
        self.current_tag = None
        self.attributes = {}
        self.tag_callback = tag_callback

    async def feed(self, chunk: str):
        """接收新的文本块"""
        self.buffer += chunk
        if self.state == "OUTSIDE":
            await self._handle_outside()
        elif self.state == "CONTENT_STREAMING":
            await self._handle_content_streaming()

    async def _handle_outside(self):
        """处理 OUTSIDE 状态"""
        # 查找开始标签 '<'
        pos = self.buffer.find('<')
        if pos == -1:
            return  # 等待更多内容
        # 输出标签前的纯文本内容（如果有）
        if pos > 0:
            self.buffer = self.buffer[pos:]
            return
        # 检查是否是标签开始
        match = re.match(r'<(\w+)([^>]*?)>', self.buffer)
        if match:
            tag_name = match.group(1)
            attr_str = match.group(2)
            self.current_tag = tag_name
            # 简化属性解析，直接去掉外层引号
            self.attributes = {}
            if attr_str.strip():
                # 使用正则表达式匹配，然后去掉外层引号
                self.attributes = self._parse_attributes_simple(attr_str)
            # 发送标签开始事件
            await self._send_tag_start()
            # 进入内容流式处理状态
            self.state = "CONTENT_STREAMING"
            self.buffer = self.buffer[match.end():]

    async def _handle_content_streaming(self):
        """处理 CONTENT_STREAMING 状态"""
        # 查找结束标签
        close_tag = f"</{self.current_tag}>"
        end_pos = self.buffer.find(close_tag)
        
        if end_pos != -1:
            # 找到结束标签，发送剩余内容并结束
            content = self.buffer[:end_pos]
            if content:
                await self._send_content_chunk(content)
            
            # 发送标签结束事件
            await self._send_tag_end()
            
            # 重置状态
            self.state = "OUTSIDE"
            self.current_tag = None
            self.attributes = {}
            self.buffer = self.buffer[end_pos + len(close_tag):]
        else:
            # 没找到结束标签，检查部分匹配
            partial_match_len = self._get_partial_match_len(close_tag)
            safe_len = len(self.buffer) - partial_match_len
            
            if safe_len > 0:
                # 有安全内容可以发送
                content = self.buffer[:safe_len]
                await self._send_content_chunk(content)
                self.buffer = self.buffer[safe_len:]
            # 如果没有安全内容，等待更多输入

    def _get_partial_match_len(self, close_tag: str) -> int:
        """计算 buffer 末尾与 close_tag 开头的最大匹配长度"""
        import re
        
        buffer_len = len(self.buffer)
        tag_len = len(close_tag)
        
        # 最多检查 min(buffer_len, tag_len) 个字符
        max_check = min(buffer_len, tag_len)
        
        # 构建正则表达式：检查buffer末尾是否与close_tag开头匹配
        # 使用正向前瞻断言 (?=...) 来匹配buffer末尾
        pattern = f"({re.escape(close_tag[:max_check])})$"
        match = re.search(pattern, self.buffer)
        
        if match:
            # 找到匹配，返回匹配长度
            return len(match.group(1))
        
        # 如果没有完全匹配，尝试部分匹配
        for i in range(max_check, 0, -1):
            pattern = f"({re.escape(close_tag[:i])})$"
            if re.search(pattern, self.buffer):
                return i
        
        return 0

    def _parse_attributes_simple(self, attr_str: str) -> dict:
        """
        简化属性解析，直接去掉外层引号
        
        Args:
            attr_str: 属性字符串，如 'name=value params="上海当前天气 2025年8月12日"'
            
        Returns:
            dict: 解析后的属性字典
        """
        attributes = {}
        
        # 匹配两种格式：
        # 1. name=value（值以空格结束，如：mood=happy level=3）
        # 2. name="value" 或 name='value'（值可以包含空格，如：params="上海当前天气 2025年8月12日"）
        pattern = r'(\w+)=(?:([^\s]+)|([\'"])(.*?)\3)'
        matches = re.findall(pattern, attr_str)
        
        for match in matches:
            key = match[0]
            # 如果第二个组有值（无引号），使用它；否则使用第四个组（有引号）
            value = match[1] if match[1] else match[3]
            attributes[key] = value.strip()
        return attributes

    async def _send_tag_start(self):
        """发送标签开始事件"""
        if not self.tag_callback:
            return
        await self.tag_callback({
            "tag": self.current_tag,
            "status": "start",
            "attributes": self.attributes
        })

    async def _send_content_chunk(self, content: str):
        """发送内容块"""
        if not self.tag_callback or not content:
            return
        await self.tag_callback({
            "tag": self.current_tag,
            "status": "streaming",
            "content": content
        })

    async def _send_tag_end(self):
        """发送标签结束事件"""
        if not self.tag_callback:
            return
        await self.tag_callback({
            "tag": self.current_tag,
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
                    await self.websocket_send_callback({
                        "event": ServerEvent.ChatResponse,
                        "payload_msg": {
                            "content": payload["content"]
                        }
                    })
            elif payload["status"] == "end":
                pass
        elif payload["tag"] == "env_desc":
            if payload["status"] == "start":
                pass
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
                pass
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
        elif payload["tag"] == "emotion":
            if payload["status"] == "start":
                pass
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
    
    async def start(self, chat_id: str, user_id: str, session_prompt: str = ""):
        self.chat_id = chat_id
        self.user_id = user_id
        self.session_prompt = session_prompt
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
            chat_model = get_chat_model_by_type("pfc_chat")
            messages = []
            for prompt in prompts:
                logger.bind(tag="TASK").info(f"prompt: {prompt}")
                if prompt["role"] == "user":
                    messages.append(HumanMessage(content=prompt["content"]))
                elif prompt["role"] == "assistant":
                    messages.append(AIMessage(content=prompt["content"]))
                else:
                    messages.append(SystemMessage(content=prompt["content"]))
            # 生成立即回复
            final_response = ""
            first_chunk = True
            logger.bind(tag="DELAY").info(f"start llm response delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
            async for chunk in chat_model.astream(messages, extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    if self.is_interruption:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    final_response += chunk.content
                    if first_chunk:
                        first_chunk = False
                        logger.bind(tag="TTS").info(f"start streaming response delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
                    await self.parser.feed(chunk.content)
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
