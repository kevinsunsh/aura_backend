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
from .doubao_client.asr_client import AsrClient
from .doubao_client.tts_client import TtsClient
from .message_processor_text import MessageProcessorText
from utils.utils import start_performance_point, end_performance_point
from muttering_data.mutter_index import get_muttering_file_path, MutteringType
from api_protocol.constant import *
from agents.aura_memory.message_store import MessageStore, Message

logger = logging.getLogger(__name__)

class AudioTaskType(Enum):
    """音频任务类型枚举"""
    PROCESS = "process"  # 正常处理任务
    QUICK_RESPONSE = "quick_response"  # 快速回复任务

class AudioClientType(Enum):
    """音频客户端类型枚举"""
    DIALOG_SESSION = "dialog_session"  # 使用DialogSession
    SEPARATE_CLIENTS = "separate_clients"  # 使用单独的ASR和TTS客户端

class IAudioClient(ABC):
    """音频客户端抽象接口"""
    
    @abstractmethod
    async def start(self) -> None:
        """启动客户端"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源"""
        pass
    
    @abstractmethod
    async def process_audio_chunk(self, audio_chunk: bytes) -> None:
        """处理音频块"""
        pass
    
    @abstractmethod
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False) -> None:
        """发送文本块"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass

class DialogSessionClient(IAudioClient):
    """DialogSession客户端包装器"""
    
    def __init__(self, 
                 uid: str,
                 asr_start_callback: Callable[[], None],
                 asr_response_callback: Callable[[str, bool], None],
                 asr_end_callback: Callable[[str], None],
                 tts_start_callback: Callable[[str], None],
                 tts_response_callback: Callable[[bytes], None],
                 tts_end_callback: Callable[[], None],
                 chat_end_callback: Callable[[str], None]):
        self.dialog_session = DialogSession(
            uid=uid,
            asr_start_callback=asr_start_callback,
            asr_response_callback=asr_response_callback,
            asr_end_callback=asr_end_callback,
            tts_start_callback=tts_start_callback,
            tts_response_callback=tts_response_callback,
            tts_end_callback=tts_end_callback,
            chat_end_callback=chat_end_callback
        )
    
    async def start(self) -> None:
        await self.dialog_session.start()
    
    async def cleanup(self) -> None:
        await self.dialog_session.cleanup()
    
    async def process_audio_chunk(self, audio_chunk: bytes) -> None:
        await self.dialog_session.process_audio_chunk(audio_chunk)
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False) -> None:
        await self.dialog_session.send_text_chunk(text, start, end)
    
    def is_connected(self) -> bool:
        return self.dialog_session.is_connected()

class SeparateClientsClient(IAudioClient):
    """单独的ASR和TTS客户端包装器"""
    
    def __init__(self,
                 uid: str,
                 asr_start_callback: Callable[[], None],
                 asr_response_callback: Callable[[str, bool], None],
                 asr_end_callback: Callable[[str], None],
                 tts_start_callback: Callable[[str], None],
                 tts_response_callback: Callable[[bytes], None],
                 tts_end_callback: Callable[[], None],
                 chat_end_callback: Callable[[str], None]):
        self.uid = uid
        
        # 存储回调函数
        self._asr_start_callback = asr_start_callback
        self._asr_response_callback = asr_response_callback
        self._asr_end_callback = asr_end_callback
        self._tts_start_callback = tts_start_callback
        self._tts_response_callback = tts_response_callback
        self._tts_end_callback = tts_end_callback
        self._chat_end_callback = chat_end_callback
        
        # 存储最终ASR结果
        self.final_asr_text = ""
        self.last_asr_text = ""
        
        # 创建ASR客户端
        self.asr_client = AsrClient(
            uid=uid,
            asr_start_callback=self._asr_start_callback,
            asr_response_callback=self._asr_response_callback,
            asr_end_callback=self._asr_end_callback
        )
        
        # 创建TTS客户端
        self.tts_client = TtsClient(
            uid=uid,
            tts_start_callback=self._tts_start_callback,
            tts_response_callback=self._tts_response_callback,
            tts_end_callback=self._tts_end_callback
        )
    
    async def start(self) -> None:
        await self.asr_client.start()
        await self.tts_client.start()
    
    async def cleanup(self) -> None:
        await self.asr_client.cleanup()
        await self.tts_client.cleanup()
    
    async def process_audio_chunk(self, audio_chunk: bytes) -> None:
        await self.asr_client.process_audio_chunk(audio_chunk)
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False) -> None:
        if text.strip():  # 只发送非空文本
            await self.tts_client.send_text_chunk(text)
    
    def is_connected(self) -> bool:
        return self.asr_client.is_connected() and self.tts_client.is_connected()

class AudioClientFactory:
    """音频客户端工厂"""
    
    @staticmethod
    def create_client(client_type: AudioClientType,
                     uid: str,
                     asr_start_callback: Callable[[], None],
                     asr_response_callback: Callable[[str, bool], None],
                     asr_end_callback: Callable[[str], None],
                     tts_start_callback: Callable[[str], None],
                     tts_response_callback: Callable[[bytes], None],
                     tts_end_callback: Callable[[], None],
                     chat_end_callback: Callable[[str], None]) -> IAudioClient:
        """创建音频客户端"""
        if client_type == AudioClientType.DIALOG_SESSION:
            return DialogSessionClient(
                uid=uid,
                asr_start_callback=asr_start_callback,
                asr_response_callback=asr_response_callback,
                asr_end_callback=asr_end_callback,
                tts_start_callback=tts_start_callback,
                tts_response_callback=tts_response_callback,
                tts_end_callback=tts_end_callback,
                chat_end_callback=chat_end_callback
            )
        elif client_type == AudioClientType.SEPARATE_CLIENTS:
            return SeparateClientsClient(
                uid=uid,
                asr_start_callback=asr_start_callback,
                asr_response_callback=asr_response_callback,
                asr_end_callback=asr_end_callback,
                tts_start_callback=tts_start_callback,
                tts_response_callback=tts_response_callback,
                tts_end_callback=tts_end_callback,
                chat_end_callback=chat_end_callback
            )
        else:
            raise ValueError(f"不支持的客户端类型: {client_type}")

class MessageProcessorAudio:
    """音频消息处理器，负责处理音频消息并启动ASR相关任务"""
    
    def __init__(self, 
                 chat_id: str,
                 user_id: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None,
                 client_type: AudioClientType = AudioClientType.DIALOG_SESSION):
        self.websocket_send_callback = websocket_send_callback
        self.task_lock = asyncio.Lock()
        self.is_running = True
        
        # 音频客户端相关
        self.client_type = client_type
        self.audio_client: Optional[IAudioClient] = None
        
        # 激活任务相关
        self.active_task: Optional[AudioTaskType] = None  # 当前激活的任务类型
        self.active_task_lock = asyncio.Lock()  # 激活任务的锁
        
        # 当前处理的 chat_stream
        self.chat_id = chat_id
        self.user_id = user_id
        
        # 创建文本处理器用于处理ASR结果
        self.text_processor = MessageProcessorText(
            chat_id=chat_id,
            user_id=user_id,
            websocket_send_callback=self._text_processor_callback
        )
        self.total_performance_point_id = None
        # ChatStart
        self.is_chat_start = True
    
    async def start(self):
        # 创建音频客户端
        self.audio_client = AudioClientFactory.create_client(
            client_type=self.client_type,
            uid=self.user_id,
            asr_start_callback=self.asr_start_callback,
            asr_response_callback=self.asr_response_callback,
            asr_end_callback=self.asr_end_callback,
            tts_start_callback=self.tts_start_callback,
            tts_response_callback=self.tts_response_callback,
            tts_end_callback=self.tts_end_callback,
            chat_end_callback=self.chat_end_callback
        )
        await self.audio_client.start()
        await self.text_processor.start()
    
    def get_current_client_type(self) -> AudioClientType:
        """获取当前客户端类型"""
        return self.client_type
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应并发送到TTS"""
        # 如果是聊天响应，发送到TTS
        if message.get("event") == ServerEvent.ChatResponse:
            chunk_content = message.get("payload_msg", {}).get("content", "")
            if chunk_content and self.audio_client and self.audio_client.is_connected():
                try:
                    if self.is_chat_start:
                        self.is_chat_start = False
                        await self.audio_client.send_text_chunk(chunk_content, start=True, end=False)
                    else:
                        await self.audio_client.send_text_chunk(chunk_content)
                    logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
                except Exception as e:
                    logger.error(f"发送TTS文本片段失败: {e}")
                    
        elif message.get("event") == ServerEvent.ChatEnded:
            # 结束TTS合成
            if self.audio_client and self.audio_client.is_connected():
                try:
                    self.is_chat_start = True
                    await self.audio_client.send_text_chunk("", start=False, end=True)
                    logger.info("TTS流式合成结束")
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
        elif message.get("event") == ServerEvent.MutteringResponse:
            # 读取muttering_data里的bin文件内容，并用TTSResponse事件发给客户端
            try:
                chunk_content = message.get("payload_msg", {}).get("content", "")
                file_path = get_muttering_file_path(MutteringType(chunk_content))
                with open(file_path, "rb") as f:
                    audio_data = f.read()
                if self.websocket_send_callback:
                    await self.websocket_send_callback({
                        "event": ServerEvent.TTSSentenceStart,
                        "payload_msg": {
                            "text": "我想想。"
                        }
                    })
                    await self.websocket_send_callback({
                        "event": ServerEvent.TTSResponse,
                        "payload_msg": {
                            "audio_data": audio_data
                        }
                    })
                    await self.websocket_send_callback({
                        "event": ServerEvent.TTSSentenceEnd,
                    })
            except Exception as e:
                logger.error(f"读取muttering_data bin文件失败: {e}")

        # 转发消息到websocket
        if self.websocket_send_callback:
            await self.websocket_send_callback(message)
    
    # DialogSession 回调函数
    async def asr_start_callback(self) -> None:
        """ASR开始回调 - 识别出首字时调用"""
        logger.info("ASR识别开始 - 检测到语音输入")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.ASRInfo,
            })
        if self.total_performance_point_id is None:
            self.total_performance_point_id = start_performance_point("总性能点")
        await self.text_processor.user_input_interruption()
    
    async def asr_response_callback(self, asr_text: str, is_interim: bool) -> None:
        """ASR响应回调 - 收到识别结果时调用"""
        logger.debug(f"收到ASR识别结果: {asr_text}")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.ASRResponse,
                "payload_msg": {
                    "results":[
                        {
                            "text": asr_text,
                            "is_interim": is_interim
                        }
                    ]
                }
            })
    
    async def asr_end_callback(self, asr_text: str) -> None:
        """ASR结束回调 - 识别完成时调用"""
        # logger.info(f"ASR识别结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.ASREnded,
            })
        # 如果asr_text为空，则不启动文本处理任务
        # await asyncio.sleep(1)
        # await self.audio_client.send_text_chunk("", start=True, end=False)
        # await asyncio.sleep(1)
        # await self.audio_client.send_text_chunk(asr_text)
        # await asyncio.sleep(1)
        # await self.audio_client.send_text_chunk("", start=False, end=True)
        # 如果有识别结果，启动文本处理任务
        if asr_text and asr_text.strip():
            await self._handle_asr_result(asr_text)
    
    async def tts_start_callback(self, text: str) -> None:
        """TTS开始回调 - 开始合成语音时调用"""
        logger.info(f"TTS合成开始 : {text}")
        # 保存消息到数据库
        MessageStore.get_instance().add_message(Message(
            msg_id=str(uuid.uuid4()),
            chat_id=self.chat_id,
            user_id="aura",
            platform="default",
            m_type="text",
            content=text,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        ))
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.TTSSentenceStart,
                "payload_msg": {
                    "text": text
                }
            })
    
    async def tts_response_callback(self, audio_data: bytes) -> None:
        """TTS响应回调 - 收到音频数据时调用"""
        logger.debug(f"收到TTS音频数据: {len(audio_data)} 字节")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.TTSResponse,
                "payload_msg": {
                    "audio_data": audio_data
                }
            })
        end_performance_point(self.total_performance_point_id)
    
    async def tts_end_callback(self) -> None:
        """TTS结束回调 - 语音合成完成时调用"""
        logger.debug("TTS合成结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEvent.TTSSentenceEnd,
            })
    
    async def chat_end_callback(self, text: str) -> None:
        """聊天结束回调 - 聊天结束时调用"""
        logger.info(f"闲聊结束 : {text}")
    
    async def _handle_asr_result(self, asr_text: str) -> None:
        """处理ASR识别结果"""
        try:
            logger.info(f"开始处理ASR结果: {asr_text}")
            
            # 使用文本处理器处理ASR结果
            result = await self.text_processor.handle_text_message(
                message_data={"message": asr_text}
            )
            
            logger.debug(f"ASR结果处理完成: {result}")
            
        except Exception as e:
            logger.error(f"处理ASR结果失败: {e}")

    async def handle_message(self,
                                  message_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理音频消息并启动异步任务接收ASR相关消息"""
        try:
            # 处理统一协议格式的payload_msg中的音频数据
            if "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
                if message_data.get("event") == ClientEvent.SayHello:
                    if isinstance(payload_msg, dict):
                        text_data = payload_msg.get("content", "")
                        result = await self.text_processor.handle_text_message(
                            message_data={"message": text_data}
                        )
                        logger.debug(f"文本结果处理完成: {result}")
                elif message_data.get("event") == ClientEvent.TaskRequest:
                    if isinstance(payload_msg, bytes):
                        # NO_SERIALIZATION的情况，payload_msg本身就是音频数据
                        logger.debug(f"使用统一协议音频数据(NO_SERIALIZATION): {len(payload_msg)} 字节")
                        if self.audio_client:
                            await self.audio_client.process_audio_chunk(payload_msg)
            # logger.info(f"已启动音频消息处理任务: chat_id={chat_stream.chat_id}")
            return {
                "success": True,
                "action": "audio_task_started",
                "chat_id": self.chat_id
            }
            
        except Exception as e:
            logger.error(f"启动音频消息处理任务失败: {e}")
            return {
                "success": False,
                "error": f"启动音频处理任务失败: {str(e)}"
            }
    
    async def cleanup(self) -> None:
        """清理资源"""
        if self.audio_client:
            try:
                logger.info("清理音频客户端资源...")
                await self.audio_client.cleanup()
                logger.info("音频客户端资源清理完成")
            except Exception as e:
                logger.warning(f"清理音频客户端时出错: {e}")
            finally:
                self.audio_client = None
                logger.info("音频客户端引用已置空")
        await self.text_processor.cleanup()
