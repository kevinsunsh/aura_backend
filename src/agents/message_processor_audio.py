import asyncio
import logging
import uuid
import base64
import json
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from enum import Enum

from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStream, ChatStreamManager
from .doubao_client.dialog_session import DialogSession
from .doubao_client.asr_client import AsrClient
from .doubao_client.tts_client import TtsClient
from .message_processor_text import MessageProcessorText
from .doubao_client.config import ws_connect_config
from .configuration import ServerEventEnum

logger = logging.getLogger(__name__)

class AudioTaskType(Enum):
    """音频任务类型枚举"""
    PROCESS = "process"  # 正常处理任务
    QUICK_RESPONSE = "quick_response"  # 快速回复任务

class MessageProcessorAudio:
    """音频消息处理器，负责处理音频消息并启动ASR相关任务"""
    
    def __init__(self, 
                 message_store: MessageStore,
                 chat_stream_manager: ChatStreamManager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.message_store = message_store
        self.chat_stream_manager = chat_stream_manager
        self.asr_client = None  # 使用新的ASR客户端
        self.tts_client = None  # 使用新的TTS客户端
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
        self.task_lock = asyncio.Lock()
        self.is_running = True
        
        # 激活任务相关
        self.active_task: Optional[AudioTaskType] = None  # 当前激活的任务类型
        self.active_task_lock = asyncio.Lock()  # 激活任务的锁
        
        # 当前处理的 chat_stream
        self.current_chat_stream: Optional[ChatStream] = None
        
        # 创建文本处理器用于处理ASR结果
        self.text_processor = MessageProcessorText(
            message_store=message_store,
            chat_stream_manager=chat_stream_manager,
            db_conn_string=db_conn_string,
            websocket_send_callback=self._text_processor_callback
        )
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应并发送到TTS"""
        # 如果是聊天响应，发送到TTS
        if message.get("event") == ServerEventEnum.ChatResponse.value:
            chunk_content = message.get("payload_msg", {}).get("content", "")
            if chunk_content and self.tts_client and self.tts_client.is_connected():
                try:
                    await self.tts_client.send_text_chunk(chunk_content)
                    logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
                except Exception as e:
                    logger.error(f"发送TTS文本片段失败: {e}")
                    
        elif message.get("event") == ServerEventEnum.ChatEnded.value:
            # 结束TTS合成
            if self.tts_client and self.tts_client.is_connected():
                try:
                    logger.info("TTS流式合成结束")
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
        
        # 转发消息到websocket
        if self.websocket_send_callback:
            await self.websocket_send_callback(message)
    
    # ASR 回调函数
    async def asr_start_callback(self) -> None:
        """ASR开始回调 - 识别出首字时调用"""
        logger.info("ASR识别开始 - 检测到语音输入")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ASRInfo.value
            })
        await self.text_processor.cleanup()
    
    async def asr_response_callback(self, asr_text: str, is_interim: bool) -> None:
        """ASR响应回调 - 收到识别结果时调用"""
        logger.debug(f"收到ASR识别结果: {asr_text}")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ASRResponse.value,
                "payload_msg": {
                    "text": asr_text,
                    "is_interim": is_interim
                }
            })
        # 如果有识别结果，启动文本处理任务
        if asr_text and asr_text.strip():
            await self._handle_asr_result(asr_text, self.current_chat_stream)
    
    async def asr_end_callback(self) -> None:
        """ASR结束回调 - 识别完成时调用"""
        logger.info(f"ASR识别结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ASREnded.value
            })
    
    # TTS 回调函数
    async def tts_start_callback(self, text: str) -> None:
        """TTS开始回调 - 开始合成语音时调用"""
        logger.debug("TTS合成开始")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.TTSSentenceStart.value,
                "payload_msg": {
                    "text": text
                }
            })
    
    async def tts_response_callback(self, audio_data: bytes) -> None:
        """TTS响应回调 - 收到音频数据时调用"""
        logger.debug(f"收到TTS音频数据: {len(audio_data)} 字节")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.TTSResponse.value,
                "payload_msg": {
                    "audio_data": audio_data,
                    "audio_size": len(audio_data)
                }
            })
    
    async def tts_end_callback(self) -> None:
        """TTS结束回调 - 语音合成完成时调用"""
        logger.debug("TTS合成结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.TTSSentenceEnd.value
            })
    
    # Chat 回调函数
    async def chat_end_callback(self, chat_response: str) -> None:
        """聊天结束回调 - 收到完整聊天响应时调用"""
        logger.info(f"聊天响应完成: {chat_response[:100]}...")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ChatEnded.value
            })
    
    async def _handle_asr_result(self, asr_text: str, chat_stream: ChatStream = None) -> None:
        """处理ASR识别结果"""
        try:
            logger.info(f"打断现有的任务，开始处理ASR结果: {asr_text}")
            
            if not chat_stream:
                logger.warning("没有提供 chat_stream，无法处理 ASR 结果")
                return
            
            # 使用文本处理器处理ASR结果
            result = await self.text_processor.handle_text_message(
                message_data={"message": asr_text},
                chat_stream=chat_stream
            )
            
            logger.debug(f"ASR结果处理完成: {result}")
            
        except Exception as e:
            logger.error(f"处理ASR结果失败: {e}")

    async def handle_audio_message(self, 
                                  message_data: Dict[str, Any], 
                                  chat_stream: ChatStream) -> Dict[str, Any]:
        """处理音频消息并启动异步任务接收ASR相关消息"""
        try:
            # 设置当前处理的 chat_stream
            self.current_chat_stream = chat_stream
            
            # 初始化ASR客户端
            if self.asr_client is None:
                self.asr_client = AsrClient(
                    uid=chat_stream.chat_id,
                    asr_start_callback=self.asr_start_callback,
                    asr_response_callback=self.asr_response_callback,
                    asr_end_callback=self.asr_end_callback
                )
                await self.asr_client.start()
            
            # 初始化TTS客户端（使用配置文件）
            if self.tts_client is None:
                self.tts_client = TtsClient(
                    uid=chat_stream.chat_id,
                    tts_start_callback=self.tts_start_callback,
                    tts_response_callback=self.tts_response_callback,
                    tts_end_callback=self.tts_end_callback
                )
                await self.tts_client.start()
            
            # 处理音频输入 - 支持二进制协议和传统base64格式
            audio_data = None
            
            # 优先处理二进制协议的audio_data
            if "audio_data" in message_data and message_data["audio_data"]:
                audio_data = message_data["audio_data"]
                logger.debug(f"使用二进制协议音频数据: {len(audio_data)} 字节")
            
            if audio_data:
                await self.asr_client.process_audio_chunk(audio_data)
            else:
                logger.warning("音频消息中没有找到音频数据")
                return {
                    "success": False,
                    "error": "音频消息中缺少音频数据"
                }
            
            # logger.info(f"已启动音频消息处理任务: chat_id={chat_stream.chat_id}")
            
            return {
                "success": True,
                "action": "audio_task_started",
                "chat_id": chat_stream.chat_id
            }
            
        except Exception as e:
            logger.error(f"启动音频消息处理任务失败: {e}")
            return {
                "success": False,
                "error": f"启动音频处理任务失败: {str(e)}"
            }
    
    async def finish_audio_input(self) -> None:
        """结束音频输入，通知ASR客户端发送最后的音频包"""
        if self.asr_client:
            await self.asr_client.finish_audio()
            
    async def cleanup(self) -> None:
        """清理资源"""
        if self.asr_client:
            await self.asr_client.cleanup()
            self.asr_client = None
        if self.tts_client:
            await self.tts_client.cleanup()
            self.tts_client = None
        self.current_chat_stream = None
