import ssl
import time
import asyncio
import websockets
from .config import *
import multiprocessing
from loguru import logger
from typing import Dict, Any
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response
from .base_client import BaseClient

class VADClient(BaseClient):
    """VAD客户端"""
    def __init__(self, config: Dict[str, Any], input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, is_process_running: Any, process_timer: Any):
        super().__init__(config)
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
        self.process_timer = process_timer
    
    async def task_request(self, audio: bytes) -> None:
        """TaskRequest - 客户端事件ID: 200"""
        if not self.is_running:
            return
        # 发送前检查SSL连接状态
        if self._is_websocket_closed():
            logger.warning("发送音频数据前检测到SSL连接已关闭")
            raise websockets.exceptions.ConnectionClosed(None, 1000, "SSL connection is closed")
        
        task_request = client_generate_request(
            payload_data=audio,
            message_type=CLIENT_AUDIO_ONLY_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=NO_SERIALIZATION,
            compression_type=GZIP,
            event=ClientEvent.TaskRequest,
            session_id=self.session_id,
            skip_audio_compression=True
        )
        try:
            await self.ws.send(task_request)
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            # 捕获所有可能的连接相关异常
            error_msg = str(e).lower()
            if "ssl" in error_msg or "connection" in error_msg:
                logger.warning(f"发送音频数据时检测到连接问题: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")
            else:
                # 重新抛出其他类型的异常
                raise
        
    @staticmethod
    def process_entry(input_queue, output_queue, is_process_running, process_timer):
        asyncio.run(VADClient.main(input_queue, output_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = VADClient(
            config=vad_config,
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running,
            process_timer=process_timer
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                client.is_process_running.value = await client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    await client.task_request(msg["data"])
    
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
        # 处理事件类型响应
        if response.get('event') is None:
            return
        event_id = response.get('event')
        payload_msg = response.get('payload_msg', {})
        # Connect类事件 (50-52)
        if event_id == ServerEvent.ConnectionStarted:
            logger.info("连接建立成功")
        elif event_id == ServerEvent.ConnectionFailed:
            logger.error("连接建立失败")
        elif event_id == ServerEvent.ConnectionFinished:
            logger.info("连接已结束")
        # Session类事件 (150-153)
        elif event_id == ServerEvent.SessionStarted:
            logger.info("会话启动成功")
        elif event_id == ServerEvent.SessionFinished:
            logger.info("会话已结束")
        elif event_id == ServerEvent.SessionFailed:
            logger.error("会话失败")
        # VAD类事件 (450-459)
        elif event_id == ServerEvent.ASRInfo:
            logger.debug("VAD识别出首字")
            self.output_queue.put({"event": ServerEvent.ASRInfo})
        elif event_id == ServerEvent.ASREnded:
            logger.bind(tag="BASE").info("VAD识别结束")
            self.output_queue.put({"event": ServerEvent.ASREnded})
            self.process_timer.value = time.time()
        else:
            logger.warning(f"未知事件ID: {event_id}")
        

