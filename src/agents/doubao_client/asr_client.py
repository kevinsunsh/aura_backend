import asyncio
import datetime
import gzip
import json
import time
import uuid
import wave
from io import BytesIO
import logging
from typing import Dict, Any, Callable, Optional
import websockets

from .config import asr_config

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type:
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# Message Type Specific Flags
NO_SEQUENCE = 0b0000  # no check sequence
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
NEG_WITH_SEQUENCE = 0b0011
NEG_SEQUENCE_1 = 0b0011

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001

# Message Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001


def generate_header(
        message_type=FULL_CLIENT_REQUEST,
        message_type_specific_flags=NO_SEQUENCE,
        serial_method=JSON,
        compression_type=GZIP,
        reserved_data=0x00
):
    """生成协议头"""
    header = bytearray()
    header_size = 1
    header.append((PROTOCOL_VERSION << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
    return header


def generate_before_payload(sequence: int):
    """生成payload前的序列号"""
    before_payload = bytearray()
    before_payload.extend(sequence.to_bytes(4, 'big', signed=True))  # sequence
    return before_payload


def parse_response(res):
    """解析服务器响应"""
    protocol_version = res[0] >> 4
    header_size = res[0] & 0x0f
    message_type = res[1] >> 4
    message_type_specific_flags = res[1] & 0x0f
    serialization_method = res[2] >> 4
    message_compression = res[2] & 0x0f
    reserved = res[3]
    header_extensions = res[4:header_size * 4]
    payload = res[header_size * 4:]
    result = {
        'is_last_package': False,
    }
    payload_msg = None
    payload_size = 0
    if message_type_specific_flags & 0x01:
        # receive frame with sequence
        seq = int.from_bytes(payload[:4], "big", signed=True)
        result['payload_sequence'] = seq
        payload = payload[4:]

    if message_type_specific_flags & 0x02:
        # receive last package
        result['is_last_package'] = True

    if message_type == FULL_SERVER_RESPONSE:
        payload_size = int.from_bytes(payload[:4], "big", signed=True)
        payload_msg = payload[4:]
    elif message_type == SERVER_ACK:
        seq = int.from_bytes(payload[:4], "big", signed=True)
        result['seq'] = seq
        if len(payload) >= 8:
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]
    elif message_type == SERVER_ERROR_RESPONSE:
        code = int.from_bytes(payload[:4], "big", signed=False)
        result['code'] = code
        payload_size = int.from_bytes(payload[4:8], "big", signed=False)
        payload_msg = payload[8:]
    if payload_msg is None:
        return result
    if message_compression == GZIP:
        payload_msg = gzip.decompress(payload_msg)
    if serialization_method == JSON:
        payload_msg = json.loads(str(payload_msg, "utf-8"))
    elif serialization_method != NO_SERIALIZATION:
        payload_msg = str(payload_msg, "utf-8")
    result['payload_msg'] = payload_msg
    result['payload_size'] = payload_size
    return result


class AsrClient:
    """ASR客户端，支持实时音频识别和断线重连"""
    
    def __init__(self, 
                 asr_start_callback: Callable[[], None] = None,
                 asr_response_callback: Callable[[str], None] = None,
                 asr_end_callback: Callable[[], None] = None,
                 asr_reconnect_callback: Callable[[], None] = None,
                 asr_disconnect_callback: Callable[[], None] = None,
                 max_reconnect_attempts: int = 5,
                 reconnect_interval: float = 2.0,
                 reconnect_backoff_factor: float = 1.5,
                 max_reconnect_interval: float = 30.0,
                 **kwargs):
        """
        初始化ASR客户端
        :param asr_start_callback: ASR开始回调
        :param asr_response_callback: ASR响应回调，参数为识别结果文本
        :param asr_end_callback: ASR结束回调
        :param asr_reconnect_callback: 重连成功回调
        :param asr_disconnect_callback: 连接断开回调
        :param max_reconnect_attempts: 最大重连尝试次数，0表示无限重连
        :param reconnect_interval: 重连间隔（秒）
        :param reconnect_backoff_factor: 重连间隔指数退避因子
        :param max_reconnect_interval: 最大重连间隔（秒）
        """
        # 使用配置文件中的设置，也可以通过kwargs覆盖
        self.ws_url = kwargs.get("ws_url", asr_config["ws_url"])
        self.uid = kwargs.get("uid", asr_config["uid"])
        self.format = kwargs.get("format", asr_config["audio"]["format"])
        self.rate = kwargs.get("rate", asr_config["audio"]["sample_rate"])
        self.bits = kwargs.get("bits", asr_config["audio"]["bits"])
        self.channel = kwargs.get("channel", asr_config["audio"]["channel"])
        self.codec = kwargs.get("codec", asr_config["audio"]["codec"])
        self.seg_duration = kwargs.get("seg_duration", asr_config["seg_duration"])
        self.headers = kwargs.get("headers", asr_config["headers"])
        
        # 回调函数
        self.asr_start_callback = asr_start_callback
        self.asr_response_callback = asr_response_callback
        self.asr_end_callback = asr_end_callback
        self.asr_reconnect_callback = asr_reconnect_callback
        self.asr_disconnect_callback = asr_disconnect_callback
        
        # 重连配置
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_interval = reconnect_interval
        self.reconnect_backoff_factor = reconnect_backoff_factor
        self.max_reconnect_interval = max_reconnect_interval
        
        # 连接状态
        self.ws = None
        self.is_running = False
        self.session_started = False
        self.seq = 1
        self.reqid = None
        
        # 重连状态
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.should_reconnect = True
        self.reconnect_task = None
        
        # 接收任务
        self.receive_task = None
        
        # 音频缓冲
        self.audio_buffer = bytearray()
        self.buffer_lock = asyncio.Lock()
        
        # utterances计数器，用于跟踪已处理的utterance数量
        self.processed_utterances_count = 0
        
    def construct_request(self):
        """构造初始请求"""
        req = {
            "user": {
                "uid": self.uid,
            },
            "audio": {
                'format': self.format,
                "sample_rate": self.rate,
                "bits": self.bits,
                "channel": self.channel,
                "codec": self.codec,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                "show_utterances": True
            }
        }
        return req
        
    async def start(self):
        """启动ASR连接"""
        if self.is_running:
            return
            
        try:
            await self._connect()
            
        except Exception as e:
            logger.error(f"启动ASR连接失败: {e}")
            self.is_running = False
            # 如果初始连接失败，也尝试重连
            if self.should_reconnect:
                await self._handle_reconnect()
            raise
            
    async def _connect(self):
        """建立WebSocket连接"""
        logger.info(f"连接ASR服务: {self.ws_url}")
        
        # 在建立新连接前，确保旧连接已完全清理
        await self._cleanup_connection()
        
        self.reqid = str(uuid.uuid4())
        
        # 构建连接头
        header = self.headers.copy()
        header["X-Api-Connect-Id"] = self.reqid
        
        # 建立WebSocket连接
        self.ws = await websockets.connect(
            self.ws_url, 
            additional_headers=header, 
            max_size=1000000000,
            ping_interval=30,  # 添加心跳检测
            ping_timeout=10
        )
        
        self.is_running = True
        logger.info("ASR WebSocket连接已建立")
        
        # 重置utterances计数器（新会话开始）
        self.processed_utterances_count = 0
        logger.debug("已重置utterances计数器")
        
        # 发送初始请求
        await self._send_initial_request()
        
        # 启动接收任务 - 确保没有旧任务在运行
        if self.receive_task and not self.receive_task.done():
            logger.warning("发现未完成的旧接收任务，正在取消...")
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass
        
        self.receive_task = asyncio.create_task(self._receive_loop())
        logger.debug("已启动新的接收任务")
        
        # 重置重连状态
        if self.is_reconnecting:
            self.is_reconnecting = False
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval
            logger.info("ASR重连成功")
            if self.asr_reconnect_callback:
                try:
                    await self.asr_reconnect_callback()
                except Exception as e:
                    logger.error(f"执行重连回调失败: {e}")

    async def _send_initial_request(self):
        """发送初始请求"""
        request_params = self.construct_request()
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        
        full_client_request = bytearray(generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(generate_before_payload(sequence=self.seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)
        
        await self.ws.send(full_client_request)
        logger.info("ASR初始请求已发送")
        
    async def _receive_loop(self):
        """接收循环"""
        try:
            while self.is_running and self.ws:
                try:
                    response = await self.ws.recv()
                    result = parse_response(response)
                    await self._handle_response(result)
                    
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("ASR WebSocket连接已关闭")
                    self._mark_disconnected()
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.warning("ASR WebSocket连接异常关闭")
                    self._mark_disconnected()
                    break
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("ASR WebSocket连接正常关闭")
                    break
                except Exception as e:
                    logger.error(f"接收ASR响应失败: {e}")
                    self._mark_disconnected()
                    break
                    
        except Exception as e:
            logger.error(f"ASR接收循环异常: {e}")
            self._mark_disconnected()
        finally:
            # 接收循环结束时，如果需要重连，启动重连逻辑
            if self.is_running and self.should_reconnect:
                logger.info("接收循环结束，启动重连逻辑")
                # 在这里触发重连，避免在循环中创建新的接收任务
                asyncio.create_task(self._handle_disconnect())
            elif self.is_running:
                self.is_running = False
                
    async def _handle_response(self, result: Dict[str, Any]):
        """处理服务器响应"""
        logger.debug(f"ASR响应: {result}")
        
        # 如果是首次响应，标记会话已开始
        if not self.session_started:
            self.session_started = True
            if self.asr_start_callback:
                await self.asr_start_callback()
                
        # 处理ASR结果
        if 'payload_msg' in result and result['payload_msg']:
            payload = result['payload_msg']
            # logger.info(f"ASR payload: {payload}")
            
            # 检查是否有识别结果
            if isinstance(payload, dict):
                # 检查是否有result字段（包含识别文本）
                if 'result' in payload and payload['result']:
                    asr_result = payload['result']
                    
                    # 处理utterances，只处理新增的utterance
                    if isinstance(asr_result, dict) and 'utterances' in asr_result:
                        utterances = asr_result['utterances']
                        if isinstance(utterances, list):
                            current_utterances_count = len(utterances)
                            
                            # 只处理新增的utterances
                            if current_utterances_count > self.processed_utterances_count:
                                logger.debug(f"检测到新utterances: 当前{current_utterances_count}个，已处理{self.processed_utterances_count}个")
                                
                                # 处理从已处理数量开始的新utterances
                                for i in range(self.processed_utterances_count, current_utterances_count):
                                    utterance = utterances[i]
                                    if isinstance(utterance, dict) and 'text' in utterance:
                                        utterance_text = utterance['text'].strip()
                                        if utterance_text and self.asr_response_callback:  # 只有非空文本才处理
                                            logger.info(f"ASR 新utterance结果 [{i+1}]: {utterance_text}")
                                            await self.asr_response_callback(utterance_text)
                                
                                # 更新已处理的utterances数量
                                self.processed_utterances_count = current_utterances_count
                                logger.debug(f"已更新utterances计数器: {self.processed_utterances_count}")
                    
                    # # 处理完整文本（作为备用，如果没有utterances）
                    # elif isinstance(asr_result, dict) and 'text' in asr_result:
                    #     final_text = asr_result['text']
                    #     if final_text and self.asr_response_callback:  # 只有非空文本才处理
                    #         logger.info(f"ASR完整识别结果: {final_text}")
                    #         await self.asr_response_callback(final_text)
                            
                    # # 如果是最后一个包，调用结束回调
                    # if result.get('is_last_package', False) and self.asr_end_callback:
                    #     # 传递完整的文本给结束回调
                    #     final_text = asr_result.get('text', '') if isinstance(asr_result, dict) else ''
                    #     await self.asr_end_callback(final_text)
                                
                # 检查是否有错误码
                if 'code' in payload:
                    code = payload['code']
                    if code != 1000:  # 1000 是成功码
                        message = payload.get('message', '未知错误')
                        logger.error(f"ASR服务返回错误: code={code}, message={message}")
                        
        # 处理错误响应
        if 'code' in result:
            error_code = result['code']
            logger.error(f"ASR连接错误: code={error_code}")
            
        # 检查是否是最后一个包
        if result.get('is_last_package', False):
            logger.info("收到ASR最后响应包")
                                
    def _mark_disconnected(self):
        """标记连接已断开（同步方法，避免在接收循环中创建新任务）"""
        if self.is_running:
            logger.warning("标记ASR连接已断开")
            self.is_running = False

    async def _handle_disconnect(self):
        """处理连接断开"""
        if self.is_reconnecting:
            logger.debug("重连已在进行中，跳过断开处理")
            return
            
        logger.warning("处理ASR连接断开")
        self.is_running = False
        
        # 调用断开连接回调
        if self.asr_disconnect_callback:
            try:
                await self.asr_disconnect_callback()
            except Exception as e:
                logger.error(f"执行断开连接回调失败: {e}")
        
        # 如果应该重连，启动重连逻辑
        if self.should_reconnect:
            await self._handle_reconnect()
            
    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if self.is_reconnecting:
            return
            
        self.is_reconnecting = True
        
        # 如果有重连任务在运行，先取消
        if self.reconnect_task:
            self.reconnect_task.cancel()
            
        self.reconnect_task = asyncio.create_task(self._reconnect_loop())
        
    async def _reconnect_loop(self):
        """重连循环"""
        while self.should_reconnect and (
            self.max_reconnect_attempts == 0 or 
            self.reconnect_attempts < self.max_reconnect_attempts
        ):
            self.reconnect_attempts += 1
            
            logger.info(f"尝试ASR重连 ({self.reconnect_attempts}/{self.max_reconnect_attempts if self.max_reconnect_attempts > 0 else '∞'})")
            
            try:
                # 等待重连间隔
                await asyncio.sleep(self.current_reconnect_interval)
                
                # 清理之前的连接
                await self._cleanup_connection()
                
                # 尝试重连
                await self._connect()
                
                # 重连成功，退出循环
                logger.info("ASR重连成功")
                return
                
            except Exception as e:
                logger.error(f"ASR重连失败: {e}")
                
                # 增加重连间隔（指数退避）
                self.current_reconnect_interval = min(
                    self.current_reconnect_interval * self.reconnect_backoff_factor,
                    self.max_reconnect_interval
                )
                
        # 重连失败
        if self.should_reconnect:
            logger.error(f"ASR重连达到最大尝试次数 ({self.max_reconnect_attempts})，停止重连")
            self.is_reconnecting = False
            
    async def _cleanup_connection(self):
        """清理连接相关资源（不重置重连状态）"""
        # 取消并等待接收任务完成
        if self.receive_task and not self.receive_task.done():
            logger.debug("取消接收任务...")
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                logger.debug("接收任务已取消")
            except Exception as e:
                logger.error(f"等待接收任务结束时出错: {e}")
        self.receive_task = None
        
        # 关闭WebSocket连接
        if self.ws:
            try:
                await self.ws.close()
                logger.debug("WebSocket连接已关闭")
            except Exception as e:
                logger.debug(f"关闭ASR WebSocket时出错: {e}")
            self.ws = None
            
        # 重置会话相关状态
        self.session_started = False
        self.seq = 1
        # 注意：不重置 processed_utterances_count，除非是完全清理

    async def process_audio_chunk(self, audio_chunk: bytes):
        """处理音频块"""
        if not self.is_running or not self.ws:
            if self.is_reconnecting:
                logger.debug("ASR正在重连中，暂时无法处理音频")
            else:
                logger.warning("ASR连接未就绪，无法处理音频")
            return
            
        try:
            async with self.buffer_lock:
                self.audio_buffer.extend(audio_chunk)
                
                # 计算分片大小（PCM格式：采样率 * 通道数 * 位深/8 * 时长）
                segment_size = int(self.rate * self.channel * (self.bits // 8) * self.seg_duration / 1000)
                
                # 如果缓冲区足够大，发送数据
                while len(self.audio_buffer) >= segment_size:
                    chunk_to_send = bytes(self.audio_buffer[:segment_size])
                    self.audio_buffer = self.audio_buffer[segment_size:]
                    
                    await self._send_audio_chunk(chunk_to_send, last=False)
                    
        except Exception as e:
            logger.error(f"处理音频块失败: {e}")
            # 如果发送失败，可能是连接问题，触发重连
            if self.is_running:
                await self._handle_disconnect()
            
    async def finish_audio(self):
        """结束音频输入"""
        if not self.is_running or not self.ws:
            return
            
        try:
            async with self.buffer_lock:
                # 发送剩余的音频数据
                if len(self.audio_buffer) > 0:
                    remaining_chunk = bytes(self.audio_buffer)
                    self.audio_buffer.clear()
                    await self._send_audio_chunk(remaining_chunk, last=True)
                else:
                    # 发送空的最后包
                    await self._send_audio_chunk(b'', last=True)
                    
        except Exception as e:
            logger.error(f"结束音频输入失败: {e}")
            if self.is_running:
                await self._handle_disconnect()
            
    async def _send_audio_chunk(self, chunk: bytes, last: bool = False):
        """发送音频块"""
        try:
            if not self.ws or not self.is_running:
                raise Exception("WebSocket连接不可用")
                
            self.seq += 1
            if last:
                self.seq = -self.seq
                
            payload_bytes = gzip.compress(chunk)
            
            if last:
                audio_request = bytearray(generate_header(
                    message_type=AUDIO_ONLY_REQUEST, 
                    message_type_specific_flags=NEG_WITH_SEQUENCE
                ))
            else:
                audio_request = bytearray(generate_header(
                    message_type=AUDIO_ONLY_REQUEST, 
                    message_type_specific_flags=POS_SEQUENCE
                ))
                
            audio_request.extend(generate_before_payload(sequence=self.seq))
            audio_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            audio_request.extend(payload_bytes)
            
            await self.ws.send(audio_request)
            logger.debug(f"发送音频块，序号: {self.seq}, 大小: {len(chunk)}, 最后: {last}")
            
        except Exception as e:
            logger.error(f"发送音频块失败: {e}")
            raise
            
    def stop_reconnect(self):
        """停止自动重连"""
        self.should_reconnect = False
        if self.reconnect_task:
            self.reconnect_task.cancel()
            
    def enable_reconnect(self):
        """启用自动重连"""
        self.should_reconnect = True
        
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态信息"""
        return {
            "is_running": self.is_running,
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "current_reconnect_interval": self.current_reconnect_interval,
            "should_reconnect": self.should_reconnect,
            "session_started": self.session_started
        }
            
    async def cleanup(self):
        """清理资源"""
        logger.info("开始清理ASR客户端资源")
        
        # 停止重连
        self.stop_reconnect()
        
        # 停止运行
        self.is_running = False
        
        # 取消重连任务
        if self.reconnect_task:
            self.reconnect_task.cancel()
            try:
                await self.reconnect_task
            except asyncio.CancelledError:
                pass
            self.reconnect_task = None
        
        # 清理连接
        await self._cleanup_connection()
        
        # 重置所有状态（包括utterances计数器）
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.processed_utterances_count = 0  # 完全清理时重置计数器
        
        logger.info("ASR客户端已清理") 