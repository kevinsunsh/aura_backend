import ssl
import time
import fastrand
import websockets
from loguru import logger
from typing import Dict, Any
from .doubao_config import *
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response

class RealtimeDialogClient:
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self, config: Dict[str, Any], chat_id: str):
        self.config = config
        self.logid = ""
        self.chat_id = chat_id
        self.session_id = None
        self.ws = None

    def _gen_log_id(self):
        """生成logID"""
        ts = int(time.time() * 1000)  # 毫秒时间戳
        r = fastrand.pcg32bounded(1 << 24) + (1 << 20)
        local_ip = "00000000000000000000000000000000"
        return f"02{ts}{local_ip}{r:08x}"

    async def connect(self) -> None:
        """建立WebSocket连接"""
        logger.info(f"连接服务器: {self.config['base_url']}")
        headers = self.config['headers']
        headers['X-Tt-Logid'] = self.logid
        self.ws = await websockets.connect(
            self.config['base_url'],
            additional_headers=headers,
            ping_interval=5,        # 更频繁的 ping（原来是 120s）
            ping_timeout=3,         # 更短的超时（原来是 60s）
            close_timeout=2,        # 更短的关闭超时
            max_queue=1024,         # 增大队列（原来是 32）
            compression=None,        # 已禁用压缩
            max_size=1000000000,    # 保持大消息支持
        )
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

    async def start_session(self) -> None:
        """StartSession - 客户端事件ID: 100"""
        default_session_req["dialog"]["dialog_id"] = self.chat_id
        self.session_id = str(uuid.uuid4()).replace('-', '')
        start_session_request = client_generate_request(
            payload_data=default_session_req,
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
            # skip_audio_compression=True
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

    async def say_hello(self, content: str) -> None:
        """SayHello - 客户端事件ID: 300"""
        hello_data = {
            "content": content
        }

        say_hello_request = client_generate_request(
            payload_data=hello_data,
            message_type=CLIENT_FULL_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=JSON,
            compression_type=GZIP,
            event=ClientEvent.SayHello,
            session_id=self.session_id
        )
        try:
            await self.ws.send(say_hello_request)
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
                logger.warning(f"发送打招呼消息时检测到连接问题: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")
            else:
                # 重新抛出其他类型的异常
                raise

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

    async def receive_server_response(self) -> Dict[str, Any]:
        """接收服务器响应"""
        try:
            # 详细检查连接状态
            if not self.ws:
                logger.warning("WebSocket连接对象为空")
                raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is None")
            
            if self._is_websocket_closed():
                logger.warning("_is_websocket_closed WebSocket连接已关闭")
                raise websockets.exceptions.ConnectionClosed(None, 1000, "WebSocket connection is closed")
            
            response = await self.ws.recv()
            # data = client_parse_response(response, skip_audio_decompression=True)
            data = client_parse_response(response)
            return data
        except websockets.exceptions.ConnectionClosed:
            # 重新抛出连接关闭异常
            logger.warning(f"ConnectionClosed WebSocket连接已关闭 {self.logid}")
            raise
        except Exception as e:
            if "SSL connection is closed" in str(e):
                logger.error(f"SSL连接已关闭: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"SSL connection is closed: {e}")
            else:
                logger.warning(f"接收消息失败: {e} {self.logid}")
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