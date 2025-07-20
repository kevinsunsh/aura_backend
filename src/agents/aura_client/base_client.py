import websockets
import gzip
import json
import asyncio
import logging
import ssl
from typing import Dict, Any

from .config import *
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response

logger = logging.getLogger(__name__)

class BaseClient:
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logid = ""
        self.session_id = None
        self.ws = None
        self.recv_lock = asyncio.Lock()  # 防止并发recv调用

    async def start(self, chat_id: str, user_id: str) -> None:
        """启动客户端"""
        self.session_id = chat_id
        try:
            await self.connect()
        except Exception as e:
            logger.error(f"启动客户端失败: {e}")
            raise e

    async def connect(self) -> None:
        """建立WebSocket连接"""
        logger.info(f"连接服务器: {self.config['base_url']}")
        self.ws = await websockets.connect(
            self.config['base_url'],
            additional_headers=self.config['headers'],
            open_timeout=5
        )
        
        # 执行连接握手
        await self.start_connection()
        response = await self.receive_server_response()
        if response.get("event") != ServerEvent.ConnectionStarted:
            logger.error(f"连接握手失败: {response}")
            raise Exception("连接握手失败")
        
        await self.start_session({})
        response = await self.receive_server_response()
        if response.get("event") != ServerEvent.SessionStarted:
            logger.error(f"会话握手失败: {response}")
            raise Exception("会话握手失败")
        logger.debug(f"连接握手响应: {response}")
        
        # 新版本websockets不再提供获取响应头的方法
        self.logid = ""
        logger.info(f"WebSocket连接已建立")
    
    async def start_connection(self) -> None:
        """StartConnection - 客户端事件ID: 1"""
        start_connection_request = client_generate_request(
            payload_data={},
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.StartConnection
        )
        try:
            await self.ws.send(start_connection_request)
            logger.info("StartConnection请求已发送")
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            logger.warning(f"发送StartConnection请求时检测到连接问题: {e}")
            raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")

    async def start_session(self, session_config: dict) -> None:
        """StartSession - 客户端事件ID: 100"""
        start_session_request = client_generate_request(
            payload_data=session_config,
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.StartSession,
            session_id=self.session_id
        )
        try:
            await self.ws.send(start_session_request)
            logger.info("StartSession请求已发送")
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            logger.warning(f"发送StartSession请求时检测到连接问题: {e}")
            raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")

    async def finish_session(self) -> None:
        """FinishSession - 客户端事件ID: 102"""
        finish_session_request = client_generate_request(
            payload_data={},
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.FinishSession,
            session_id=self.session_id
        )
        try:
            await self.ws.send(finish_session_request)
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            logger.warning(f"发送FinishSession请求时检测到连接问题: {e}")
            # 对于结束会话的请求，我们不需要重新抛出异常，因为连接可能已经关闭
            logger.info("FinishSession请求发送失败，但这是正常的（连接可能已关闭）")

    async def finish_connection(self) -> None:
        """FinishConnection - 客户端事件ID: 2"""
        finish_connection_request = client_generate_request(
            payload_data={},
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.FinishConnection
        )
        try:
            await self.ws.send(finish_connection_request)
            logger.info("FinishConnection请求已发送")
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            logger.warning(f"发送FinishConnection请求时检测到连接问题: {e}")
            # 对于结束连接的请求，我们不需要重新抛出异常，因为连接可能已经关闭
            logger.info("FinishConnection请求发送失败，但这是正常的（连接可能已关闭）")
    
    async def receive_server_response(self) -> Dict[str, Any]:
        """接收服务器响应"""
        try:
            # 详细检查连接状态
            if not self.ws:
                logger.warning("WebSocket连接对象为空")
                raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is None")
            
            if self._is_websocket_closed():
                logger.warning("WebSocket连接已关闭")
                raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is closed")
            
            response = await self.ws.recv()
            data = client_parse_response(response, skip_audio_decompression=True)
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
    
    async def cleanup(self) -> None:
        """清理资源"""
        try:
            await self.finish_session()
            response = await self.receive_server_response()
            logger.debug(f"会话结束握手响应: {response}")
            if response.get("event") != ServerEvent.SessionFinished:
                raise Exception("会话结束握手失败")

            await self.finish_connection()
            response = await self.receive_server_response()
            if response.get("event") != ServerEvent.ConnectionFinished:
                raise Exception("连接结束握手失败")
            await self.close()
        except Exception as e:
            logger.error(f"清理资源失败: {e}")
    
class AsrClient(BaseClient):
    """ASR客户端"""
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
    
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

class TtsClient(BaseClient):
    """TTS客户端"""
    def __init__(self, config: Dict[str, Any], session_id: str):
        super().__init__(config, session_id)
    
    async def chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """ChatTTSText - 客户端事件ID: 500"""
        tts_data = {
            "start": start,
            "content": content,
            "end": end
        }

        chat_tts_request = client_generate_request(
            payload_data=tts_data,
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.ChatTTSText,
            session_id=self.session_id
        )

        try:
            await self.ws.send(chat_tts_request)
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
                logger.warning(f"发送TTS文本时检测到连接问题: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")
            else:
                # 重新抛出其他类型的异常
                raise
