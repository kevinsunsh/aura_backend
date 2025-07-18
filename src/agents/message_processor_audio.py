import multiprocessing
import asyncio
import logging
import uuid
import base64
import json
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

from .doubao_client.dialog_session import DialogSession
from .aura_client.aura_dialog_session import AuraDialogSession
# from .doubao_client.asr_client import AsrClient
from .doubao_client.asr_client_new import AsrClient
from .doubao_client.tts_client import TtsClient
from .message_processor_text import MessageProcessorText
from utils.utils import start_performance_point, end_performance_point, safe_call
from muttering_data.mutter_index import get_muttering_file_path, MutteringType
from api_protocol.constant import *
from agents.aura_memory.message_store import MessageStore, Message
from agents.prompts.check_response_prompt import CHECK_RESPONSE_PROMPT
from configuration.config import get_chat_model_by_type
from langchain_core.messages import SystemMessage
from .task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)

class DialogSessionType(Enum):
    """音频客户端类型枚举"""
    E2E_SESSION = "e2e_session"  # 端到端语音对话
    ALT_SESSION = "alt_session"  # 集联语音对话

SESSION_TYPES = [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]
# SESSION_TYPES = [DialogSessionType.E2E_SESSION]
# SESSION_TYPES = [DialogSessionType.ALT_SESSION]

