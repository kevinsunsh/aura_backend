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
from .message_processor_text import MessageProcessorText
from .doubao_client.config import ws_connect_config
from .configuration import ServerEventEnum
from utils.utils import start_performance_point, end_performance_point

logger = logging.getLogger(__name__)

class AudioTaskType(Enum):
    """音频任务类型枚举"""
    PROCESS = "process"  # 正常处理任务
    QUICK_RESPONSE = "quick_response"  # 快速回复任务

class MessageProcessorAudio:
    """音频消息处理器，负责处理音频消息并启动ASR相关任务"""
    
    def __init__(self, 
                 message_store: MessageStore,
                 chat_stream: ChatStream,
                 chat_stream_manager: ChatStreamManager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.message_store = message_store
        self.chat_stream_manager = chat_stream_manager
        self.dialog_session = None  # 使用DialogSession替代单独的ASR和TTS客户端
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
        self.task_lock = asyncio.Lock()
        self.is_running = True
        
        # 激活任务相关
        self.active_task: Optional[AudioTaskType] = None  # 当前激活的任务类型
        self.active_task_lock = asyncio.Lock()  # 激活任务的锁
        
        # 当前处理的 chat_stream
        self.current_chat_stream = chat_stream
        
        # 创建文本处理器用于处理ASR结果
        self.text_processor = MessageProcessorText(
            message_store=message_store,
            chat_stream=chat_stream,
            chat_stream_manager=chat_stream_manager,
            db_conn_string=db_conn_string,
            websocket_send_callback=self._text_processor_callback
        )
        self.total_performance_point_id = None
        # ChatStart
        self.is_chat_start = True
    
    async def start(self):
        # 初始化DialogSession
        if self.dialog_session is None:
            self.dialog_session = DialogSession(
                uid=self.current_chat_stream.chat_id,
                asr_start_callback=self.asr_start_callback,
                asr_response_callback=self.asr_response_callback,
                asr_end_callback=self.asr_end_callback,
                tts_start_callback=self.tts_start_callback,
                tts_response_callback=self.tts_response_callback,
                tts_end_callback=self.tts_end_callback,
                chat_end_callback=self.chat_end_callback
            )
            await self.dialog_session.start()
        await self.text_processor.start()
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应并发送到TTS"""
        # 如果是聊天响应，发送到TTS
        if message.get("event") == ServerEventEnum.ChatResponse.value:
            chunk_content = message.get("payload_msg", {}).get("content", "")
            if chunk_content and self.dialog_session and self.dialog_session.is_connected():
                try:
                    if self.is_chat_start:
                        self.is_chat_start = False
                        await self.dialog_session.send_text_chunk(chunk_content, start=True, end=False)
                    await self.dialog_session.send_text_chunk(chunk_content)
                    logger.debug(f"已发送TTS文本片段: {chunk_content[:30]}...")
                except Exception as e:
                    logger.error(f"发送TTS文本片段失败: {e}")
                    
        elif message.get("event") == ServerEventEnum.ChatEnded.value:
            # 结束TTS合成
            if self.dialog_session and self.dialog_session.is_connected():
                try:
                    self.is_chat_start = True
                    await self.dialog_session.send_text_chunk("", start=False, end=True)
                    logger.info("TTS流式合成结束")
                except Exception as e:
                    logger.error(f"结束TTS合成失败: {e}")
        
        # 转发消息到websocket
        if self.websocket_send_callback:
            await self.websocket_send_callback(message)
    
    # DialogSession 回调函数
    async def asr_start_callback(self) -> None:
        """ASR开始回调 - 识别出首字时调用"""
        logger.info("ASR识别开始 - 检测到语音输入")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ASRInfo.value
            })
        if self.total_performance_point_id is None:
            self.total_performance_point_id = start_performance_point("总性能点")
        await self.text_processor.user_input_interruption()
    
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
    
    async def asr_end_callback(self, asr_text: str) -> None:
        """ASR结束回调 - 识别完成时调用"""
        # logger.info(f"ASR识别结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.ASREnded.value
            })
        # 如果asr_text为空，则不启动文本处理任务
        # await self.dialog_session.send_text_chunk("我想想", start=True, end=False)
        # 如果有识别结果，启动文本处理任务
        if asr_text and asr_text.strip():
            await self._handle_asr_result(asr_text, self.current_chat_stream)
    
    async def tts_start_callback(self, text: str) -> None:
        """TTS开始回调 - 开始合成语音时调用"""
        logger.info(f"TTS合成开始 : {text}")
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
                    "audio_data": audio_data
                }
            })
        end_performance_point(self.total_performance_point_id)
    
    async def tts_end_callback(self) -> None:
        """TTS结束回调 - 语音合成完成时调用"""
        logger.debug("TTS合成结束")
        if self.websocket_send_callback:
            await self.websocket_send_callback({
                "event": ServerEventEnum.TTSSentenceEnd.value
            })
    
    async def chat_end_callback(self, text: str) -> None:
        """聊天结束回调 - 聊天结束时调用"""
        logger.info(f"闲聊结束 : {text}")
        # await self.message_store.add_message(Message(
        #     msg_id=str(uuid.uuid4()),
        #     chat_id=self.current_chat_stream.chat_id,
        #     user_id="aura",
        #     platform="default",
        #     m_type="text",
        #     content=text,
        #     data={},
        #     created_at=int(datetime.now().timestamp() * 1000)
        # ))
    
    async def _handle_asr_result(self, asr_text: str, chat_stream: ChatStream = None) -> None:
        """处理ASR识别结果"""
        try:
            logger.info(f"开始处理ASR结果: {asr_text}")
            
            if not chat_stream:
                logger.warning("没有提供 chat_stream，无法处理 ASR 结果")
                return
            
            # 使用文本处理器处理ASR结果
            result = await self.text_processor.handle_text_message(
                message_data={"message": asr_text}
            )
            
            logger.debug(f"ASR结果处理完成: {result}")
            
        except Exception as e:
            logger.error(f"处理ASR结果失败: {e}")

    async def handle_audio_message(self, 
                                  message_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理音频消息并启动异步任务接收ASR相关消息"""
        try:
            # 处理音频输入 - 支持二进制协议和传统base64格式
            audio_data = None
            
            # 优先处理二进制协议的audio_data（向后兼容）
            if "audio_data" in message_data and message_data["audio_data"]:
                audio_data = message_data["audio_data"]
                logger.debug(f"使用二进制协议音频数据: {len(audio_data)} 字节")
            # 处理统一协议格式的payload_msg中的音频数据
            elif "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
                if isinstance(payload_msg, dict):
                    # JSON序列化的情况，从字典中提取audio_data
                    if "audio_data" in payload_msg:
                        audio_data = payload_msg["audio_data"]
                        logger.debug(f"使用统一协议音频数据(JSON): {len(audio_data)} 字节")
                elif isinstance(payload_msg, bytes):
                    # NO_SERIALIZATION的情况，payload_msg本身就是音频数据
                    audio_data = payload_msg
                    logger.debug(f"使用统一协议音频数据(NO_SERIALIZATION): {len(audio_data)} 字节")
            
            if audio_data:
                await self.dialog_session.process_audio_chunk(audio_data)
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
                "chat_id": self.current_chat_stream.chat_id
            }
            
        except Exception as e:
            logger.error(f"启动音频消息处理任务失败: {e}")
            return {
                "success": False,
                "error": f"启动音频处理任务失败: {str(e)}"
            }
    
    async def cleanup(self) -> None:
        """清理资源"""
        if self.dialog_session:
            try:
                logger.info("清理DialogSession资源...")
                await self.dialog_session.cleanup()
                logger.info("DialogSession资源清理完成")
            except Exception as e:
                logger.warning(f"清理DialogSession时出错: {e}")
            finally:
                self.dialog_session = None
                logger.info("DialogSession引用已置空")
        self.current_chat_stream = None
