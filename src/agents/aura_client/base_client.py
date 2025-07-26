import ssl
from abc import ABC, abstractmethod
import asyncio
from loguru import logger
import threading
import websockets
from .config import *
from typing import Dict, Any
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response

class BaseClient(ABC):
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logid = ""
        self.chat_id = None
        self.user_id = None
        self.session_id = None
        self.ws = None
        self.recv_lock = asyncio.Lock()  # 防止并发recv调用
        self.is_running = False
        self.message_loop = None
    
    async def message_receive_loop(self):
        """服务器响应接收循环"""
        while True:
            # 尝试从客户端接收响应
            try:
                if self._is_websocket_closed():
                    await self.connect()
                if not self.is_running:
                    await self.connect()
                response = await self.receive_server_response()
                await self._handle_server_response(response)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                await self.connect()
    
    @abstractmethod
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
        pass

    async def start(self, chat_id: str, user_id: str) -> bool:
        """启动客户端，带重试机制"""
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.session_id = chat_id
                self.user_id = user_id
                self.chat_id = chat_id
                await self.connect()
                self.message_loop = asyncio.create_task(self.message_receive_loop())
                return True
            except Exception as e:
                logger.error(f"启动客户端失败（第{attempt}次）: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2)
                else:
                    return False
    
    async def connect(self) -> None:
        """建立WebSocket连接"""
        self.is_running = False
        logger.bind(tag="BASE").info(f"连接服务器: {self.config['base_url']}")
        self.ws = await websockets.connect(
            self.config['base_url'],
            additional_headers=self.config['headers'],
            open_timeout=20
        )
        
        # 执行连接握手
        await self.start_connection()
        response = await self.receive_server_response()
        if response.get("event") != ServerEvent.ConnectionStarted:
            logger.error(f"连接握手失败: {response}")
            raise Exception("连接握手失败")
        
        await self.start_session(
            payload_data = {
                "chat_info": {
                    "chat_id": self.chat_id,
                    "user_id": self.user_id
                }
            }
        )
        response = await self.receive_server_response()
        if response.get("event") != ServerEvent.SessionStarted:
            logger.error(f"会话握手失败: {response}")
            raise Exception("会话握手失败")
        logger.bind(tag="BASE").info(f"连接握手响应: {response}")
        
        # 新版本websockets不再提供获取响应头的方法
        self.logid = ""
        self.is_running = True
        logger.bind(tag="BASE").info(f"WebSocket连接已建立")
    
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

    async def start_session(self, payload_data: dict) -> None:
        """StartSession - 客户端事件ID: 100"""
        start_session_request = client_generate_request(
            payload_data=payload_data,
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
            response = await self.ws.recv()
            data = client_parse_response(response, skip_audio_decompression=True)
            return data
        except Exception as e:
            await self.connect()
        
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
            if self.message_loop:
                self.message_loop.cancel()
                self.message_loop = None
            self.is_running = False
            await self.finish_session()
            await self.finish_connection()
            await self.close()
        except Exception as e:
            logger.error(f"清理资源失败: {e}")