class IDialogSession(ABC):
    """对话会话抽象接口"""
    
    @abstractmethod
    async def start(self) -> None:
        """启动客户端"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源"""
        pass
    
    @abstractmethod
    async def process_audio_input(self, audio_chunk: bytes) -> None:
        """处理音频块"""
        pass
    
    @abstractmethod
    async def process_text_input(self, text: str) -> None:
        """处理文本块"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass

class E2ESessionClient(IDialogSession):
    """端到端语音对话客户端包装器"""
    
    def __init__(self, 
                 chat_id: str,
                 user_id: str,
                 asr_output_queue,
                 llm_output_queue,
                 e2e_output_queue):
        self.chat_id = chat_id
        self.user_id = user_id
        self.asr_output_queue = asr_output_queue
        self.llm_output_queue = llm_output_queue
        self.e2e_output_queue = e2e_output_queue

        self.dialog_session = DialogSession(
            uid=self.user_id,
            asr_start_callback=self._on_asr_info,
            asr_response_callback=self._on_asr_response,
            asr_end_callback=self._on_asr_ended,
            tts_sentence_start_callback=self._e2e_on_tts_sentence_start,
            tts_response_callback=self._e2e_on_tts_response,
            tts_sentence_end_callback=self._e2e_on_tts_sentence_end,
            tts_ended_callback=self._e2e_on_tts_ended,
            chat_response_callback=self._e2e_on_chat_response,
            chat_end_callback=self._e2e_on_chat_ended
        )
        self.server_asr_result = ""
        # 创建文本处理器
        self.text_processor = MessageProcessorText(
            chat_id=self.chat_id,
            user_id=self.user_id,
            websocket_send_callback=self._text_processor_callback
        )
        # 创建TTS客户端
        self.tts_client = TtsClient(
            uid=self.user_id,
            tts_sentence_start_callback=self._llm_on_tts_sentence_start,
            tts_response_callback=self._llm_on_tts_response,
            tts_sentence_end_callback=self._llm_on_tts_sentence_end,
            tts_ended_callback=self._llm_on_tts_ended
        )
        self.is_chat_start = True
        self.is_llm_tts_running = False
        self.recv_message_tasks = None
    
    # TTS类事件回调方法
    async def _e2e_on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.info(f"E2E TTS句子开始: {text}")
        self.e2e_output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
    
    async def _e2e_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.info("E2E TTS句子结束")
        self.e2e_output_queue.put({"event": ServerEvent.TTSSentenceEnd})

    async def _e2e_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        self.e2e_output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload})
    
    async def _e2e_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.info("E2E TTS合成结束")
        self.e2e_output_queue.put({"event": ServerEvent.TTSEnded})
    
    # TTS类事件回调方法
    async def _llm_on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.info(f"LLM TTS句子开始: {text}")
        self.is_llm_tts_running = True
        self.llm_output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
    
    async def _llm_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.info("LLM TTS句子结束")
        self.llm_output_queue.put({"event": ServerEvent.TTSSentenceEnd})
    
    async def _llm_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        self.llm_output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload})
    
    async def _llm_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.info("LLM TTS合成结束")
        self.is_llm_tts_running = False
        self.llm_output_queue.put({"event": ServerEvent.TTSEnded})
    
    # ASR类事件回调方法
    async def _on_asr_info(self) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.info("ASR识别出首字")
        await self.text_processor.user_input_interruption()
        self.asr_output_queue.put({"event": ServerEvent.ASRInfo})
    
    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        results = payload.get("results", [])
        if results:
            for result in results:
                text = result.get("text", "")
                is_interim = result.get("is_interim", False)
                logger.debug(f"ASR识别结果: {text} (临时: {is_interim})")
                self.server_asr_result = text
                self.asr_output_queue.put({
                    "event": ServerEvent.ASRResponse,
                    "payload_msg": {"results": [{"text": text, "is_interim": is_interim}]}
                })
    
    async def _on_asr_ended(self) -> None:
        """ASR结束事件回调"""
        logger.info(f"ASR识别结束 : {self.server_asr_result}")
        await self.text_processor.handle_text_message({"message": self.server_asr_result})
        self.asr_output_queue.put({"event": ServerEvent.ASREnded})
    
    # Chat类事件回调方法
    async def _e2e_on_chat_response(self, payload: Dict[str, Any]) -> None:
        """聊天响应事件回调"""
        content = payload.get("content", "")
        logger.info(f"E2E收到聊天响应: {content[:10]}...")
        self.e2e_output_queue.put({"event": ServerEvent.ChatResponse, "payload_msg": {"content": content}})
    
    async def _e2e_on_chat_ended(self) -> None:
        """聊天结束事件回调"""
        logger.info("E2E聊天响应结束")
        self.e2e_output_queue.put({"event": ServerEvent.ChatEnded})
        
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应并发送到TTS"""
        # 如果是聊天响应，发送到TTS
        if message.get("event") == ServerEvent.ChatResponse:
            chunk_content = message.get("payload_msg", {}).get("content", "")
            if chunk_content and self.tts_client and self.tts_client.is_connected():
                try:
                    if self.is_chat_start:
                        self.is_chat_start = False
                        await self.tts_client.send_text_chunk(chunk_content, start=True, end=False)
                    else:
                        await self.tts_client.send_text_chunk(chunk_content)
                    logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
                except Exception as e:
                    logger.error(f"发送TTS文本片段失败: {e}")
        elif message.get("event") == ServerEvent.ChatEnded:
            # 结束TTS合成
            if self.tts_client.is_connected():
                try:
                    self.is_chat_start = True
                    await self.tts_client.send_text_chunk("", start=False, end=True)
                    logger.debug("ChatEnded流式结束")
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
        self.llm_output_queue.put(message)
    
    async def start(self) -> None:
        await self.dialog_session.start()
        await self.text_processor.start()
        await self.tts_client.start()
        self.recv_message_tasks = asyncio.gather(
            self.dialog_session.message_receive_loop(),
            self.tts_client.message_receive_loop()
        )
    
    async def cleanup(self) -> None:
        await self.dialog_session.cleanup()
        await self.text_processor.cleanup()
        await self.tts_client.cleanup()
        # 取消所有消息处理任务
        if hasattr(self, 'recv_message_tasks'):
            self.recv_message_tasks.cancel()
            try:
                await self.recv_message_tasks
            except asyncio.CancelledError:
                pass
        logger.info("E2ESessionClient清理完成")
    
    async def process_audio_input(self, audio_chunk: bytes) -> None:
        await self.dialog_session.process_audio_chunk(audio_chunk)
    
    async def process_text_input(self, text: str) -> None:
        pass
    
    def is_connected(self) -> bool:
        return self.dialog_session.is_connected() and self.tts_client.is_connected()

