import websockets
import gzip
import json
import asyncio
import logging

from typing import Dict, Any

from . import protocol
from . import config

logger = logging.getLogger(__name__)

class RealtimeDialogClient:
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self, config: Dict[str, Any], session_id: str):
        self.config = config
        self.logid = ""
        self.session_id = session_id
        self.ws = None
        self.recv_lock = asyncio.Lock()  # 防止并发recv调用

    async def connect(self) -> None:
        """建立WebSocket连接"""
        logger.info(f"连接服务器: {self.config['base_url']}")
        self.ws = await websockets.connect(
            self.config['base_url'],
            additional_headers=self.config['headers'],
            ping_interval=None
        )
        
        # 新版本websockets不再提供获取响应头的方法
        self.logid = ""
        logger.info(f"WebSocket连接已建立")
    
    async def start_connection(self) -> None:
        """StartConnection - 客户端事件ID: 1"""
        start_connection_request = bytearray(protocol.generate_header())
        start_connection_request.extend(int(1).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        start_connection_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        start_connection_request.extend(payload_bytes)
        await self.ws.send(start_connection_request)
        logger.info("StartConnection请求已发送")

    async def start_session(self) -> None:
        """StartSession - 客户端事件ID: 100"""
        session_params = config.start_session_req
        payload_bytes = str.encode(json.dumps(session_params))
        payload_bytes = gzip.compress(payload_bytes)
        start_session_request = bytearray(protocol.generate_header())
        start_session_request.extend(int(100).to_bytes(4, 'big'))
        start_session_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        start_session_request.extend(str.encode(self.session_id))
        start_session_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        start_session_request.extend(payload_bytes)
        await self.ws.send(start_session_request)
        logger.info("StartSession请求已发送")

    async def finish_session(self) -> None:
        """FinishSession - 客户端事件ID: 102"""
        finish_session_request = bytearray(protocol.generate_header())
        finish_session_request.extend(int(102).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        finish_session_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        finish_session_request.extend(str.encode(self.session_id))
        finish_session_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        finish_session_request.extend(payload_bytes)
        await self.ws.send(finish_session_request)

    async def finish_connection(self) -> None:
        """FinishConnection - 客户端事件ID: 2"""
        finish_connection_request = bytearray(protocol.generate_header())
        finish_connection_request.extend(int(2).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        finish_connection_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        finish_connection_request.extend(payload_bytes)
        await self.ws.send(finish_connection_request)
        logger.info("FinishConnection请求已发送")

    async def task_request(self, audio: bytes) -> None:
        """TaskRequest - 客户端事件ID: 200"""
        # 发送前检查SSL连接状态
        if self._is_websocket_closed():
            logger.warning("发送音频数据前检测到SSL连接已关闭")
            raise websockets.exceptions.ConnectionClosed(None, 1000, "SSL connection is closed")
        
        # 详细检查SSL socket状态
        if hasattr(self.ws, '_socket') and self.ws._socket:
            try:
                sock = self.ws._socket
                if hasattr(sock, 'fileno'):
                    sock.fileno()
                if hasattr(sock, 'getpeername'):
                    sock.getpeername()
                logger.debug("SSL socket状态检查通过")
            except (OSError, AttributeError, ConnectionResetError, BrokenPipeError) as e:
                logger.warning(f"SSL socket状态检查失败: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"SSL connection error: {e}")
        
        task_request = bytearray(
            protocol.generate_header(message_type=protocol.CLIENT_AUDIO_ONLY_REQUEST,
                                     serial_method=protocol.NO_SERIALIZATION))
        task_request.extend(int(200).to_bytes(4, 'big'))
        task_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        task_request.extend(str.encode(self.session_id))
        payload_bytes = gzip.compress(audio)
        task_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # payload size(4 bytes)
        task_request.extend(payload_bytes)
        await self.ws.send(task_request)

    async def say_hello(self, content: str) -> None:
        """SayHello - 客户端事件ID: 300"""
        hello_data = {
            "content": content
        }
        payload_bytes = str.encode(json.dumps(hello_data))
        payload_bytes = gzip.compress(payload_bytes)
        
        say_hello_request = bytearray(protocol.generate_header(message_type=0b0001, serial_method=0b0001))
        say_hello_request.extend(int(300).to_bytes(4, 'big'))
        say_hello_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        say_hello_request.extend(str.encode(self.session_id))
        say_hello_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        say_hello_request.extend(payload_bytes)
        await self.ws.send(say_hello_request)

    async def chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """ChatTTSText - 客户端事件ID: 500"""
        tts_data = {
            "start": start,
            "content": content,
            "end": end
        }
        payload_bytes = str.encode(json.dumps(tts_data))
        payload_bytes = gzip.compress(payload_bytes)
        
        chat_tts_request = bytearray(protocol.generate_header(message_type=0b0001, serial_method=0b0001))
        chat_tts_request.extend(int(500).to_bytes(4, 'big'))
        chat_tts_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        chat_tts_request.extend(str.encode(self.session_id))
        chat_tts_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        chat_tts_request.extend(payload_bytes)
        await self.ws.send(chat_tts_request)

    async def receive_server_response(self) -> Dict[str, Any]:
        """接收服务器响应"""
        async def _receive_with_lock():
            async with self.recv_lock:
                try:
                    # 详细检查连接状态
                    if not self.ws:
                        logger.warning("WebSocket连接对象为空")
                        raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is None")
                    
                    if self._is_websocket_closed():
                        logger.warning("WebSocket连接已关闭")
                        raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is closed")
                    
                    response = await self.ws.recv()
                    data = protocol.parse_response(response)
                    return data
                except websockets.exceptions.ConnectionClosed:
                    # 重新抛出连接关闭异常
                    raise
                except Exception as e:
                    if "SSL connection is closed" in str(e):
                        logger.error(f"SSL连接已关闭: {e}")
                        raise websockets.exceptions.ConnectionClosed(None, 1000, f"SSL connection is closed: {e}")
                    else:
                        raise Exception(f"接收消息失败: {e}")
        
        try:
            # 使用超时机制防止长时间阻塞
            return await asyncio.wait_for(_receive_with_lock(), timeout=10.0)
        except asyncio.TimeoutError:
            raise Exception("接收服务器响应超时")
    
    def _is_websocket_closed(self) -> bool:
        """检查WebSocket是否已关闭"""
        try:
            if self.ws is None:
                return True
            
            # 检查是否有state属性 (新版websockets)
            if hasattr(self.ws, 'state'):
                try:
                    from websockets.protocol import State
                    return self.ws.state != State.OPEN
                except ImportError:
                    pass
            
            # 检查是否有closed属性 (旧版websockets)
            if hasattr(self.ws, 'closed'):
                return self.ws.closed
            
            # 检查是否有open属性 (某些版本)
            if hasattr(self.ws, 'open'):
                return not self.ws.open
            
            # 检查是否有close_code属性，如果有且不为None，说明连接已关闭
            if hasattr(self.ws, 'close_code'):
                return self.ws.close_code is not None
            
            # 最后的兜底方案，假设连接未关闭
            return False
            
        except Exception as e:
            logger.debug(f"检查WebSocket关闭状态时出错: {e}")
            return True  # 出错时假设连接已关闭

    async def close(self) -> None:
        """关闭WebSocket连接"""
        if self.ws:
            try:
                logger.info("关闭WebSocket连接...")
                await self.ws.close()
                logger.info("WebSocket连接已关闭")
            except Exception as e:
                logger.warning(f"关闭WebSocket连接时出错: {e}")
            finally:
                # 强制清理连接对象
                self.ws = None
                logger.info("WebSocket连接对象已清理")