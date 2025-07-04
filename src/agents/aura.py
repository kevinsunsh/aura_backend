import json
import uuid
import logging
import asyncio
import requests
import gzip
import base64
import websockets
from pydantic import BaseModel
from enum import Enum
from typing import Optional, Callable, Any, Dict
from datetime import datetime
from fastapi import WebSocketDisconnect
# 配置相关
from config import settings

from .aura_memory.message_store import MessageStore
from .aura_memory.chat_stream import ChatStreamManager
from .message_processor_audio import MessageProcessorAudio
from .message_processor_text import MessageProcessorText
from .doubao_client import protocol
from .configuration import ServerEventEnum, ClientEventEnum
from .server_protocol import server_parse_request, server_generate_response
from utils.utils import performance_point_context

# 配置LangChain日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langchain")
logger.setLevel(logging.INFO)

class MessageType(Enum):
    """消息类型枚举"""
    TEXT = "text"
    AUDIO = "audio"
    UNSUPPORTED = "unsupported"

class AuraAgent:
    _instance = None
    @staticmethod
    def get_instance():
        if AuraAgent._instance is None:
            AuraAgent._instance = AuraAgent()
        return AuraAgent._instance
    
    def __init__(self):
        self.chat_stream = None
        
        # 统一使用postgresql驱动，禁用SSL以提高连接速度
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"  # 禁用SSL以提高连接速度
        )
        
        # 初始化数据库组件
        self.message_store = MessageStore(self.db_conn_string)
        self.chat_stream_manager = ChatStreamManager(self.db_conn_string)

        # WebSocket相关
        self.websocket_connection = None  # 存储WebSocket连接
        self.websocket_lock = asyncio.Lock()  # 用于同步访问WebSocket连接
        
        self.message_processor_text = MessageProcessorText(
            message_store=self.message_store,
            chat_stream_manager=self.chat_stream_manager,
            db_conn_string=self.db_conn_string,
            websocket_send_callback=self.send_websocket_message
        )
        self.message_processor_audio = MessageProcessorAudio(
            message_store=self.message_store,
            chat_stream_manager=self.chat_stream_manager,
            db_conn_string=self.db_conn_string,
            websocket_send_callback=self.send_websocket_message
        )
    
    async def send_websocket_message(self, message: dict):
        """发送WebSocket消息，使用统一的协议格式"""
        try:
            async with asyncio.timeout(5.0):  # 5秒超时
                async with self.websocket_lock:
                    if self.websocket_connection:
                        try:
                            # 使用统一的协议构造方法
                            binary_data = self._construct_protocol_message(message)
                            
                            # 兼容 FastAPI WebSocket (send_bytes) 和标准 websockets (send)
                            if hasattr(self.websocket_connection, 'send_bytes'):
                                await self.websocket_connection.send_bytes(binary_data)
                            else:
                                await self.websocket_connection.send(binary_data)
                                
                        except Exception as e:
                            logger.error(f"发送消息失败: {str(e)}")
                            # 标记连接为无效，但不在这里调用remove_websocket_connection避免死锁
                            self.websocket_connection = None
        except asyncio.TimeoutError:
            logger.error("获取websocket_lock超时，可能存在死锁")
        except Exception as e:
            logger.error(f"发送WebSocket消息时出错: {e}")

    def _construct_protocol_message(self, message: dict) -> bytes:
        """使用统一的协议构造方法"""
        try:
            # 获取事件ID
            event_id = message.get("event")
            
            # 获取payload数据
            payload_data = message.get("payload_msg", message)
            
            # 获取session_id
            session_id = getattr(self.chat_stream, 'chat_id', 'default') if self.chat_stream else 'default'
            
            # 处理音频数据
            if "audio_data" in payload_data and isinstance(payload_data["audio_data"], bytes):
                # 音频数据不需要JSON序列化，直接发送
                payload_bytes = payload_data["audio_data"]
                message_type = protocol.SERVER_ACK
                serial_method = protocol.NO_SERIALIZATION
                compression_type = protocol.GZIP
            else:
                # 其他数据使用JSON序列化，让server_generate_response处理序列化和压缩
                payload_bytes = payload_data
                message_type = protocol.SERVER_FULL_RESPONSE
                serial_method = protocol.JSON
                compression_type = protocol.GZIP
            
            # 使用统一的协议生成方法
            binary_data = server_generate_response(
                payload_data=payload_bytes,
                message_type=message_type,
                message_type_specific_flags=protocol.MSG_WITH_EVENT,
                serial_method=serial_method,
                compression_type=compression_type,
                event=event_id,
                session_id=session_id
            )
            
            return binary_data
            
        except Exception as e:
            logger.error(f"构造协议消息失败: {e}")
            # 降级到JSON发送
            return str.encode(json.dumps(message))

    # WebSocket连接管理方法
    async def set_websocket_connection(self, websocket):
        """设置WebSocket连接"""
        try:
            async with asyncio.timeout(5.0):  # 5秒超时
                async with self.websocket_lock:
                    self.websocket_connection = websocket
                    logger.info(f"用户已连接 WebSocket")
        except asyncio.TimeoutError:
            logger.error("获取websocket_lock超时，可能存在死锁")
            # 强制设置连接
            self.websocket_connection = websocket
            logger.info(f"强制设置WebSocket连接")
        except Exception as e:
            logger.error(f"设置WebSocket连接时出错: {e}")
            # 强制设置连接
            self.websocket_connection = websocket
    
    async def remove_websocket_connection(self):
        """移除WebSocket连接"""
        # 先获取锁，移除WebSocket连接，添加超时防止死锁
        try:
            async with asyncio.timeout(5.0):  # 5秒超时
                async with self.websocket_lock:
                    if self.websocket_connection:
                        self.websocket_connection = None
                        logger.info(f"用户已断开 WebSocket 连接")
        except asyncio.TimeoutError:
            logger.error("获取websocket_lock超时，可能存在死锁")
            # 强制重置连接
            self.websocket_connection = None
        except Exception as e:
            logger.error(f"移除WebSocket连接时出错: {e}")
            # 强制重置连接
            self.websocket_connection = None

        # 在锁外进行清理操作，避免死锁
        try:
            # 清理文本消息处理器
            if hasattr(self, 'message_processor_text'):
                await self.message_processor_text.cleanup()
            
            # 清理消息分发器
            if hasattr(self, 'message_processor_audio'):
                await self.message_processor_audio.cleanup()

            # 释放聊天流锁
            if hasattr(self, 'chat_stream') and self.chat_stream:
                try:
                    self.chat_stream_manager.release_lock(self.chat_stream.chat_id)
                    logger.info(f"已释放聊天流锁: {self.chat_stream.chat_id}")
                except Exception as e:
                    logger.error(f"释放聊天流锁时出错: {e}")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
    
    def _parse_binary_protocol_message(self, data: bytes) -> Dict[str, Any]:
        """使用统一的协议解析方法"""
        try:
            # 使用统一的协议解析函数
            result = server_parse_request(data)
            
            # 如果解析成功，添加额外的调试信息
            if 'error' not in result:
                logger.debug(f"协议解析成功: message_type={result.get('message_type')}, "
                           f"event={result.get('event')}, session_id={result.get('session_id')}")
            
            return result
                
        except Exception as e:
            logger.error(f"解析二进制协议消息失败: {e}")
            # 降级处理，返回空消息
            return {"error": f"解析失败: {str(e)}"}

    def _determine_message_type(self, message_data: Dict[str, Any]) -> MessageType:
        """确定消息类型 - 适配统一的协议解析格式"""
        # 检查是否有错误
        if "error" in message_data:
            return MessageType.UNSUPPORTED
            
        # 检查payload_msg中的内容
        payload_msg = message_data.get("payload_msg")
        if payload_msg:
            # 如果是字典类型（JSON序列化），检查其中的字段
            if isinstance(payload_msg, dict):
                if "message" in payload_msg and payload_msg["message"]:
                    return MessageType.TEXT
                elif "audio" in payload_msg and payload_msg["audio"]:
                    return MessageType.AUDIO
                elif "audio_data" in payload_msg and payload_msg["audio_data"]:
                    return MessageType.AUDIO
                elif "text" in payload_msg and payload_msg["text"]:
                    return MessageType.TEXT
            # 如果是字符串类型（JSON序列化），可能是文本消息
            elif isinstance(payload_msg, str) and payload_msg.strip():
                return MessageType.TEXT
            # 如果是字节类型（NO_SERIALIZATION），是音频数据
            elif isinstance(payload_msg, bytes) and len(payload_msg) > 0:
                return MessageType.AUDIO
                
        # 检查原始字段（向后兼容）
        if "message" in message_data and message_data["message"]:
            return MessageType.TEXT
        elif "audio" in message_data and message_data["audio"]:
            return MessageType.AUDIO
        elif "audio_data" in message_data and message_data["audio_data"]:
            return MessageType.AUDIO
            
        return MessageType.UNSUPPORTED

    def _is_websocket_closed(self, websocket) -> bool:
        """检查WebSocket是否已关闭，兼容不同版本的websockets库"""
        try:
            if websocket is None:
                logger.debug("WebSocket为None，认为已关闭")
                return True
            
            # 检查是否有state属性 (新版websockets)
            if hasattr(websocket, 'state'):
                try:
                    from websockets.protocol import State
                    current_state = websocket.state
                    is_closed = current_state != State.OPEN
                    logger.debug(f"WebSocket状态检查: state={current_state}, is_closed={is_closed}")
                    return is_closed
                except ImportError:
                    logger.debug("无法导入websockets.protocol.State，跳过state检查")
                    pass
                except Exception as e:
                    logger.debug(f"检查websocket.state时出错: {e}")
                    pass
            
            # 检查是否有closed属性 (某些版本websockets)
            if hasattr(websocket, 'closed'):
                is_closed = websocket.closed
                logger.debug(f"WebSocket closed属性检查: {is_closed}")
                return is_closed
            
            # 检查是否有open属性 (某些版本)
            if hasattr(websocket, 'open'):
                is_closed = not websocket.open
                logger.debug(f"WebSocket open属性检查: open={websocket.open}, is_closed={is_closed}")
                return is_closed
            
            # 检查是否有close_code属性，如果有且不为None，说明连接已关闭
            if hasattr(websocket, 'close_code'):
                close_code = websocket.close_code
                is_closed = close_code is not None
                logger.debug(f"WebSocket close_code检查: {close_code}, is_closed={is_closed}")
                return is_closed
            
            # 最后的兜底方案，假设连接未关闭
            logger.debug("WebSocket状态检查：使用兜底方案，假设连接未关闭")
            return False
            
        except Exception as e:
            logger.debug(f"检查WebSocket关闭状态时出错: {e}")
            return True  # 出错时假设连接已关闭

    async def handle_websocket_connection(self, websocket, chat_id: str):
        """处理WebSocket连接，包括连接和session生命周期管理"""
        await websocket.accept()
        await self.set_websocket_connection(websocket)
        
        try:
            # 第一步：等待客户端发送开始连接消息
            logger.info("等待客户端发送开始连接消息...")
            if not await self._wait_for_connection_start(websocket):
                logger.error("未收到有效的开始连接消息，关闭连接")
                return
            
            # 第二步：等待客户端发送开始session消息
            logger.info("等待客户端发送开始session消息...")
            if not await self._wait_for_session_start(websocket, chat_id):
                logger.error("未收到有效的开始session消息，关闭连接")
                return
            
            # 第三步：进入正常的消息处理循环
            logger.info(f"开始处理session消息: chat_id={chat_id}")
            await self._message_processing_loop(websocket)
            
            # 第四步：等待客户端发送session结束和连接结束消息
            await self._wait_for_graceful_shutdown(websocket)
                
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {str(e)}")
        finally:
            # 清理资源
            await self.remove_websocket_connection()
            await self.cleanup()

    async def _wait_for_connection_start(self, websocket) -> bool:
        """等待客户端发送开始连接消息"""
        try:
            # 直接尝试接收消息，如果连接有问题会抛出异常
            # 兼容 FastAPI WebSocket (receive) 和标准 websockets (recv)
            if hasattr(websocket, 'receive'):
                data = await websocket.receive()
                # FastAPI WebSocket 返回的是字典，需要提取数据
                if isinstance(data, dict):
                    if 'bytes' in data:
                        data = data['bytes']
                    elif 'text' in data:
                        data = data['text'].encode('utf-8')
                    else:
                        logger.error(f"未知的WebSocket消息格式: {data}")
                        return False
            else:
                data = await websocket.recv()
                
            message_data = self._parse_binary_protocol_message(data)
            
            if "error" in message_data:
                logger.error(f"解析连接开始消息失败: {message_data['error']}")
                return False
                
            # 检查是否是开始连接消息
            if message_data.get("event") == ClientEventEnum.StartConnection.value:
                logger.info("收到开始连接消息")
                # 发送连接确认
                await self.send_websocket_message({
                    "event": ServerEventEnum.ConnectionStarted.value,
                    "payload_msg": {"status": "connected", "message": "连接已建立"}
                })
                return True
            else:
                logger.error(f"期望收到start_connection消息，但收到: {message_data.get('action', 'unknown')}")
                return False
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket连接已关闭")
            return False
        except websockets.exceptions.ConnectionClosedError:
            logger.info("WebSocket连接异常关闭")
            return False
        except Exception as e:
            logger.error(f"等待连接开始消息时出错: {e}")
            return False

    async def _wait_for_session_start(self, websocket, chat_id: str) -> bool:
        """等待客户端发送开始session消息并初始化session"""
        try:
            # 直接尝试接收消息，如果连接有问题会抛出异常
            # 兼容 FastAPI WebSocket (receive) 和标准 websockets (recv)
            if hasattr(websocket, 'receive'):
                data = await websocket.receive()
                # FastAPI WebSocket 返回的是字典，需要提取数据
                if isinstance(data, dict):
                    if 'bytes' in data:
                        data = data['bytes']
                    elif 'text' in data:
                        data = data['text'].encode('utf-8')
                    else:
                        logger.error(f"未知的WebSocket消息格式: {data}")
                        return False
            else:
                data = await websocket.recv()
                
            message_data = self._parse_binary_protocol_message(data)
            
            if "error" in message_data:
                logger.error(f"解析session开始消息失败: {message_data['error']}")
                return False
                
            # 检查是否是开始session消息
            if message_data.get("event") == ClientEventEnum.StartSession.value:
                logger.info(f"收到开始session消息: chat_id={chat_id}")
                
                # 初始化聊天流和锁
                with performance_point_context("获取聊天流"):
                    self.chat_stream = self.chat_stream_manager.get_or_create_chat_stream(chat_id)
                with performance_point_context("聊天流加锁"):
                    locked = self.chat_stream_manager.acquire_lock(chat_id)
                    if not locked:
                        logger.warning(f"加锁失败: chat_id={chat_id}")
                        await self.send_websocket_message({
                            "event": ServerEventEnum.SessionFailed.value, 
                            "payload_msg": {"status": "failed", "message": "无法获取session锁"}
                        })
                        return False
                
                # 发送session确认
                await self.send_websocket_message({
                    "event": ServerEventEnum.SessionStarted.value,
                    "payload_msg": {"status": "started", "chat_id": chat_id, "message": "Session已开始"}
                })
                return True
            else:
                logger.error(f"期望收到StartSession事件，但收到: {message_data.get('event', 'unknown')}")
                return False
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket连接已关闭")
            return False
        except websockets.exceptions.ConnectionClosedError:
            logger.info("WebSocket连接异常关闭")
            return False
        except Exception as e:
            logger.error(f"等待session开始消息时出错: {e}")
            return False

    async def _message_processing_loop(self, websocket):
        """主要的消息处理循环"""
        while True:
            try:
                # 接收客户端消息（统一使用二进制协议）
                # 兼容 FastAPI WebSocket (receive) 和标准 websockets (recv)
                if hasattr(websocket, 'receive'):
                    data = await websocket.receive()
                    # FastAPI WebSocket 返回的是字典，需要提取数据
                    if isinstance(data, dict):
                        if 'bytes' in data:
                            data = data['bytes']
                        elif 'text' in data:
                            data = data['text'].encode('utf-8')
                        else:
                            logger.error(f"未知的WebSocket消息格式: {data}")
                            continue
                else:
                    data = await websocket.recv()
                
                # 解析二进制协议消息
                message_data = self._parse_binary_protocol_message(data)

                # 检查解析是否成功
                if "error" in message_data:
                    logger.error(f"消息解析失败: {message_data['error']}")
                    continue
                
                # 检查是否是结束session消息
                if message_data.get("event") == ClientEventEnum.FinishSession.value:
                    logger.info("收到结束session消息")
                    await self.send_websocket_message({
                        "event": ServerEventEnum.SessionFinished.value,
                        "payload_msg": {"status": "ended", "message": "Session已结束"}
                    })
                    break
                    
                logger.debug(f"收到二进制协议消息: event={message_data.get('event', 'unknown')}")

                message_type = self._determine_message_type(message_data)
                
                if message_type == MessageType.TEXT:
                    await self.message_processor_text.handle_text_message(message_data, self.chat_stream)
                elif message_type == MessageType.AUDIO:
                    if "audio_data" in message_data:
                        logger.debug(f"收到二进制音频消息: len={len(message_data['audio_data'])}")
                    await self.message_processor_audio.handle_audio_message(message_data, self.chat_stream)
                else:
                    logger.warning(f"不支持的消息类型: {message_type}")
            
            except WebSocketDisconnect:
                logger.info("WebSocket客户端主动断开连接")
                break
            except websockets.exceptions.ConnectionClosed:
                logger.info("WebSocket连接已关闭")
                break
            except websockets.exceptions.ConnectionClosedError:
                logger.info("WebSocket连接异常关闭")
                break
            except websockets.exceptions.ConnectionClosedOK:
                logger.info("WebSocket连接正常关闭")
                break
            except Exception as e:
                logger.error(f"处理WebSocket消息失败: {e}")
                # 检查是否是连接相关的错误
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                    logger.info("检测到连接断开相关错误，停止处理")
                    break
                # 其他错误继续处理
                continue

    async def _wait_for_graceful_shutdown(self, websocket):
        """等待客户端优雅关闭：先end_connection"""
        try:
            # 给客户端一些时间发送end_connection消息
            import asyncio
            try:
                # 兼容 FastAPI WebSocket (receive) 和标准 websockets (recv)
                if hasattr(websocket, 'receive'):
                    data = await asyncio.wait_for(websocket.receive(), timeout=5.0)
                    # FastAPI WebSocket 返回的是字典，需要提取数据
                    if isinstance(data, dict):
                        if 'bytes' in data:
                            data = data['bytes']
                        elif 'text' in data:
                            data = data['text'].encode('utf-8')
                        else:
                            logger.error(f"未知的WebSocket消息格式: {data}")
                            return
                else:
                    data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    
                message_data = self._parse_binary_protocol_message(data)
                
                if message_data.get("event") == ClientEventEnum.FinishConnection.value:
                    logger.info("收到结束连接消息")
                    await self.send_websocket_message({
                        "event": ServerEventEnum.ConnectionFinished.value,
                        "payload_msg": {"status": "ended", "message": "连接已结束"}
                    })
                else:
                    logger.warning(f"期望收到FinishConnection事件，但收到: {message_data.get('event', 'unknown')}")
                    
            except asyncio.TimeoutError:
                logger.info("等待结束连接消息超时，强制关闭")
            except Exception as e:
                logger.debug(f"等待结束连接消息时出错: {e}")
                
        except Exception as e:
            logger.debug(f"等待优雅关闭时出错: {e}")

    async def cleanup(self):
        """清理所有资源"""
        try:
            # 移除WebSocket连接（这里会自动清理消息处理器）
            await self.remove_websocket_connection()
            
            # 等待一小段时间确保所有异步任务都能正确结束
            import asyncio
            await asyncio.sleep(0.1)
            
            logger.info("AuraAgent 资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