# class ALTSessionClient(IDialogSession):
#     """集联语音对话客户端包装器"""
    
#     def __init__(self,
#                  chat_id: str,
#                  user_id: str,
#                  asr_start_callback: Callable[[], None],
#                  asr_response_callback: Callable[[str, bool], None],
#                  asr_end_callback: Callable[[str], None],
#                  tts_start_callback: Callable[[str], None],
#                  tts_response_callback: Callable[[bytes], None],
#                  tts_end_callback: Callable[[], None],
#                  chat_response_callback: Callable[[str], None],
#                  chat_end_callback: Callable[[str], None]):
#         self.chat_id = chat_id
#         self.user_id = user_id
        
#         # 存储回调函数
#         self._asr_start_callback = asr_start_callback
#         self._asr_response_callback = asr_response_callback
#         self._asr_end_callback = asr_end_callback
#         self._tts_start_callback = tts_start_callback
#         self._tts_response_callback = tts_response_callback
#         self._tts_end_callback = tts_end_callback
#         self._chat_response_callback = chat_response_callback
#         self._chat_end_callback = chat_end_callback
        
#         # 创建ASR客户端
#         # self.asr_client = AsrClient(
#         #     uid=uid,
#         #     asr_start_callback=self._asr_start_callback,
#         #     asr_response_callback=self._asr_response_callback,
#         #     asr_end_callback=self._asr_end_callback
#         # )
#         # 创建ASR客户端
#         self.asr_client = AuraDialogSession(
#             uid=self.user_id,
#             asr_start_callback=self.asr_start_wrapper,
#             asr_response_callback=self._asr_response_callback,
#             asr_end_callback=self._asr_end_callback
#         )
#         # 创建文本处理器
#         self.text_processor = MessageProcessorText(
#             chat_id=self.chat_id,
#             user_id=self.user_id,
#             websocket_send_callback=self._text_processor_callback
#         )
#         # 创建TTS客户端
#         self.tts_client = TtsClient(
#             uid=self.user_id,
#             tts_start_callback=self._tts_start_callback,
#             tts_response_callback=self._tts_response_callback,
#             tts_end_callback=self._tts_end_callback
#         )
#         self.is_chat_start = True
    
#     async def asr_start_wrapper(self) -> None:
#         await self.text_processor.user_input_interruption()
#         await safe_call(self._asr_start_callback)
    
#     async def asr_end_wrapper(self, asr_text: str) -> None:
#         await self.text_processor.handle_text_message({"message": asr_text})
#         await safe_call(self._asr_end_callback, asr_text)

#     async def _text_processor_callback(self, message: Dict[str, Any]):
#         """文本处理器回调，用于处理聊天响应并发送到TTS"""
#         # 如果是聊天响应，发送到TTS
#         if message.get("event") == ServerEvent.ChatResponse:
#             chunk_content = message.get("payload_msg", {}).get("content", "")
#             if chunk_content and self.audio_client and self.audio_client.is_connected():
#                 try:
#                     if self.is_chat_start:
#                         self.is_chat_start = False
#                         await self.tts_client.send_text_chunk(chunk_content, start=True, end=False)
#                     else:
#                         await self.tts_client.send_text_chunk(chunk_content)
#                     logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
#                 except Exception as e:
#                     logger.error(f"发送TTS文本片段失败: {e}")
#             await safe_call(self._chat_response_callback, {"llm_response": chunk_content})
#         elif message.get("event") == ServerEvent.ChatEnded:
#             # 结束TTS合成
#             if self.is_connected():
#                 try:
#                     self.is_chat_start = True
#                     await self.tts_client.send_text_chunk("", start=False, end=True)
#                     logger.debug("ChatEnded流式结束")
#                 except Exception as e:
#                     logger.error(f"结束TTS合成失败: {e}")
#             await safe_call(self._chat_end_callback, "")

