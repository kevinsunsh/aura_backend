import ssl
import logging
import asyncio
import websockets
from .config import *
import multiprocessing
from typing import Dict, Any
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response
from .base_client import BaseClient

logger = logging.getLogger(__name__)

class ASRClient(BaseClient):
    """ASR客户端"""
    def __init__(self, config: Dict[str, Any], input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, is_process_running: multiprocessing.Value):
        super().__init__(config)
        self.is_running = False
        self.message_loop = None
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
    
    async def start(self, chat_id: str, user_id: str) -> None:
        """启动客户端"""
        try:
            self.session_id = chat_id
            self.user_id = user_id
            self.chat_id = chat_id
            await self.connect()
            self.message_loop = asyncio.create_task(self.message_receive_loop())
        except Exception as e:
            logger.error(f"启动客户端失败: {e}")
            raise e
    
    async def connect(self) -> None:
        """连接服务器"""
        try:
            self.is_running = False
            await super().connect()
            self.is_running = True
        except Exception as e:
            logger.error(f"连接服务器失败: {e}")
            raise e
    
    async def cleanup(self) -> None:
        """清理客户端"""
        if self.message_loop:
            self.message_loop.cancel()
            self.message_loop = None
        self.is_running = False
        await super().cleanup()

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
    def process_entry(input_queue, output_queue, is_process_running):
        asyncio.run(ASRClient.main(input_queue, output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = ASRClient(
            config=vad_config,
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                await client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    await client.task_request(msg["data"])
    
    async def _on_asr_ended(self) -> None:
        """ASR结束事件回调"""
        self.output_queue.put({"event": ServerEvent.ASREnded})
    
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
        # ASR类事件 (450-459)
        elif event_id == ServerEvent.ASRInfo:
            logger.info("ASR识别出首字")
            self.output_queue.put({"event": ServerEvent.ASREnded})
        elif event_id == ServerEvent.ASRResponse:
            logger.info("ASR响应事件回调")
            self.output_queue.put({"event": ServerEvent.ASRResponse, "payload_msg": payload_msg})
        elif event_id == ServerEvent.ASREnded:
            logger.info("ASR识别结束")
            self.output_queue.put({"event": ServerEvent.ASREnded})
        else:
            logger.warning(f"未知事件ID: {event_id}")
    
    async def message_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while True:
                # 尝试从客户端接收响应
                try:
                    if not self.is_running:
                        await asyncio.sleep(0.1)
                        continue
                    response = await self.receive_server_response()
                    await self._handle_server_response(response)
                except Exception as e:
                    await self._connect()
        except asyncio.CancelledError:
            logger.debug("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息出现未预期错误: {e}")
