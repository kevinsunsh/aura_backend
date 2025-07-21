import asyncio
import uuid
import queue
import threading
import time
import json
import logging
import base64
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

import websockets
import gzip

from api_protocol.constant import *

from .realtime_dialog_client import RealtimeDialogClient
from .doubao_config import ws_connect_config
from utils.utils import safe_call

logger = logging.getLogger(__name__)

class DialogSession:
    """对话会话管理类，集成RealtimeDialogClient和aura流式聊天"""
    def __init__(self, 
                 asr_start_callback: Callable[[], None] = None,
                 asr_response_callback: Callable[[dict, bool], None] = None,
                 asr_end_callback: Callable[[], None] = None,
                 tts_sentence_start_callback: Callable[[dict], None] = None,
                 tts_response_callback: Callable[[bytes], None] = None,
                 tts_sentence_end_callback: Callable[[], None] = None,
                 tts_ended_callback: Callable[[], None] = None,
                 chat_response_callback: Callable[[dict], None] = None,
                 chat_end_callback: Callable[[], None] = None,
                 ):
        self.uid = None
        self.session_id = None
        self.client = None

        # 状态管理
        self.is_running = False
        self.is_session_started = False
        
        # 服务器ASR结果
        self.asr_start_callback = asr_start_callback
        self.asr_response_callback = asr_response_callback
        self.asr_end_callback = asr_end_callback

        # 服务器TTS结果
        self.tts_sentence_start_callback = tts_sentence_start_callback
        self.tts_response_callback = tts_response_callback
        self.tts_sentence_end_callback = tts_sentence_end_callback
        self.tts_ended_callback = tts_ended_callback

        # 服务器Chat结果
        self.chat_response_callback = chat_response_callback
        self.chat_end_callback = chat_end_callback
        self.message_loop = None
    
    async def _connect(self) -> bool:
        """执行连接逻辑"""
        try:
            # 创建新的客户端实例
            self.client = RealtimeDialogClient(config=ws_connect_config, session_id=self.session_id)
            
            # 重新连接
            await self.client.connect()

            # 执行连接握手
            await self.client.start_connection()
            response = await self.client.receive_server_response()
            logger.info(f"连接响应: event={response.get('event')}")
            if not response.get('event') == ServerEvent.ConnectionStarted:
                return False
            
            await self.client.start_session()
            response = await self.client.receive_server_response()
            logger.info(f"会话响应: event={response.get('event')}")
            if not response.get('event') == ServerEvent.SessionStarted:
                return False
            
            self.is_running = True
            self.is_session_started = True
            return True
        except Exception as e:
            logger.error(f"连接失败: {e}")
            return False
    
    async def start(self, chat_id: str, user_id: str) -> None:
        """启动对话会话"""
        try:
            self.session_id = chat_id
            self.uid = chat_id
            logger.info(f"启动对话会话: {self.session_id}")
            await self._connect()
            self.message_loop = asyncio.create_task(self.message_receive_loop())
        except Exception as e:
            logger.error(f"对话会话错误: {e}")
    
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
        if response == {}:
            return
        
        logger.debug(f"处理服务器响应: {response}")

        # 处理事件类型响应
        if response.get('event') is not None:
            event_id = response.get('event')
            payload_msg = response.get('payload_msg', {})
            logger.debug(f"处理服务器事件: {event_id}")
            await self._handle_server_event(event_id, payload_msg)
            return
    
    async def _handle_server_event(self, event_id: int, payload_msg: Dict[str, Any]) -> None:
        # Connect类事件 (50-52)
        if event_id == ServerEvent.ConnectionStarted:
            await self._on_connection_started(payload_msg)
        elif event_id == ServerEvent.ConnectionFailed:
            await self._on_connection_failed(payload_msg)
        elif event_id == ServerEvent.ConnectionFinished:
            await self._on_connection_finished(payload_msg)
        # Session类事件 (150-153)
        elif event_id == ServerEvent.SessionStarted:
            await self._on_session_started(payload_msg)
        elif event_id == ServerEvent.SessionFinished:
            await self._on_session_finished(payload_msg)
        elif event_id == ServerEvent.SessionFailed:
            await self._on_session_failed(payload_msg)
        # TTS类事件 (350-359)
        elif event_id == ServerEvent.TTSSentenceStart:
            await safe_call(self.tts_sentence_start_callback, payload_msg)
        elif event_id == ServerEvent.TTSSentenceEnd:
            await safe_call(self.tts_sentence_end_callback)
        elif event_id == ServerEvent.TTSResponse:
            await safe_call(self.tts_response_callback, payload_msg)
        elif event_id == ServerEvent.TTSEnded:
            await safe_call(self.tts_ended_callback)
        # ASR类事件 (450-459)
        elif event_id == ServerEvent.ASRInfo:
            await safe_call(self.asr_start_callback)
        elif event_id == ServerEvent.ASRResponse:
            await safe_call(self.asr_response_callback, payload_msg)
        elif event_id == ServerEvent.ASREnded:
            await safe_call(self.asr_end_callback)
        # Chat类事件 (550-559)
        elif event_id == ServerEvent.ChatResponse:
            await safe_call(self.chat_response_callback, payload_msg)
        elif event_id == ServerEvent.ChatEnded:
            await safe_call(self.chat_end_callback)
        else:
            logger.warning(f"未知事件ID: {event_id}")
    
    # Connect类事件回调方法
    async def _on_connection_started(self, payload: Dict[str, Any]) -> None:
        """连接建立成功事件回调"""
        logger.info("连接建立成功")

    async def _on_connection_failed(self, payload: Dict[str, Any]) -> None:
        """连接建立失败事件回调"""
        error_msg = payload.get("error", "未知错误")
        logger.error(f"连接建立失败: {error_msg}")

    async def _on_connection_finished(self, payload: Dict[str, Any]) -> None:
        """连接结束事件回调"""
        logger.info("连接已结束")

    # Session类事件回调方法
    async def _on_session_started(self, payload: Dict[str, Any]) -> None:
        """会话启动成功事件回调"""
        dialog_id = payload.get("dialog_id", "")
        logger.info(f"会话启动成功，dialog_id: {dialog_id}")

    async def _on_session_finished(self, payload: Dict[str, Any]) -> None:
        """会话结束事件回调"""
        logger.info("会话已结束")
        self.is_session_started = False

    async def _on_session_failed(self, payload: Dict[str, Any]) -> None:
        """会话失败事件回调"""
        error_msg = payload.get("error", "未知错误")
        logger.error(f"会话失败: {error_msg}")
        self.is_session_started = False
    
    async def message_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while self.is_running and self.is_session_started:
                try:
                    # 尝试从服务器接收响应
                    response = await self.client.receive_server_response()
                    await self._handle_server_response(response)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("服务器连接已关闭，尝试重连...")
                    await self._connect()
                except Exception as e:
                    logger.warning(f"服务器接收响应失败: {e}")
                    await self._connect()
        except asyncio.CancelledError:
            logger.info("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息出现未预期错误: {e}")
        
    async def process_audio_chunk(self, audio_data: bytes) -> None:
        """处理音频输入"""
        try:
            # 检查连接状态并尝试重连
            if not self.is_connected():
                logger.warning("连接检查失败，无法发送音频数据")
                return
                
            self.last_input_time = time.time()
            logger.debug(f"开始发送音频数据: {len(audio_data)} 字节")
            await self.client.task_request(audio_data)
            logger.debug(f"已发送音频数据: {len(audio_data)} 字节")
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionResetError,
                BrokenPipeError) as e:
            logger.error(f"WebSocket连接相关错误: {e}")
            await self._connect()
        except Exception as e:
            logger.error(f"发送音频数据失败: {e}")
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["connection", "websocket", "ssl", "socket", "network"]):
                await self._connect()
                logger.info("已触发重连，音频数据将在重连后重试")
            else:
                # 其他类型的错误，记录但不重连
                logger.error(f"非连接相关错误，不进行重连: {e}")
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False) -> None:
        """发送文本块到TTS（兼容TTS客户端的接口）"""
        await self.send_chat_tts_text(text, start, end)
    
    async def send_say_hello(self, content: str) -> None:
        """发送打招呼消息"""
        try:
            # 检查连接状态并尝试重连
            if not self.is_connected():
                logger.warning("连接检查失败，无法发送打招呼消息")
                return
                
            await self.client.say_hello(content)
            logger.info(f"已发送打招呼消息: {content}")
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionResetError,
                BrokenPipeError) as e:
            logger.error(f"WebSocket连接相关错误: {e}")
            await self._connect()
        except Exception as e:
            logger.error(f"发送打招呼消息失败: {e}")
            # 如果是连接相关错误，尝试重连
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["connection", "websocket", "ssl", "socket", "network"]):
                await self._connect()
            else:
                logger.error(f"非连接相关错误，不进行重连: {e}")
    
    async def send_chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """发送聊天TTS文本"""
        try:
            # 检查连接状态并尝试重连
            if not self.is_connected():
                logger.warning("连接检查失败，无法发送TTS文本")
                return
            
            await self.client.chat_tts_text(content, start, end)
        except Exception as e:
            logger.error(f"发送TTS文本失败: {e}")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            return (self.is_running and 
                    self.is_session_started and 
                    self.client.ws is not None and 
                    self._is_websocket_open())
        except Exception as e:
            logger.debug(f"检查连接状态时出错: {e}")
            return False
    
    def _is_websocket_open(self) -> bool:
        """检查WebSocket是否开启"""
        try:
            if self.client.ws is None:
                return False
            
            # 检查是否有state属性 (新版websockets)
            if hasattr(self.client.ws, 'state'):
                # 导入State枚举
                try:
                    from websockets.protocol import State
                    if self.client.ws.state == State.OPEN:
                        return True
                    else:
                        return False
                except ImportError:
                    # 如果导入失败，尝试其他方法
                    pass
            
            # 检查是否有closed属性 (旧版websockets)
            if hasattr(self.client.ws, 'closed'):
                return not self.client.ws.closed
            
            # 检查是否有open属性 (某些版本)
            if hasattr(self.client.ws, 'open'):
                return self.client.ws.open
            
            # 如果以上都没有，尝试通过其他方式检查
            # 检查是否有close_code属性，如果有且不为None，说明连接已关闭
            if hasattr(self.client.ws, 'close_code'):
                return self.client.ws.close_code is None
            
            # 最后的兜底方案，假设连接是开启的
            logger.warning("无法确定WebSocket连接状态，假设连接正常")
            return True
            
        except Exception as e:
            logger.debug(f"检查WebSocket状态时出错: {e}")
            return False
    
    async def cleanup(self) -> None:
        """清理资源"""
        try:
            # 结束会话
            if self.is_session_started:
                await self.client.finish_session()

            await asyncio.sleep(0.1)
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
            self.is_running = False
            self.is_session_started = False
            if self.message_loop:
                self.message_loop.cancel()
                self.message_loop = None
            logger.info(f"对话会话已清理: {self.session_id}")
            self.session_id = None
            self.uid = None
        except Exception as e:
            logger.error(f"DoubaoClient清理资源时出错: {e}")
