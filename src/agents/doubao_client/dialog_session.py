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

from .realtime_dialog_client import RealtimeDialogClient
from .config import ws_connect_config

logger = logging.getLogger(__name__)

@dataclass
class AudioConfig:
    """音频配置数据类"""
    format: str
    bit_size: int
    channels: int
    sample_rate: int
    chunk: int

class DialogSession:
    """对话会话管理类，集成RealtimeDialogClient和aura流式聊天"""
    def __init__(self, 
                 uid: str = None,
                 asr_start_callback: Callable[[], None] = None,
                 asr_response_callback: Callable[[str, bool], None] = None,
                 asr_end_callback: Callable[[str], None] = None,
                 tts_start_callback: Callable[[str], None] = None,
                 tts_response_callback: Callable[[bytes], None] = None,
                 tts_end_callback: Callable[[], None] = None,
                 chat_end_callback: Callable[[str], None] = None,
                 ):
        self.uid = uid or str(uuid.uuid4())
        self.session_id = self.uid
        self.client = RealtimeDialogClient(config=ws_connect_config, session_id=self.session_id)

        # 状态管理
        self.is_running = True
        self.is_session_finished = False
        
        # 重连状态管理
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 99
        self.reconnect_delay = 2.0  # 重连延迟秒数
        self.reconnect_start_time = None  # 重连开始时间
        
        # 服务器ASR结果
        self.server_asr_result = None
        self.asr_start_callback = asr_start_callback
        self.asr_response_callback = asr_response_callback
        self.asr_end_callback = asr_end_callback

        # 服务器TTS结果
        self.tts_start_callback = tts_start_callback
        self.tts_response_callback = tts_response_callback
        self.tts_end_callback = tts_end_callback

        # 服务器Chat结果
        self.server_chat_response = ""
        self.chat_end_callback = chat_end_callback

        # 延迟监控
        self.last_input_time = None
        self.first_audio_response_time = None
        self.latency_stats = {
            'total_requests': 0,
            'total_latency': 0.0,
            'min_latency': float('inf'),
            'max_latency': 0.0,
            'avg_latency': 0.0
        }
        
        # 任务管理
        self.server_receive_task = None
        self.is_tts_sentence_start = False
        
    def _update_latency_stats(self, latency: float) -> None:
        """更新延迟统计信息"""
        self.latency_stats['total_requests'] += 1
        self.latency_stats['total_latency'] += latency
        self.latency_stats['min_latency'] = min(self.latency_stats['min_latency'], latency)
        self.latency_stats['max_latency'] = max(self.latency_stats['max_latency'], latency)
        self.latency_stats['avg_latency'] = self.latency_stats['total_latency'] / self.latency_stats['total_requests']
    
    async def check_connection_and_reconnect(self) -> bool:
        """检查连接状态并在断线时尝试重连"""
        logger.debug(f"检查连接状态: is_reconnecting={self.is_reconnecting}, is_running={self.is_running}, is_session_finished={self.is_session_finished}")
        
        # 如果正在重连中，检查是否超时
        if self.is_reconnecting:
            if self.reconnect_start_time and time.time() - self.reconnect_start_time > 30:
                logger.error("重连超时（30秒），重置重连状态")
                self.is_reconnecting = False
                self.reconnect_start_time = None
                return False
            logger.debug("当前正在重连中，跳过连接检查")
            return False
            
        # 检查连接状态
        connection_ok = self.is_connected()
        logger.debug(f"连接状态检查结果: {connection_ok}")
        if connection_ok:
            # 连接正常，重置重连计数和状态
            if self.reconnect_attempts > 0:
                logger.info("连接已恢复正常，重置重连计数")
                self.reconnect_attempts = 0
                self.reconnect_start_time = None
            return True
        
        # 连接断开，尝试重连
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"已达到最大重连次数 ({self.max_reconnect_attempts})，停止重连")
            self.is_running = False
            return False
        
        logger.warning(f"检测到连接断开，开始第 {self.reconnect_attempts + 1} 次重连...")
        # 异步触发重连，不阻塞当前调用
        await self._trigger_reconnect()
        return False  # 返回False表示当前不可用，需要等待重连完成
    
    async def _reconnect(self) -> bool:
        """执行重连逻辑"""
        self.is_reconnecting = True
        self.reconnect_start_time = time.time()
        self.reconnect_attempts += 1
        
        try:
            # 等待重连延迟
            await asyncio.sleep(self.reconnect_delay)
            
            # 注意：不取消当前的接收任务，因为重连是由接收任务本身调用的
            # 取消自己会导致死锁
            
            # 关闭现有连接
            if self.client.ws:
                try:
                    await self.client.close()
                    logger.info("旧连接已关闭")
                except Exception as e:
                    logger.warning(f"关闭旧连接时出错: {e}")
                
                # 强制清理WebSocket对象
                self.client.ws = None
                logger.info("WebSocket对象已清理")
            
            # 确保旧连接完全关闭后再创建新连接
            await asyncio.sleep(0.1)
            
            # 创建新的客户端实例
            self.client = RealtimeDialogClient(config=ws_connect_config, session_id=self.session_id)
            
            # 重新连接
            await self.client.connect()

            # 执行连接握手
            await self.client.start_connection()
            if not await self.wait_for_server_response(50):  # ConnectionStarted
                raise Exception("重连时连接握手失败")
                
            await self.client.start_session()
            if not await self.wait_for_server_response(150):  # SessionStarted
                raise Exception("重连时会话握手失败")
            
            # 重连成功
            logger.info(f"重连成功，第 {self.reconnect_attempts} 次尝试")
            self.is_reconnecting = False
            self.reconnect_start_time = None
            self.is_session_finished = False  # 重置会话状态
            
            # 重置聊天响应缓冲区，避免数据混淆
            self.server_chat_response = ""
            self.server_asr_result = None
            
            # 检查并确保接收任务正常运行
            if self.server_receive_task and self.server_receive_task.done():
                logger.warning("检测到接收任务已结束，重新启动...")
                self.server_receive_task = asyncio.create_task(self._server_receive_loop())
            elif not self.server_receive_task:
                logger.warning("接收任务不存在，重新创建...")
                self.server_receive_task = asyncio.create_task(self._server_receive_loop())
            else:
                logger.info("重连成功，接收循环将继续运行")
            
            return True
            
        except Exception as e:
            logger.error(f"重连失败，第 {self.reconnect_attempts} 次尝试: {e}")
            self.is_reconnecting = False
            self.reconnect_start_time = None
            
            # 如果还有重连机会，返回False让调用者稍后再试
            if self.reconnect_attempts < self.max_reconnect_attempts:
                return False
            else:
                # 已达到最大重连次数，停止运行
                logger.error(f"已达到最大重连次数 ({self.max_reconnect_attempts})，停止运行")
                self.is_running = False
                return False
    
    def is_connection_healthy(self) -> bool:
        """检查连接是否健康"""
        try:
            return (not self.is_reconnecting and 
                    self.is_running and 
                    not self.is_session_finished and 
                    self.client.ws is not None and 
                    self._is_websocket_open())
        except Exception as e:
            logger.debug(f"检查连接健康状态时出错: {e}")
            return False

    async def wait_for_server_response(self, expected_event_id: int, timeout: float = 5.0) -> bool:
        """等待服务端特定响应 - 直接接收模式，避免循环依赖"""
        try:
            logger.info(f"等待事件ID {expected_event_id} 的响应...")
            
            # 直接循环接收消息，直到收到期望的响应或超时
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # 直接调用客户端的接收方法
                    response = await self.client.receive_server_response()
                    
                    # 检查是否是期望的响应
                    if response.get('event') == expected_event_id:
                        event_id = response.get("event", "unknown")
                        logger.info(f"📥 收到服务端响应: 事件ID={event_id}")
                        
                        status = response.get("status", "unknown")
                        message = response.get("message", "")
                        logger.info(f"✅ 事件{expected_event_id} 成功: {status} - {message}")
                        return True
                    else:
                        # 在重连过程中，只记录其他消息但不处理，避免干扰重连流程
                        if self.is_reconnecting:
                            logger.debug(f"重连过程中收到其他事件: {response.get('event')}，跳过处理")
                        else:
                            # 正常流程中处理其他消息
                            await self._handle_server_response(response)
                        
                except asyncio.TimeoutError:
                    # 单次接收超时，继续循环
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"WebSocket连接已关闭: {e}")
                    return False
                except websockets.exceptions.WebSocketException as e:
                    logger.warning(f"WebSocket异常: {e}")
                    await asyncio.sleep(0.1)
                    continue
                except Exception as e:
                    logger.warning(f"接收消息时出错: {e}")
                    # 短暂暂停后继续
                    await asyncio.sleep(0.1)
                    continue
            
            # 超时
            logger.error(f"❌ 等待事件ID {expected_event_id} 响应超时")
            return False
                
        except Exception as e:
            logger.error(f"❌ 等待服务端响应时出错: {e}")
            return False
    
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
        if event_id == 50:  # ConnectionStarted
            await self._on_connection_started(payload_msg)
        elif event_id == 51:  # ConnectionFailed
            await self._on_connection_failed(payload_msg)
        elif event_id == 52:  # ConnectionFinished
            await self._on_connection_finished(payload_msg)
        # Session类事件 (150-153)
        elif event_id == 150:  # SessionStarted
            await self._on_session_started(payload_msg)
        elif event_id == 152:  # SessionFinished
            await self._on_session_finished(payload_msg)
        elif event_id == 153:  # SessionFailed
            await self._on_session_failed(payload_msg)
        # TTS类事件 (350-359)
        elif event_id == 350:  # TTSSentenceStart
            # if payload_msg["tts_type"] in ["chat_tts_text", "default"]:
            if payload_msg["tts_type"] in ["chat_tts_text"]:
                await self._on_tts_sentence_start(payload_msg)
                self.is_tts_sentence_start = True
        elif event_id == 351:  # TTSSentenceEnd
            await self._on_tts_sentence_end(payload_msg)
            self.is_tts_sentence_start = False
        elif event_id == 352:  # TTSResponse
            if self.is_tts_sentence_start:
                await self._on_tts_response(payload_msg)
        elif event_id == 359:  # TTSEnded
            await self._on_tts_ended(payload_msg)
        # ASR类事件 (450-459)
        elif event_id == 450:  # ASRInfo
            await self._on_asr_info(payload_msg)
        elif event_id == 451:  # ASRResponse
            await self._on_asr_response(payload_msg)
        elif event_id == 459:  # ASREnded
            await self._on_asr_ended(payload_msg)
        # Chat类事件 (550-559)
        elif event_id == 550:  # ChatResponse
            await self._on_chat_response(payload_msg)
        elif event_id == 559:  # ChatEnded
            await self._on_chat_ended(payload_msg)
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
        self.is_session_finished = True

    async def _on_session_failed(self, payload: Dict[str, Any]) -> None:
        """会话失败事件回调"""
        error_msg = payload.get("error", "未知错误")
        logger.error(f"会话失败: {error_msg}")
        self.is_session_finished = True

    # TTS类事件回调方法
    async def _on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        tts_type = payload.get("tts_type", "")
        text = payload.get("text", "")
        logger.debug(f"TTS句子开始 - 类型: {tts_type}, 文本: {text[:50]}...")
        if self.tts_start_callback:
            try:
                if asyncio.iscoroutinefunction(self.tts_start_callback):
                    await self.tts_start_callback(text)
                else:
                    self.tts_start_callback(text)
            except Exception as e:
                logger.error(f"TTS开始回调执行失败: {e}")
    
    async def _on_tts_sentence_end(self, payload: Dict[str, Any]) -> None:
        """TTS句子结束事件回调"""
        logger.debug("TTS句子结束")
        if self.tts_end_callback:
            try:
                if asyncio.iscoroutinefunction(self.tts_end_callback):
                    await self.tts_end_callback()
                else:
                    self.tts_end_callback()
            except Exception as e:
                logger.error(f"TTS结束回调执行失败: {e}")

    async def _on_tts_response(self, payload: Dict[str, Any]) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        audio_data = payload if isinstance(payload, bytes) else b""
        logger.debug(f"收到TTS音频数据: {len(audio_data)} 字节")
        if self.tts_response_callback:
            try:
                if asyncio.iscoroutinefunction(self.tts_response_callback):
                    await self.tts_response_callback(audio_data)
                else:
                    self.tts_response_callback(audio_data)
            except Exception as e:
                logger.error(f"TTS响应回调执行失败: {e}")
    
    async def _on_tts_ended(self, payload: Dict[str, Any]) -> None:
        """TTS结束事件回调"""
        logger.info("TTS合成结束")
    
    # ASR类事件回调方法
    async def _on_asr_info(self, payload: Dict[str, Any]) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.info("ASR识别出首字")
        if self.asr_start_callback:
            try:
                if asyncio.iscoroutinefunction(self.asr_start_callback):
                    await self.asr_start_callback()
                else:
                    self.asr_start_callback()
            except Exception as e:
                logger.error(f"ASR开始回调执行失败: {e}")
    
    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        results = payload.get("results", [])
        if results:
            for result in results:
                text = result.get("text", "")
                is_interim = result.get("is_interim", False)
                logger.debug(f"ASR识别结果: {text} (临时: {is_interim})")
                
                self.server_asr_result = text
                
                # 调用ASR响应回调
                if self.asr_response_callback:
                    try:
                        if asyncio.iscoroutinefunction(self.asr_response_callback):
                            await self.asr_response_callback(text, is_interim)
                        else:
                            self.asr_response_callback(text, is_interim)
                    except Exception as e:
                        logger.error(f"ASR响应回调执行失败: {e}")
    
    async def _on_asr_ended(self, payload: Dict[str, Any]) -> None:
        """ASR结束事件回调"""
        logger.info(f"ASR识别结束 : {self.server_asr_result}")
        if self.asr_end_callback:
            try:
                if asyncio.iscoroutinefunction(self.asr_end_callback):
                    await self.asr_end_callback(self.server_asr_result)
                else:
                    self.asr_end_callback(self.server_asr_result)
            except Exception as e:
                logger.error(f"ASR结束回调执行失败: {e}")
    
    # Chat类事件回调方法
    async def _on_chat_response(self, payload: Dict[str, Any]) -> None:
        """聊天响应事件回调"""
        pass
        # content = payload.get("content", "")
        # logger.info(f"收到聊天响应: {content[:50]}...")
        
        # 缓冲服务器聊天响应
        # self.server_chat_response += content

    async def _on_chat_ended(self, payload: Dict[str, Any]) -> None:
        """聊天结束事件回调"""
        pass
        # logger.info("聊天响应结束")
        # if self.chat_end_callback:
        #     try:
        #         if asyncio.iscoroutinefunction(self.chat_end_callback):
        #             await self.chat_end_callback(self.server_chat_response)
        #         else:
        #             self.chat_end_callback(self.server_chat_response)
        #     except Exception as e:
        #         logger.error(f"聊天结束回调执行失败: {e}")
        #     # 重置聊天响应缓冲区
        #     self.server_chat_response = ""
    
    async def _server_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while self.is_running and not self.is_session_finished:
                try:
                    # 检查连接状态并尝试重连
                    if not await self.check_connection_and_reconnect():
                        # 如果正在重连中，等待重连完成
                        if self.is_reconnecting:
                            logger.debug("正在重连中，等待重连完成...")
                            await asyncio.sleep(0.5)
                        # 如果重连失败且不是因为正在重连中，则等待后重试
                        elif self.is_running:
                            logger.warning("连接检查失败，等待后重试...")
                            await asyncio.sleep(1.0)
                        continue
                    
                    # 尝试从ASR客户端接收响应
                    try:
                        asr_response = await self.client.receive_server_response()
                        await self._handle_server_response(asr_response)
                    except Exception as recv_error:
                        # 特别处理WebSocket并发接收错误
                        error_msg = str(recv_error).lower()
                        if "recv" in error_msg and ("already running" in error_msg or "cannot call" in error_msg):
                            logger.warning(f"检测到WebSocket并发接收问题: {recv_error}")
                            # 短暂暂停，让其他操作完成
                            await asyncio.sleep(0.1)
                            continue
                        elif "超时" in str(recv_error) or "timeout" in error_msg:
                            # 超时是正常情况，服务器没有消息时等待即可
                            logger.debug("服务器无消息，继续等待...")
                            continue
                        else:
                            # 重新抛出其他类型的错误
                            raise recv_error
                except websockets.exceptions.ConnectionClosed:
                    logger.info("服务器连接已关闭，尝试重连...")
                    # 不立即退出，让重连逻辑处理
                    reconnect_success = await self.check_connection_and_reconnect()
                    if not reconnect_success and not self.is_running:
                        logger.error("重连失败且系统已停止运行，退出接收循环")
                        break
                except Exception as e:
                    error_msg = str(e).lower()
                    logger.warning(f"服务器接收响应失败: {e}")
                    
                    # 特别处理并发recv错误
                    if ("recv" in error_msg and "already running" in error_msg) or "cannot call recv" in error_msg:
                        logger.info("检测到WebSocket并发接收问题，短暂暂停后重试...")
                        await asyncio.sleep(0.2)
                        continue
                    
                    # 如果是连接相关错误，尝试重连
                    if "connection" in error_msg or "websocket" in error_msg:
                        reconnect_success = await self.check_connection_and_reconnect()
                        if not reconnect_success and not self.is_running:
                            logger.error("重连失败且系统已停止运行，退出接收循环")
                            break
                
                await asyncio.sleep(0.01)  # 避免CPU过度使用
                
        except asyncio.CancelledError:
            logger.info("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息出现未预期错误: {e}")
            # 只有在出现严重错误时才停止运行
            if not self.is_reconnecting:
                self.is_running = False
    
    async def process_audio_input(self, audio_data: bytes) -> None:
        """处理音频输入"""
        try:
            # 检查连接状态并尝试重连
            if not await self.check_connection_and_reconnect():
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
            # 触发重连
            await self._trigger_reconnect()
            logger.info("已触发重连，音频数据将在重连后重试")
        except Exception as e:
            logger.error(f"发送音频数据失败: {e}")
            # 如果是连接相关错误，尝试重连
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["connection", "websocket", "ssl", "socket", "network"]):
                await self._trigger_reconnect()
                logger.info("已触发重连，音频数据将在重连后重试")
            else:
                # 其他类型的错误，记录但不重连
                logger.error(f"非连接相关错误，不进行重连: {e}")
    
    async def process_audio_chunk(self, audio_chunk: bytes) -> None:
        """处理音频块（兼容ASR客户端的接口）"""
        await self.process_audio_input(audio_chunk)
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False) -> None:
        """发送文本块到TTS（兼容TTS客户端的接口）"""
        await self.send_chat_tts_text(text, start, end)
    
    async def send_say_hello(self, content: str) -> None:
        """发送打招呼消息"""
        try:
            # 检查连接状态并尝试重连
            if not await self.check_connection_and_reconnect():
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
            if await self.check_connection_and_reconnect():
                # 重连成功，重试发送
                try:
                    await self.client.say_hello(content)
                    logger.info(f"重连后成功发送打招呼消息: {content}")
                except Exception as retry_e:
                    logger.error(f"重连后发送打招呼消息仍然失败: {retry_e}")
            else:
                logger.error("重连失败，无法发送打招呼消息")
        except Exception as e:
            logger.error(f"发送打招呼消息失败: {e}")
            # 如果是连接相关错误，尝试重连
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["connection", "websocket", "ssl", "socket", "network"]):
                if await self.check_connection_and_reconnect():
                    # 重连成功，重试发送
                    try:
                        await self.client.say_hello(content)
                        logger.info(f"重连后成功发送打招呼消息: {content}")
                    except Exception as retry_e:
                        logger.error(f"重连后发送打招呼消息仍然失败: {retry_e}")
            else:
                logger.error(f"非连接相关错误，不进行重连: {e}")
    
    async def send_chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """发送聊天TTS文本"""
        try:
            # 检查连接状态并尝试重连
            if not await self.check_connection_and_reconnect():
                logger.warning("连接检查失败，无法发送TTS文本")
                return
                
            await self.client.chat_tts_text(content, start, end)
            # logger.info(f"已发送TTS文本: {content[:50]}...")
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionResetError,
                BrokenPipeError) as e:
            logger.error(f"WebSocket连接相关错误: {e}")
            if await self.check_connection_and_reconnect():
                # 重连成功，重试发送
                try:
                    await self.client.chat_tts_text(content, start, end)
                    logger.info(f"重连后成功发送TTS文本: {content[:50]}...")
                except Exception as retry_e:
                    logger.error(f"重连后发送TTS文本仍然失败: {retry_e}")
            else:
                logger.error("重连失败，无法发送TTS文本")
        except Exception as e:
            logger.error(f"发送TTS文本失败: {e}")
            # 如果是连接相关错误，尝试重连
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["connection", "websocket", "ssl", "socket", "network"]):
                if await self.check_connection_and_reconnect():
                    # 重连成功，重试发送
                    try:
                        await self.client.chat_tts_text(content, start, end)
                        logger.info(f"重连后成功发送TTS文本: {content[:50]}...")
                    except Exception as retry_e:
                        logger.error(f"重连后发送TTS文本仍然失败: {retry_e}")
            else:
                logger.error(f"非连接相关错误，不进行重连: {e}")
    
    async def get_session_info(self) -> Dict[str, Any]:
        """获取会话信息"""
        return {
            "session_id": self.session_id,
            "is_running": self.is_running,
            "is_session_finished": self.is_session_finished,
            "is_connected": self.is_connected(),
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "latency_stats": self.latency_stats.copy(),
            "receive_task_running": self.is_receive_task_running(),
            "receive_task_exists": self.server_receive_task is not None,
            "receive_task_done": self.server_receive_task.done() if self.server_receive_task else None,
            "receive_task_cancelled": self.server_receive_task.cancelled() if self.server_receive_task else None
        }
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            return (self.is_running and 
                    not self.is_session_finished and 
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
                    return self.client.ws.state == State.OPEN
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
    
    def is_client_running(self) -> bool:
        """检查客户端是否正在运行"""
        return self.is_running
    
    def is_server_session_active(self) -> bool:
        """检查服务器会话是否活跃"""
        return not self.is_session_finished
    
    def is_receive_task_running(self) -> bool:
        """检查接收任务是否正在运行"""
        return (self.server_receive_task is not None and 
                not self.server_receive_task.done() and 
                not self.server_receive_task.cancelled())
    
    async def _trigger_reconnect(self) -> None:
        """触发重连"""
        if not self.is_reconnecting:
            logger.info("检测到连接问题，触发重连...")
            self.is_reconnecting = True
            self.reconnect_start_time = time.time()
            # 异步触发重连，不阻塞当前任务
            asyncio.create_task(self._reconnect())
        else:
            logger.debug("重连已在进行中，跳过重复触发")

    async def start(self) -> None:
        """启动对话会话"""
        try:
            logger.info(f"启动对话会话: {self.session_id}")
            await self.client.connect()
            
            # 执行连接握手
            await self.client.start_connection()
            if not await self.wait_for_server_response(50):  # ConnectionStarted
                raise Exception("连接握手失败")
                
            await self.client.start_session()
            if not await self.wait_for_server_response(150):  # SessionStarted
                raise Exception("会话握手失败")
            
            # 握手完成后启动服务器响应接收任务
            self.server_receive_task = asyncio.create_task(self._server_receive_loop())
            
        except Exception as e:
            logger.error(f"对话会话错误: {e}")

    async def cleanup(self) -> None:
        """清理资源"""
        try:
            # 取消任务
            if self.server_receive_task:
                self.server_receive_task.cancel()
            
            # 结束会话
            if not self.is_session_finished:
                await self.client.finish_session()
                while not self.is_session_finished:
                    await asyncio.sleep(0.1)

            self.is_tts_sentence_start = False
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
            
            logger.info(f"对话会话已清理: {self.session_id}")
            
        except Exception as e:
            logger.error(f"DoubaoClient清理资源时出错: {e}")

    def print_latency_summary(self) -> None:
        """打印延迟统计摘要"""
        if self.latency_stats['total_requests'] > 0:
            logger.info(f"=== 延迟统计摘要 ===")
            logger.info(f"总请求数: {self.latency_stats['total_requests']}")
            logger.info(f"平均延迟: {self.latency_stats['avg_latency']:.3f}秒")
            logger.info(f"最小延迟: {self.latency_stats['min_latency']:.3f}秒")
            logger.info(f"最大延迟: {self.latency_stats['max_latency']:.3f}秒")
            logger.info(f"总延迟: {self.latency_stats['total_latency']:.3f}秒")
        else:
            logger.info("没有延迟统计数据")

    def get_reconnect_status(self) -> Dict[str, Any]:
        """获取重连状态信息"""
        return {
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "reconnect_delay": self.reconnect_delay,
            "is_connected": self.is_connected(),
            "is_running": self.is_running,
            "is_session_finished": self.is_session_finished
        }
    
    async def force_reconnect(self) -> bool:
        """强制重连（忽略最大重连次数限制）"""
        if self.is_reconnecting:
            logger.warning("已有重连任务在进行中，忽略强制重连请求")
            return False
        
        logger.info("执行强制重连...")
        old_attempts = self.reconnect_attempts
        self.reconnect_attempts = 0  # 暂时重置计数以允许重连
        
        try:
            result = await self._reconnect()
            if not result:
                self.reconnect_attempts = old_attempts  # 恢复原计数
            return result
        except Exception as e:
            logger.error(f"强制重连失败: {e}")
            self.reconnect_attempts = old_attempts  # 恢复原计数
            return False 