#     async def start(self) -> None:
#         await self.asr_client.start()
#         await self.text_processor.start()
#         await self.tts_client.start()
    
#     async def cleanup(self) -> None:
#         await self.asr_client.cleanup()
#         await self.text_processor.cleanup()
#         await self.tts_client.cleanup()
    
#     async def process_audio_input(self, audio_chunk: bytes) -> None:
#         await self.asr_client.process_audio_chunk(audio_chunk)
    
#     async def process_text_input(self, text: str) -> None:
#         await self.tts_client.send_text_chunk(text)
    
#     def is_connected(self) -> bool:
#         return self.asr_client.is_connected() and self.tts_client.is_connected()

# class DialogSessionFactory:
#     """对话会话工厂"""
#     @staticmethod
#     def create_client(client_type: DialogSessionType,
#                      chat_id: str,
#                      user_id: str,
#                      asr_start_callback: Callable[[], None],
#                      asr_response_callback: Callable[[str, bool], None],
#                      asr_end_callback: Callable[[str], None],
#                      tts_start_callback: Callable[[str], None],
#                      tts_response_callback: Callable[[bytes], None],
#                      tts_end_callback: Callable[[], None],
#                      chat_response_callback: Callable[[str], None],
#                      chat_end_callback: Callable[[str], None]) -> IDialogSession:
#         """创建对话会话"""
#         if client_type == DialogSessionType.E2E_SESSION:
#             return E2ESessionClient(
#                 chat_id=chat_id,
#                 user_id=user_id,
#                 asr_start_callback=asr_start_callback,
#                 asr_response_callback=asr_response_callback,
#                 asr_end_callback=asr_end_callback,
#                 tts_start_callback=tts_start_callback,
#                 tts_response_callback=tts_response_callback,
#                 tts_end_callback=tts_end_callback,
#                 chat_response_callback=chat_response_callback,
#                 chat_end_callback=chat_end_callback
#             )
#         elif client_type == DialogSessionType.ALT_SESSION:
#             return ALTSessionClient(
#                 chat_id=chat_id,
#                 user_id=user_id,
#                 asr_start_callback=asr_start_callback,
#                 asr_response_callback=asr_response_callback,
#                 asr_end_callback=asr_end_callback,
#                 tts_start_callback=tts_start_callback,
#                 tts_response_callback=tts_response_callback,
#                 tts_end_callback=tts_end_callback,
#                 chat_response_callback=chat_response_callback,
#                 chat_end_callback=chat_end_callback
#             )
#         else:
#             raise ValueError(f"不支持的客户端类型: {client_type}")

def e2e_process(input_queue, asr_output_queue, llm_output_queue, e2e_output_queue, chat_id, user_id):
    asyncio.run(e2e_main(input_queue, asr_output_queue, llm_output_queue, e2e_output_queue, chat_id, user_id))

async def e2e_main(input_queue, asr_output_queue, llm_output_queue, e2e_output_queue, chat_id, user_id):
    # E2E_SESSION 逻辑保持不变
    client = E2ESessionClient(
        user_id=user_id,
        chat_id=chat_id,
        asr_output_queue=asr_output_queue,
        llm_output_queue=llm_output_queue,
        e2e_output_queue=e2e_output_queue
    )
    await client.start()
    loop = asyncio.get_event_loop()
    while True:
        msg = await loop.run_in_executor(None, input_queue.get)
        if isinstance(msg, dict) and msg.get("type") == "stop":
            break
        elif isinstance(msg, dict) and msg.get("type") == "audio":
            await client.process_audio_input(msg["data"])
        elif isinstance(msg, dict) and msg.get("type") == "text":
            pass
    await client.cleanup()

