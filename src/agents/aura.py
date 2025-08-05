import json
import uuid
from loguru import logger
import asyncio
import requests
import gzip
import time
import websockets
from pydantic import BaseModel
from enum import Enum
from typing import Optional, Callable, Any, Dict
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
# 配置相关
from config import settings

from .agent_memory.chat_stream import ChatStreamManager
from .message_processor_audio import MessageProcessorAudio
from api_protocol.constant import *
from api_protocol.server_protocol import server_parse_request, server_generate_response

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
        # WebSocket相关
        self.websocket_connection = None  # 存储WebSocket连接
        self.last_message_time = time.time()
        self.session_prompt = ""
    
    async def send_websocket_message(self, message: dict):
        """发送WebSocket消息，使用统一的协议格式"""
        try:
            # async with self.websocket_lock: # 移除锁
            if self.websocket_connection:
                try:
                    # 使用统一的协议构造方法
                    logger.debug(f"发送消息: {message}")
                    binary_data = self._construct_protocol_message(message)
                    
                    # 兼容 FastAPI WebSocket (send_bytes) 和标准 websockets (send)
                    if hasattr(self.websocket_connection, 'send_bytes'):
                        await self.websocket_connection.send_bytes(binary_data)
                    else:
                        await self.websocket_connection.send(binary_data)
                    logger.debug(f"发送消息成功: {message.get('event')}")
                except Exception as e:
                    logger.error(f"发送消息失败: {str(e)}")
        except asyncio.TimeoutError:
            logger.error("send_websocket_message获取websocket_lock超时，可能存在死锁")
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
            skip_audio_compression = False
            if isinstance(payload_data, bytes):
                # 音频数据不需要JSON序列化，直接发送
                message_type = SERVER_ACK
                serial_method = NO_SERIALIZATION
                # skip_audio_compression = True
                compression_type = NO_COMPRESSION
            else:
                # 其他数据使用JSON序列化，让server_generate_response处理序列化和压缩
                message_type = SERVER_FULL_RESPONSE
                serial_method = JSON
                compression_type = GZIP
            
            # 使用统一的协议生成方法
            binary_data = server_generate_response(
                payload_data=payload_data,
                message_type=message_type,
                message_type_specific_flags=MSG_WITH_EVENT,
                serial_method=serial_method,
                compression_type=compression_type,
                event=event_id,
                session_id=session_id,
                skip_audio_compression=skip_audio_compression
            )
            
            return binary_data
            
        except Exception as e:
            logger.error(f"构造协议消息失败: {e}")

    async def remove_websocket_connection(self):
        """移除WebSocket连接"""
        try:
            await self.websocket_connection.close()
        except Exception as e:
            logger.error(f"关闭WebSocket连接时出错: {e}")
        # 清理消息分发器和聊天流锁
        try:
            await MessageProcessorAudio.get_instance().cleanup()
            logger.bind(tag="BASE").info("MessageProcessorAudio清理完成")
            if hasattr(self, 'chat_stream') and self.chat_stream:
                try:
                    ChatStreamManager.get_instance().release_lock(self.chat_stream.chat_id)
                    logger.bind(tag="BASE").info(f"已释放聊天流锁: {self.chat_stream.chat_id}")
                except Exception as e:
                    logger.error(f"释放聊天流锁时出错: {e}")
        except Exception as e:
            logger.error(f"remove_websocket_connection清理资源时出错: {e}")
    
    def _parse_binary_protocol_message(self, data: bytes) -> Dict[str, Any]:
        """使用统一的协议解析方法"""
        try:
            # 使用统一的协议解析函数
            # result = server_parse_request(data, skip_audio_decompression=True)
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
    
    async def handle_websocket_connection(self, websocket):
        """处理WebSocket连接，包括连接和session生命周期管理"""
        await websocket.accept()
        self.websocket_connection = websocket
        logger.bind(tag="BASE").info(f"WebSocket连接已设置")
        
        try:
            # 第一步：等待客户端发送开始连接消息
            logger.bind(tag="BASE").info("等待客户端发送开始连接消息...")
            if not await self._wait_for_connection_start(websocket):
                logger.error("未收到有效的开始连接消息，关闭连接")
                return
            
            # 第二步：等待客户端发送开始session消息
            logger.bind(tag="BASE").info("等待客户端发送开始session消息...")
            if not await self._wait_for_session_start(websocket):
                logger.error("未收到有效的开始session消息，关闭连接")
                return
            
            # 第三步：进入正常的消息处理循环
            logger.bind(tag="BASE").info(f"开始处理session消息")
            await self._message_processing_loop(websocket)
            
            # 第四步：等待客户端发送session结束和连接结束消息
            await self._wait_for_graceful_shutdown(websocket)
                
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {str(e)}")
        finally:
            # 清理资源
            await self.cleanup()

    async def _wait_for_connection_start(self, websocket) -> bool:
        """等待客户端发送开始连接消息"""
        try:
            # 直接尝试接收消息，如果连接有问题会抛出异常
            # 兼容 FastAPI WebSocket (receive) 和标准 websockets (recv)
            data = None
            if hasattr(websocket, 'receive'):
                data = await websocket.receive()
                # FastAPI WebSocket 返回的是字典，需要提取数据
                if isinstance(data, dict):
                    if 'bytes' in data:
                        data = data['bytes']
                    elif 'text' in data:
                        data = data['text'].encode('utf-8')
                    elif data.get('type') == 'websocket.disconnect':
                        logger.bind(tag="BASE").info(f"WebSocket连接断开: {data.get('reason', 'unknown')}")
                        return False
                    else:
                        logger.error(f"未知的WebSocket消息格式: {data}")
                        return False
            else:
                data = await websocket.recv()
            
            if data is None:
                return False
            
            message_data = self._parse_binary_protocol_message(data)
            
            if "error" in message_data:
                logger.error(f"解析连接开始消息失败: {message_data['error']}")
                return False
                
            # 检查是否是开始连接消息
            if message_data.get("event") == ClientEvent.StartConnection:
                logger.bind(tag="BASE").info("收到开始连接消息")
                # 发送连接确认
                await self.send_websocket_message({
                    "event": ServerEvent.ConnectionStarted,
                    "payload_msg": {}
                })
                return True
            else:
                logger.error(f"期望收到start_connection消息，但收到: {message_data.get('action', 'unknown')}")
                return False
                
        except websockets.exceptions.ConnectionClosed:
            logger.bind(tag="BASE").info("WebSocket连接已关闭")
            return False
        except Exception as e:
            logger.error(f"等待连接开始消息时出错: {e}")
            return False

    async def _wait_for_session_start(self, websocket) -> bool:
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
                    elif data.get('type') == 'websocket.disconnect':
                        logger.info(f"WebSocket连接断开: {data.get('reason', 'unknown')}")
                        return False
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
            if message_data.get("event") == ClientEvent.StartSession:
                chat_id = message_data.get("payload_msg", {}).get("chat_info", {}).get("chat_id", None)
                user_id = message_data.get("payload_msg", {}).get("chat_info", {}).get("user_id", None)
                self.session_prompt = message_data.get("payload_msg", {}).get("dialog", {}).get("system_role", "你是一个AI助手，性格温和友善，喜欢帮助朋友解决问题。") + "\n" + message_data.get("payload_msg", {}).get("dialog", {}).get("speaking_style", "说话风趣幽默有梗。")
                logger.bind(tag="BASE").info(f"收到开始session消息: session_prompt={self.session_prompt}")
                if chat_id is None or user_id is None:
                    logger.error(f"开始session消息中没有chat_id或user_id")
                    return False
                
                logger.info(f"收到开始session消息: chat_id={chat_id}")
                
                # 初始化聊天流和锁
                self.chat_stream = ChatStreamManager.get_instance().get_or_create_chat_stream(chat_id)
                locked = ChatStreamManager.get_instance().acquire_lock(chat_id)
                if not locked:
                    logger.warning(f"加锁失败: chat_id={chat_id}")
                    await self.send_websocket_message({
                        "event": ServerEvent.SessionFailed, 
                        "payload_msg": {"status": "failed", "message": "无法获取session锁"}
                    })
                    return False
                
                result = await MessageProcessorAudio.get_instance().start(chat_id, user_id, self.session_prompt, self.send_websocket_message)
                if result == False:
                    await self.send_websocket_message({
                        "event": ServerEvent.SessionFailed, 
                        "payload_msg": {"status": "failed", "message": "无法启动session"}
                    })
                    return False
                # 发送session确认
                await self.send_websocket_message({
                    "event": ServerEvent.SessionStarted,
                    "payload_msg": {"status": "started", "chat_id": chat_id, "message": "Session已开始"}
                })
                return True
            else:
                logger.error(f"期望收到StartSession事件，但收到: {message_data.get('event', 'unknown')}")
                return False
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket连接已关闭")
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
                        elif data.get('type') == 'websocket.disconnect':
                            logger.info(f"WebSocket连接断开: {data.get('reason', 'unknown')}")
                            return  # 直接退出循环
                        else:
                            logger.error(f"_message_processing_loop 未知的WebSocket消息格式: {data}")
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
                if message_data.get("event") == ClientEvent.FinishSession:
                    logger.info("收到结束session消息")
                    await self.send_websocket_message({
                        "event": ServerEvent.SessionFinished,
                        "payload_msg": {"status": "ended", "message": "Session已结束"}
                    })
                    break
                now = time.time()
                logger.debug(f"收到二进制协议消息: event={message_data.get('event', 'unknown')} {now - self.last_message_time}")
                self.last_message_time = now
                await MessageProcessorAudio.get_instance().handle_message(message_data)
            except WebSocketDisconnect:
                logger.info("WebSocket客户端主动断开连接")
                break
            except websockets.exceptions.ConnectionClosed:
                logger.info("WebSocket连接已关闭")
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
                
                if message_data.get("event") == ClientEvent.FinishConnection:
                    logger.info("收到结束连接消息")
                    await self.send_websocket_message({
                        "event": ServerEvent.ConnectionFinished,
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
            
            await asyncio.sleep(1)
            logger.info("AuraAgent 资源清理完成")
        except Exception as e:
            logger.error(f"AuraAgent清理资源时出错: {e}")
