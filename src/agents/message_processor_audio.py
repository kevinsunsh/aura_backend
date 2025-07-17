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

# SESSION_TYPES = [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]
# SESSION_TYPES = [DialogSessionType.E2E_SESSION]
SESSION_TYPES = [DialogSessionType.ALT_SESSION]

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
                 asr_start_callback: Callable[[], None],
                 asr_response_callback: Callable[[str, bool], None],
                 asr_end_callback: Callable[[str], None],
                 tts_start_callback: Callable[[str], None],
                 tts_response_callback: Callable[[bytes], None],
                 tts_end_callback: Callable[[], None],
                 chat_response_callback: Callable[[str], None],
                 chat_end_callback: Callable[[str], None]):
        self.chat_id = chat_id
        self.user_id = user_id
        self.dialog_session = DialogSession(
            uid=self.user_id,
            asr_start_callback=asr_start_callback,
            asr_response_callback=asr_response_callback,
            asr_end_callback=asr_end_callback,
            tts_start_callback=tts_start_callback,
            tts_response_callback=tts_response_callback,
            tts_end_callback=tts_end_callback,
            chat_response_callback=chat_response_callback,
            chat_end_callback=chat_end_callback
        )
    
    async def start(self) -> None:
        await self.dialog_session.start()
    
    async def cleanup(self) -> None:
        await self.dialog_session.cleanup()
    
    async def process_audio_input(self, audio_chunk: bytes) -> None:
        await self.dialog_session.process_audio_chunk(audio_chunk)
    
    async def process_text_input(self, text: str) -> None:
        pass
    
    def is_connected(self) -> bool:
        return self.dialog_session.is_connected()