class MessageProcessorAudio:
    """
    多进程版音频消息处理器
    """
    def __init__(self, chat_id: str, user_id: str, websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = chat_id
        self.user_id = user_id
        self.websocket_send_callback = websocket_send_callback
        self.input_queues = multiprocessing.Queue()
        self.asr_output_queue = multiprocessing.Queue()
        self.llm_output_queue = multiprocessing.Queue()
        self.e2e_output_queue = multiprocessing.Queue()
        self.process = None
        self.send_message_task = None
        self.send_asr_message_task = None
        self.active_client = None
    
    async def handle_message(self, message_data: Dict[str, Any]):
        """
        分发消息到两个 client 进程
        """
        if "payload_msg" in message_data and message_data["payload_msg"]:
            payload_msg = message_data["payload_msg"]
            if message_data.get("event") == ClientEvent.SayHello:
                self.input_queues.put({"type": "text", "data": payload_msg.get("content", "")})
            elif message_data.get("event") == ClientEvent.TaskRequest:
                self.input_queues.put({"type": "audio", "data": payload_msg})
        return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}

    async def send_asr_message(self):
        """
        轮询ASR输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.asr_output_queue.get)
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送ASR消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("ASR消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"ASR消息处理任务异常: {e}")
            raise  # 重新抛出异常

    async def send_message(self):
        """
        轮询LLM输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.llm_output_queue.get),
                    logger.debug(f"收到LLM消息: {msg}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送LLM消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("LLM消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"LLM消息处理任务异常: {e}")
            raise  # 重新抛出异常

    # async def send_e2e_message(self):
    #     """
    #     轮询E2E输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         loop = asyncio.get_event_loop()
    #         while True:
    #             msg = await loop.run_in_executor(None, self.e2e_output_queue.get)
    #             logger.debug(f"收到E2E消息: {msg}")
    #             if self.websocket_send_callback:
    #                 await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         pass
    #     except Exception as e:
    #         logger.error(f"发送E2E消息失败: {e}")
    
    async def start(self):
        logger.info(f"开始启动MessageProcessorAudio: chat_id={self.chat_id}")
        
        # 确保之前的任务已经清理
        if hasattr(self, 'message_tasks'):
            try:
                self.message_tasks.cancel()
                await self.message_tasks
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"清理之前的任务时出错: {e}")
        
        # 启动消息处理任务
        logger.info("启动消息处理任务")
        self.message_tasks = asyncio.gather(
            self.send_asr_message(),
            self.send_message()
        )
        
        # 启动子进程
        logger.info("启动子进程")
        self.process = multiprocessing.Process(
            target=e2e_process,
            args=(self.input_queues, self.asr_output_queue, self.llm_output_queue, self.e2e_output_queue, self.chat_id, self.user_id)
        )
        self.process.start()
        
        logger.info(f"MessageProcessorAudio启动完成: chat_id={self.chat_id}")
    
    async def cleanup(self):
        logger.info(f"开始清理MessageProcessorAudio: chat_id={self.chat_id}")
        
        # 取消所有消息处理任务
        if hasattr(self, 'message_tasks'):
            self.message_tasks.cancel()
            try:
                await self.message_tasks
            except asyncio.CancelledError:
                pass
        logger.info("消息处理任务已取消")
        
        # 直接杀死子进程
        if self.process and self.process.is_alive():
            logger.info("直接杀死子进程")
            self.process.kill()
        elif self.process:
            logger.info("子进程已经结束")
        else:
            logger.info("没有子进程需要清理")
        
        # 清理队列
        try:
            logger.info("清理队列...")
            # 先清空队列内容
            while not self.asr_output_queue.empty():
                try:
                    self.asr_output_queue.get_nowait()
                except:
                    break
            while not self.llm_output_queue.empty():
                try:
                    self.llm_output_queue.get_nowait()
                except:
                    break
            while not self.e2e_output_queue.empty():
                try:
                    self.e2e_output_queue.get_nowait()
                except:
                    break
            while not self.input_queues.empty():
                try:
                    self.input_queues.get_nowait()
                except:
                    break
            
            # 关闭队列
            self.asr_output_queue.close()
            self.llm_output_queue.close()
            self.e2e_output_queue.close()
            self.input_queues.close()
            logger.info("队列清理完成")
        except Exception as e:
            logger.error(f"清理队列时出错: {e}")
        
        logger.info("MessageProcessorAudio清理完成")
