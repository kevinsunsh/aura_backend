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

from .base_client import AsrClient
from .config import asr_config
from utils.utils import safe_call

logger = logging.getLogger(__name__)

class AuraDialogSession:
    """对话会话管理类，集成RealtimeDialogClient和aura流式聊天"""
    def __init__(self, 
                 asr_start_callback: Callable[[], None] = None,
                 asr_response_callback: Callable[[str, bool], None] = None,
                 asr_end_callback: Callable[[], None] = None,
                 ):
        self.session_id = None
        self.client = None

        # 状态管理
        self.is_running = True
        self.is_session_finished = False
                
        # 服务器ASR结果
        self.server_asr_result = ""
        self.asr_start_callback = asr_start_callback
        self.asr_response_callback = asr_response_callback
        self.asr_end_callback = asr_end_callback
    
    async def start(self, chat_id: str, user_id: str) -> None:
        """启动对话会话"""
        try:
            logger.debug(f"启动对话会话: {chat_id}")
            self.session_id = chat_id
            self.client = AsrClient(config=asr_config)
            await self.client.start(chat_id, user_id)
            self.message_loop = asyncio.create_task(self.message_receive_loop())
        except Exception as e:
            logger.error(f"对话会话错误: {e}")
    
    async def _connect(self) -> bool:
        """执行重连逻辑"""
        try:
            # 创建新的客户端实例
            self.client = AsrClient(config=asr_config)
            # 重新连接
            await self.client.connect()
            return True
        except Exception as e:
            return False
    
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
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
            await self._on_connection_started()
        elif event_id == ServerEvent.ConnectionFailed:
            await self._on_connection_failed()
        elif event_id == ServerEvent.ConnectionFinished:
            await self._on_connection_finished()
        # Session类事件 (150-153)
        elif event_id == ServerEvent.SessionStarted:
            await self._on_session_started()
        elif event_id == ServerEvent.SessionFinished:
            await self._on_session_finished()
        elif event_id == ServerEvent.SessionFailed:
            await self._on_session_failed()
        # ASR类事件 (450-459)
        elif event_id == ServerEvent.ASRInfo:
            await self._on_asr_info()
        elif event_id == ServerEvent.ASRResponse:
            await self._on_asr_response(payload_msg)
        elif event_id == ServerEvent.ASREnded:
            await self._on_asr_ended()
        else:
            logger.warning(f"未知事件ID: {event_id}")
    
    # Connect类事件回调方法
    async def _on_connection_started(self) -> None:
        """连接建立成功事件回调"""
        logger.debug("连接建立成功")
    
    async def _on_connection_failed(self) -> None:
        """连接建立失败事件回调"""
        logger.error("连接建立失败")
    
    async def _on_connection_finished(self) -> None:
        """连接结束事件回调"""
        logger.debug("连接已结束")
    
    # Session类事件回调方法
    async def _on_session_started(self) -> None:
        """会话启动成功事件回调"""
        logger.debug("会话启动成功")
    
    async def _on_session_finished(self) -> None:
        """会话结束事件回调"""
        logger.debug("会话已结束")
    
    async def _on_session_failed(self) -> None:
        """会话失败事件回调"""
        logger.error("会话失败")
    
    # ASR类事件回调方法
    async def _on_asr_info(self) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.debug("ASR识别出首字")
        await safe_call(self.asr_start_callback)
    
    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        logger.debug("ASR响应事件回调")
        await safe_call(self.asr_response_callback, payload)
    
    async def _on_asr_ended(self) -> None:
        """ASR结束事件回调"""
        logger.debug("ASR识别结束")
        await safe_call(self.asr_end_callback)
    
    async def message_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while self.is_running:
                # 尝试从客户端接收响应
                try:
                    response = await self.client.receive_server_response()
                    await self._handle_server_response(response)
                except Exception as e:
                    await self._connect()
        except asyncio.CancelledError:
            logger.debug("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息出现未预期错误: {e}")
    
    async def process_audio_chunk(self, audio_data: bytes) -> None:
        """处理音频输入"""
        try:
            await self.client.task_request(audio_data)
        except Exception as e:
            logger.error(f"发送音频数据失败: {e}")
            await self._connect()
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            return self.client.ws is not None and self._is_websocket_open()
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
            await self.client.cleanup()
            self.message_loop.cancel()
            self.message_loop = None
            logger.debug(f"对话会话已清理: {self.session_id}")
        except Exception as e:
            logger.error(f"AuraDialogSession清理资源时出错: {e}")
