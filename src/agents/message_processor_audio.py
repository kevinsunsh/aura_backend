import os
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

logger = logging.getLogger(__name__)

class DialogSessionType(Enum):
    """音频客户端类型枚举"""
    E2E_SESSION = "e2e_session"  # 端到端语音对话
    ALT_SESSION = "alt_session"  # 集联语音对话

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

class MessageProcessorAudio:
    """音频消息处理器，负责处理音频消息并启动ASR相关任务（支持双client并发）"""
    
    def __init__(self, 
                 chat_id: str,
                 user_id: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.websocket_send_callback = websocket_send_callback

        # 支持双client
        self.audio_clients = {DialogSessionType.E2E_SESSION: None, DialogSessionType.ALT_SESSION: None}
        
        self.chat_id = chat_id
        self.user_id = user_id
        
        # 缓存结构
        self.message_cache = {DialogSessionType.E2E_SESSION: asyncio.Queue(), DialogSessionType.ALT_SESSION: asyncio.Queue()}
        self.active_client = None
        self.active_client_lock = asyncio.Lock()
        self.check_response_task = None
        self.send_response_task = None
    
    async def start(self):
        # 创建两个音频客户端
        for type in [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]:
            self.audio_clients[type] = DialogSessionFactory.create_client(
                client_type=type,
                chat_id=self.chat_id,
                user_id=self.user_id,
                asr_start_callback=lambda type=type: self.asr_start_callback(type),
                asr_response_callback=lambda asr_text, is_interim, type=type: self.asr_response_callback(asr_text, is_interim, type),
                asr_end_callback=lambda asr_text, type=type: self.asr_end_callback(asr_text, type),
                tts_start_callback=lambda text, type=type: self.tts_start_callback(text, type),
                tts_response_callback=lambda audio_data, type=type: self.tts_response_callback(audio_data, type),
                tts_end_callback=lambda type=type: self.tts_end_callback(type),
                chat_response_callback=lambda text, type=type: self.chat_response_callback(text, type),
                chat_end_callback=lambda text, type=type: self.chat_end_callback(text, type)
            )
            await self.audio_clients[type].start()
        self.send_response_task = asyncio.create_task(self.send_response())
    
    async def asr_start_callback(self, type: DialogSessionType) -> None:
        if type == DialogSessionType.E2E_SESSION:
            if self.websocket_send_callback:
                await self.websocket_send_callback({"event": ServerEvent.ASRInfo})
    
    async def asr_response_callback(self, asr_text: str, is_interim: bool, type: DialogSessionType) -> None:
        if type == DialogSessionType.E2E_SESSION:
            if self.websocket_send_callback:
                await self.websocket_send_callback({
                    "event": ServerEvent.ASRResponse,
                    "payload_msg": {
                        "results":[{"text": asr_text, "is_interim": is_interim}]
                    }
                })
    
    async def check_response(self, asr_text: str) -> None:
        try:
            # chat_model = get_chat_model_by_type("pfc_action_planner")
            # prompt = CHECK_RESPONSE_PROMPT.format(
            #     user_input=asr_text
            # )
            # response = await chat_model.ainvoke([
            #     SystemMessage(content=prompt)
            # ],
            # extra_body={"thinking": {"type": "disabled"}})
            # if "True" in response.content:
            if True:
                async with self.active_client_lock:
                    self.active_client = DialogSessionType.E2E_SESSION
                # 清空缓存
                while not self.message_cache[DialogSessionType.ALT_SESSION].empty():
                    try:
                        self.message_cache[DialogSessionType.ALT_SESSION].get_nowait()
                    except asyncio.QueueEmpty:
                        break
            else:
                async with self.active_client_lock:
                    self.active_client = DialogSessionType.ALT_SESSION
                # 清空缓存
                while not self.message_cache[DialogSessionType.E2E_SESSION].empty():
                    try:
                        self.message_cache[DialogSessionType.E2E_SESSION].get_nowait()
                    except asyncio.QueueEmpty:
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"检查响应失败: {e}")
    
    async def send_response(self) -> None:
        try:
            while True:
                if self.active_client is not None:
                    if self.websocket_send_callback:
                        message = await self.message_cache[self.active_client].get()
                        await self.websocket_send_callback(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"发送响应失败: {e}")
    
    async def asr_end_callback(self, asr_text: str, type: DialogSessionType) -> None:
        if type == DialogSessionType.E2E_SESSION:
            if self.websocket_send_callback:
                await self.websocket_send_callback({"event": ServerEvent.ASREnded})
        if type == DialogSessionType.ALT_SESSION:
            if self.check_response_task:
                self.check_response_task.cancel()
            self.check_response_task = asyncio.create_task(self.check_response(asr_text))
    
    async def chat_response_callback(self, text: str, type: DialogSessionType) -> None:
        if self.active_client == type or self.active_client is None:
            self.message_cache[type].put_nowait({"event": ServerEvent.ChatResponse, "payload_msg": {"content": text}})
    
    async def chat_end_callback(self, text: str, type: DialogSessionType) -> None:
        if self.active_client == type or self.active_client is None:
            self.message_cache[type].put_nowait({"event": ServerEvent.ChatEnded, "payload_msg": {"content": text}})
    
    async def tts_start_callback(self, text: str, type: DialogSessionType) -> None:
        if self.active_client == type or self.active_client is None:
            self.message_cache[type].put_nowait({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
    
    async def tts_response_callback(self, audio_data: bytes, type: DialogSessionType) -> None:
        if self.active_client == type or self.active_client is None:
            self.message_cache[type].put_nowait({"event": ServerEvent.TTSResponse, "payload_msg": {"audio_data": audio_data}})
    
    async def tts_end_callback(self, type: DialogSessionType) -> None:
        if self.active_client == type or self.active_client is None:
            self.message_cache[type].put_nowait({"event": ServerEvent.TTSSentenceEnd})
    
    async def handle_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
                if message_data.get("event") == ClientEvent.SayHello:
                    if isinstance(payload_msg, dict):
                        text_data = payload_msg.get("content", "")
                        for type in [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]:
                            await self.audio_clients[type].process_text_input(text_data)
                elif message_data.get("event") == ClientEvent.TaskRequest:
                    if isinstance(payload_msg, bytes):
                        for type in [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]:
                            await self.audio_clients[type].process_audio_input(payload_msg)
            return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}
        except Exception as e:
            logger.error(f"启动音频消息处理任务失败: {e}")
            return {"success": False, "error": f"启动音频处理任务失败: {str(e)}"}
    
    async def cleanup(self) -> None:
        for type in [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]:
            if self.audio_clients[type]:
                try:
                    await self.audio_clients[type].cleanup()
                except Exception as e:
                    logger.warning(f"清理音频客户端时出错: {e}")
        self.audio_clients = {DialogSessionType.E2E_SESSION: None, DialogSessionType.ALT_SESSION: None}
        self.message_cache = {DialogSessionType.E2E_SESSION: asyncio.Queue(), DialogSessionType.ALT_SESSION: asyncio.Queue()}
        if self.send_response_task:
            self.send_response_task.cancel()
        self.send_response_task = None
        if self.check_response_task:
            self.check_response_task.cancel()
        self.check_response_task = None