class ALTSessionClient(IDialogSession):
    """集联语音对话客户端包装器"""
    
    def __init__(self,
                 chat_id: str,
                 user_id: str,
                 asr_start_callback: Callable[[], None],
                 asr_response_callback: Callable[[str, bool], None],
                 asr_end_callback: Callable[[str], None],
                 tts_start_callback: Callable[[str], None],
                 tts_response_callback: Callable[[bytes], None],
                 tts_end_callback: Callable[[], None],
                 chat_response_callback: Callable[[str], None],
                 chat_end_callback: Callable[[str], None]):
        self.chat_id = chat_id
        self.user_id = user_id
        
        # 存储回调函数
        self._asr_start_callback = asr_start_callback
        self._asr_response_callback = asr_response_callback
        self._asr_end_callback = asr_end_callback
        self._tts_start_callback = tts_start_callback
        self._tts_response_callback = tts_response_callback
        self._tts_end_callback = tts_end_callback
        self._chat_response_callback = chat_response_callback
        self._chat_end_callback = chat_end_callback
        
        # 创建ASR客户端
        # self.asr_client = AsrClient(
        #     uid=uid,
        #     asr_start_callback=self._asr_start_callback,
        #     asr_response_callback=self._asr_response_callback,
        #     asr_end_callback=self._asr_end_callback
        # )
        # 创建ASR客户端
        self.asr_client = AuraDialogSession(
            uid=self.user_id,
            asr_start_callback=self.asr_start_wrapper,
            asr_response_callback=self._asr_response_callback,
            asr_end_callback=self._asr_end_callback
        )
        # 创建文本处理器
        self.text_processor = MessageProcessorText(
            chat_id=self.chat_id,
            user_id=self.user_id,
            websocket_send_callback=self._text_processor_callback
        )
        # 创建TTS客户端
        self.tts_client = TtsClient(
            uid=self.user_id,
            tts_start_callback=self._tts_start_callback,
            tts_response_callback=self._tts_response_callback,
            tts_end_callback=self._tts_end_callback
        )
        self.is_chat_start = True
    
    async def asr_start_wrapper(self) -> None:
        await self.text_processor.user_input_interruption()
        await safe_call(self._asr_start_callback)
    
    async def asr_end_wrapper(self, asr_text: str) -> None:
        await self.text_processor.handle_text_message({"message": asr_text})
        await safe_call(self._asr_end_callback, asr_text)

    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应并发送到TTS"""
        # 如果是聊天响应，发送到TTS
        if message.get("event") == ServerEvent.ChatResponse:
            chunk_content = message.get("payload_msg", {}).get("content", "")
            if chunk_content and self.audio_client and self.audio_client.is_connected():
                try:
                    if self.is_chat_start:
                        self.is_chat_start = False
                        await self.tts_client.send_text_chunk(chunk_content, start=True, end=False)
                    else:
                        await self.tts_client.send_text_chunk(chunk_content)
                    logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
                except Exception as e:
                    logger.error(f"发送TTS文本片段失败: {e}")
            await safe_call(self._chat_response_callback, chunk_content)
        elif message.get("event") == ServerEvent.ChatEnded:
            # 结束TTS合成
            if self.is_connected():
                try:
                    self.is_chat_start = True
                    await self.tts_client.send_text_chunk("", start=False, end=True)
                    logger.debug("ChatEnded流式结束")
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
            await safe_call(self._chat_end_callback, "")

    async def start(self) -> None:
        await self.asr_client.start()
        await self.text_processor.start()
        await self.tts_client.start()
    
    async def cleanup(self) -> None:
        await self.asr_client.cleanup()
        await self.text_processor.cleanup()
        await self.tts_client.cleanup()
    
    async def process_audio_input(self, audio_chunk: bytes) -> None:
        await self.asr_client.process_audio_chunk(audio_chunk)
    
    async def process_text_input(self, text: str) -> None:
        await self.tts_client.send_text_chunk(text)
    
    def is_connected(self) -> bool:
        return self.asr_client.is_connected() and self.tts_client.is_connected()

class DialogSessionFactory:
    """对话会话工厂"""
    @staticmethod
    def create_client(client_type: DialogSessionType,
                     chat_id: str,
                     user_id: str,
                     asr_start_callback: Callable[[], None],
                     asr_response_callback: Callable[[str, bool], None],
                     asr_end_callback: Callable[[str], None],
                     tts_start_callback: Callable[[str], None],
                     tts_response_callback: Callable[[bytes], None],
                     tts_end_callback: Callable[[], None],
                     chat_response_callback: Callable[[str], None],
                     chat_end_callback: Callable[[str], None]) -> IDialogSession:
        """创建对话会话"""
        if client_type == DialogSessionType.E2E_SESSION:
            return E2ESessionClient(
                chat_id=chat_id,
                user_id=user_id,
                asr_start_callback=asr_start_callback,
                asr_response_callback=asr_response_callback,
                asr_end_callback=asr_end_callback,
                tts_start_callback=tts_start_callback,
                tts_response_callback=tts_response_callback,
                tts_end_callback=tts_end_callback,
                chat_response_callback=chat_response_callback,
                chat_end_callback=chat_end_callback
            )
        elif client_type == DialogSessionType.ALT_SESSION:
            return ALTSessionClient(
                chat_id=chat_id,
                user_id=user_id,
                asr_start_callback=asr_start_callback,
                asr_response_callback=asr_response_callback,
                asr_end_callback=asr_end_callback,
                tts_start_callback=tts_start_callback,
                tts_response_callback=tts_response_callback,
                tts_end_callback=tts_end_callback,
                chat_response_callback=chat_response_callback,
                chat_end_callback=chat_end_callback
            )
        else:
            raise ValueError(f"不支持的客户端类型: {client_type}")

def client_process(client_type, input_queue, output_queue, chat_id, user_id):
    asyncio.run(client_main(client_type, input_queue, output_queue, chat_id, user_id))

async def client_main(client_type, input_queue, output_queue, chat_id, user_id):
    # ALTSession 进程内详细实现
    if client_type == DialogSessionType.ALT_SESSION:
        # 状态变量
        is_chat_start = True
        is_in_asr = False
        is_in_chat = False
        is_in_tts = False
        # 回调适配
        async def asr_start_callback():
            nonlocal is_in_asr
            is_in_asr = True
            await text_processor.user_input_interruption()
            output_queue.put({"event": ServerEvent.ASRInfo})
        async def asr_response_callback(asr_text, is_interim):
            output_queue.put({
                "event": ServerEvent.ASRResponse,
                "payload_msg": {"results": [{"text": asr_text, "is_interim": is_interim}]}
            })
        async def asr_end_callback(asr_text):
            nonlocal is_in_asr
            is_in_asr = False
            await text_processor.handle_text_message({"message": asr_text})
            output_queue.put({"event": ServerEvent.ASREnded})
        async def tts_start_callback(text):
            nonlocal is_in_tts
            is_in_tts = True
            if is_in_asr:
                logger.info(f"在发消息处打断流式响应，继续倾听")
                return
            output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
        async def tts_response_callback(audio_data):
            if is_in_asr:
                logger.info(f"在发消息处打断流式响应，继续倾听")
                return
            output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": {"audio_data": audio_data}})
        async def tts_end_callback():
            nonlocal is_in_tts
            is_in_tts = False
            if is_in_asr:
                logger.info(f"在发消息处打断流式响应，继续倾听")
                return
            output_queue.put({"event": ServerEvent.TTSSentenceEnd})
        async def chat_response_callback(text):
            nonlocal is_in_chat
            is_in_chat = True
            if is_in_asr:
                logger.info(f"在发消息处打断流式响应，继续倾听")
                return
            output_queue.put({"event": ServerEvent.ChatResponse, "payload_msg": {"content": text}})
        async def chat_end_callback(text):
            nonlocal is_in_chat
            is_in_chat = False
            if is_in_asr:
                logger.info(f"在发消息处打断流式响应，继续倾听")
                return
            output_queue.put({"event": ServerEvent.ChatEnded, "payload_msg": {"content": text}})
        # 文本处理器回调
        async def text_processor_callback(message: Dict[str, Any]):
            nonlocal is_chat_start
            if message.get("event") == ServerEvent.ChatResponse:
                chunk_content = message.get("payload_msg", {}).get("content", "")
                if chunk_content:
                    try:
                        if is_chat_start:
                            is_chat_start = False
                            await tts_client.send_text_chunk(chunk_content, start=True, end=False)
                        else:
                            await tts_client.send_text_chunk(chunk_content)
                    except Exception as e:
                        logger.error(f"发送TTS文本片段失败: {e}")
                await chat_response_callback(chunk_content)
            elif message.get("event") == ServerEvent.ChatEnded:
                try:
                    is_chat_start = True
                    await tts_client.send_text_chunk("", start=False, end=True)
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
                await chat_end_callback("")
        # 组件初始化
        asr_client = AuraDialogSession(
            uid=user_id,
            asr_start_callback=asr_start_callback,
            asr_response_callback=asr_response_callback,
            asr_end_callback=asr_end_callback
        )
        text_processor = MessageProcessorText(
            chat_id=chat_id,
            user_id=user_id,
            websocket_send_callback=text_processor_callback
        )
        tts_client = TtsClient(
            uid=user_id,
            tts_start_callback=tts_start_callback,
            tts_response_callback=tts_response_callback,
            tts_end_callback=tts_end_callback
        )
        # 启动
        await asr_client.start()
        await text_processor.start()
        await tts_client.start()
        # 主循环
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "stop":
                break
            elif isinstance(msg, dict) and msg.get("type") == "audio":
                await asr_client.process_audio_chunk(msg["data"])
            elif isinstance(msg, dict) and msg.get("type") == "text":
                await tts_client.send_text_chunk(msg["data"])
        # 清理
        await asr_client.cleanup()
        await text_processor.cleanup()
        await tts_client.cleanup()
    # E2E_SESSION 逻辑保持不变
    elif client_type == DialogSessionType.E2E_SESSION:
        def asr_start_callback():
            output_queue.put({"event": ServerEvent.ASRInfo})
        def asr_response_callback(asr_text, is_interim):
            output_queue.put({
                "event": ServerEvent.ASRResponse,
                "payload_msg": {"results": [{"text": asr_text, "is_interim": is_interim}]}
            })
        def asr_end_callback(asr_text):
            output_queue.put({"event": ServerEvent.ASREnded})
        def tts_start_callback(text):
            output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
        def tts_response_callback(audio_data):
            output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": {"audio_data": audio_data}})
        def tts_end_callback():
            output_queue.put({"event": ServerEvent.TTSSentenceEnd})
        def chat_response_callback(text):
            output_queue.put({"event": ServerEvent.ChatResponse, "payload_msg": {"content": text}})
        def chat_end_callback(text):
            output_queue.put({"event": ServerEvent.ChatEnded, "payload_msg": {"content": text}})
        client = DialogSession(
            uid=user_id,
            asr_start_callback=asr_start_callback,
            asr_response_callback=asr_response_callback,
            asr_end_callback=asr_end_callback,
            tts_start_callback=tts_start_callback,
            tts_response_callback=tts_response_callback,
            tts_end_callback=tts_end_callback,
            chat_response_callback=chat_response_callback,
            chat_end_callback=chat_end_callback
        )
        await client.start()
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "stop":
                break
            elif isinstance(msg, dict) and msg.get("type") == "audio":
                await client.process_audio_chunk(msg["data"])
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
        self.input_queues = {
            DialogSessionType.E2E_SESSION: multiprocessing.Queue(),
            DialogSessionType.ALT_SESSION: multiprocessing.Queue()
        }
        self.output_queues = {
            DialogSessionType.E2E_SESSION: multiprocessing.Queue(),
            DialogSessionType.ALT_SESSION: multiprocessing.Queue()
        }
        self.processes = {}
        self.send_message_task = None
        self.active_client = DialogSessionType.ALT_SESSION
    
    def send_to_client(self, client_type, msg):
        self.input_queues[client_type].put(msg)
    
    async def handle_message(self, message_data: Dict[str, Any]):
        """
        分发消息到两个 client 进程
        """
        if "payload_msg" in message_data and message_data["payload_msg"]:
            payload_msg = message_data["payload_msg"]
            if message_data.get("event") == ClientEvent.SayHello:
                for t in SESSION_TYPES:
                    self.send_to_client(t, {"type": "text", "data": payload_msg.get("content", "")})
            elif message_data.get("event") == ClientEvent.TaskRequest:
                for t in SESSION_TYPES:
                    self.send_to_client(t, {"type": "audio", "data": payload_msg})
        return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}

    async def send_message(self):
        """
        轮询两个 client 的输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                # msg = await loop.run_in_executor(None, self.output_queues[DialogSessionType.E2E_SESSION].get)
                # if msg.get("event") in [ServerEvent.ASRInfo, ServerEvent.ASRResponse, ServerEvent.ASREnded] or self.active_client == DialogSessionType.E2E_SESSION:
                #     if self.websocket_send_callback:
                #         await self.websocket_send_callback(msg)
                #     continue
                msg = await loop.run_in_executor(None, self.output_queues[self.active_client].get)
                logger.debug(f"收到消息: {msg}")
                if self.websocket_send_callback:
                    await self.websocket_send_callback(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
    
    async def start(self):
        for t in SESSION_TYPES:
            p = multiprocessing.Process(
                target=client_process,
                args=(t, self.input_queues[t], self.output_queues[t], self.chat_id, self.user_id)
            )
            p.start()
            self.processes[t] = p
        self.send_message_task = asyncio.create_task(self.send_message())

    async def cleanup(self):
        for t in self.processes:
            self.input_queues[t].put({"type": "stop"})
            self.processes[t].join()
