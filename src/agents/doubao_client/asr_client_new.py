import asyncio
import datetime
import gzip
import json
import time
import uuid
import struct
import wave
from io import BytesIO
import logging
from typing import Dict, Any, Callable, Optional
from enum import Enum
from dataclasses import dataclass
import websockets
from utils.utils import start_performance_point, end_performance_point
from .doubao_config import asr_config
import fastrand

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

INVALID_AUDIO_FORMAT = 45000151
# 常量定义
DEFAULT_SAMPLE_RATE = 16000

class ProtocolVersion:
    V1 = 0b0001

class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111

class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011

class SerializationType:
    NO_SERIALIZATION = 0b0000
    JSON = 0b0001

class CompressionType:
    GZIP = 0b0001

class Config:
    def __init__(self):
        # 填入控制台获取的app id和access token
        self.auth = {
            "app_key": "4427555468",
            "access_key": "wo4mooD0lf3nNJlfNoYsnHzrx7Dl5jrl"
        }
    
    @property
    def app_key(self) -> str:
        return self.auth["app_key"]

    @property
    def access_key(self) -> str:
        return self.auth["access_key"]

config = Config()

class CommonUtils:
    @staticmethod
    def gzip_compress(data: bytes) -> bytes:
        return gzip.compress(data)

    @staticmethod
    def gzip_decompress(data: bytes) -> bytes:
        return gzip.decompress(data)

class AsrRequestHeader:
    def __init__(self):
        self.message_type = MessageType.CLIENT_FULL_REQUEST
        self.message_type_specific_flags = MessageTypeSpecificFlags.POS_SEQUENCE
        self.serialization_type = SerializationType.JSON
        self.compression_type = CompressionType.GZIP
        self.reserved_data = bytes([0x00])

    def with_message_type(self, message_type: int) -> 'AsrRequestHeader':
        self.message_type = message_type
        return self

    def with_message_type_specific_flags(self, flags: int) -> 'AsrRequestHeader':
        self.message_type_specific_flags = flags
        return self

    def with_serialization_type(self, serialization_type: int) -> 'AsrRequestHeader':
        self.serialization_type = serialization_type
        return self

    def with_compression_type(self, compression_type: int) -> 'AsrRequestHeader':
        self.compression_type = compression_type
        return self

    def with_reserved_data(self, reserved_data: bytes) -> 'AsrRequestHeader':
        self.reserved_data = reserved_data
        return self

    def to_bytes(self) -> bytes:
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)
        header.append((self.message_type << 4) | self.message_type_specific_flags)
        header.append((self.serialization_type << 4) | self.compression_type)
        header.extend(self.reserved_data)
        return bytes(header)

    @staticmethod
    def default_header() -> 'AsrRequestHeader':
        return AsrRequestHeader()

def _gen_log_id():
    """生成logID"""
    ts = int(time.time() * 1000)  # 毫秒时间戳
    r = fastrand.pcg32bounded(1 << 24) + (1 << 20)
    local_ip = "00000000000000000000000000000000"
    return f"02{ts}{local_ip}{r:08x}"
log_id = _gen_log_id()
class RequestBuilder:
    @staticmethod
    def new_auth_headers() -> Dict[str, str]:
        reqid = str(uuid.uuid4())
        logger.info(f"new_auth_headers log_id: {log_id}")
        return {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": config.access_key,
            "X-Api-App-Key": config.app_key,
            "X-Tt-Logid": log_id
        }

    @staticmethod
    def new_full_client_request(seq: int) -> bytes:  # 添加seq参数
        header = AsrRequestHeader.default_header() \
            .with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        
        payload = {
            "user": {
                "uid": "demo_uid"
            },
            "audio": {
                "format": "wav",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False
            }
        }
        
        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = CommonUtils.gzip_compress(payload_bytes)
        payload_size = len(compressed_payload)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))  # 使用传入的seq
        request.extend(struct.pack('>I', payload_size))
        request.extend(compressed_payload)
        
        return bytes(request)

    @staticmethod
    def new_audio_only_request(seq: int, segment: bytes, is_last: bool = False) -> bytes:
        header = AsrRequestHeader.default_header()
        if is_last:  # 最后一个包特殊处理
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
            seq = -seq  # 设为负值
        else:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        header.with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        
        compressed_segment = CommonUtils.gzip_compress(segment)
        request.extend(struct.pack('>I', len(compressed_segment)))
        request.extend(compressed_segment)
        
        return bytes(request)

class AsrResponse:
    def __init__(self):
        self.code = 0
        self.event = 0
        self.is_last_package = False
        self.payload_sequence = 0
        self.payload_size = 0
        self.payload_msg = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "event": self.event,
            "is_last_package": self.is_last_package,
            "payload_sequence": self.payload_sequence,
            "payload_size": self.payload_size,
            "payload_msg": self.payload_msg
        }

class ResponseParser:
    @staticmethod
    def parse_response(msg: bytes) -> AsrResponse:
        response = AsrResponse()
        
        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_type_specific_flags = msg[1] & 0x0f
        serialization_method = msg[2] >> 4
        message_compression = msg[2] & 0x0f
        
        payload = msg[header_size*4:]
        
        # 解析message_type_specific_flags
        if message_type_specific_flags & 0x01:
            response.payload_sequence = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            response.is_last_package = True
        if message_type_specific_flags & 0x04:
            response.event = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
            
        # 解析message_type
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            response.payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            response.code = struct.unpack('>i', payload[:4])[0]
            response.payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            
        if not payload:
            return response
            
        # 解压缩
        if message_compression == CompressionType.GZIP:
            try:
                payload = CommonUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        # 解析payload
        try:
            if serialization_method == SerializationType.JSON:
                response.payload_msg = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

class AsrClient:
    """ASR客户端，支持实时音频识别和断线重连"""
    
    def __init__(self, 
                 asr_start_callback: Callable[[], None] = None,
                 asr_response_callback: Callable[[str], None] = None,
                 asr_end_callback: Callable[[], None] = None,
                 uid: str = None,
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
        self.ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
        self.uid = uid

        # 回调函数
        self.asr_start_callback = asr_start_callback
        self.asr_response_callback = asr_response_callback
        self.asr_end_callback = asr_end_callback

        # 重连配置
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_interval = reconnect_interval
        self.reconnect_backoff_factor = reconnect_backoff_factor
        self.max_reconnect_interval = max_reconnect_interval
        
        # 连接状态
        self.ws = None
        self.is_running = False
        self.asr_started = False
        self.connection_lost = False  # 新增：标记连接是否丢失
        
        # 重连状态
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.should_reconnect = True
        self.reconnect_task = None
        self.seq = 1
        
        # 接收任务
        self.receive_task = None
        
        # 共享变量 - 会被更新的状态
        self.server_asr_result = ""  # 当前utterance文本
        
        # 发送队列和保活机制
        self.send_queue = None  # 发送队列，在连接时初始化
        self.asrend_task = None

        # 性能点
        self.asr_service_performance_point_id = None
                
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
        
        # 构建连接头
        header = RequestBuilder.new_auth_headers()
        
        # 建立WebSocket连接
        self.ws = await websockets.connect(
            self.ws_url, 
            additional_headers=header, 
            max_size=1000000000
        )
        
        self.is_running = True
        logger.info("ASR WebSocket连接已建立")
        
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

        # 发送初始请求
        await self._send_initial_request()
        
        # 重置重连状态
        if self.is_reconnecting:
            self.is_reconnecting = False
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval
            self.connection_lost = False  # 重连成功后重置连接丢失标志
    
    async def _send_initial_request(self):
        """发送初始请求"""
        request = RequestBuilder.new_full_client_request(self.seq)
        self.seq += 1  # 发送后递增
        try:
            await self.ws.send(request)
            logger.info(f"Sent full client request with seq: {self.seq-1}")
        except Exception as e:
            logger.error(f"Failed to send full client request: {e}")
            raise
    
    async def _send_wav_header(self):
        """发送WAV文件头"""
        # 构建一个标准的16kHz、16bit、单声道的WAV文件头
        wav_header = (
            b'RIFF' +
            (36).to_bytes(4, 'little') +  # ChunkSize: 36 + SubChunk2Size（此处先写36，后续音频数据长度为0）
            b'WAVE' +
            b'fmt ' +
            (16).to_bytes(4, 'little') +  # Subchunk1Size: 16 for PCM
            (1).to_bytes(2, 'little') +   # AudioFormat: 1 for PCM
            (1).to_bytes(2, 'little') +   # NumChannels: 1
            (16000).to_bytes(4, 'little') +  # SampleRate: 16000
            (16000 * 1).to_bytes(4, 'little') +  # ByteRate: SampleRate * NumChannels * BitsPerSample/8
            (1).to_bytes(2, 'little') +   # BlockAlign: NumChannels * BitsPerSample/8
            (16).to_bytes(2, 'little') +  # BitsPerSample: 16
            b'data' +
            (0).to_bytes(4, 'little')     # Subchunk2Size: 0（无音频数据）
        )
        request = RequestBuilder.new_audio_only_request(wav_header, self.seq)
        self.seq += 1  # 发送后递增
        try:
            await self.ws.send(request)
            logger.info(f"Sent wav header request with seq: {self.seq-1}")
        except Exception as e:
            logger.error(f"Failed to send wav header request: {e}")
            raise
    
    async def _receive_loop(self):
        """接收循环"""
        try:
            while self.is_running and self.ws:
                try:
                    # 检查WebSocket连接状态
                    if hasattr(self.ws, 'closed') and self.ws.closed:
                        logger.warning("ASR WebSocket连接已关闭，停止接收")
                        self._mark_disconnected()
                        break
                    
                    # logger.debug(f"开始接收新的ASR响应")
                    response = await self.ws.recv()
                    result = ResponseParser.parse_response(response)
                    await self._handle_response(result)
                    # logger.debug(f"接收新的ASR响应完成")
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
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止接收")
                        self._mark_disconnected()
                        break
                    # 其他错误继续处理
                    self._mark_disconnected()
                    break
                    
        except Exception as e:
            logger.error(f"ASR接收循环异常: {e}")
            self._mark_disconnected()
        finally:
            # 接收循环结束时，根据连接丢失状态决定是否重连
            if self.connection_lost and self.should_reconnect:
                logger.info("接收循环结束，检测到连接丢失，启动重连逻辑")
                # 在这里触发重连，避免在循环中创建新的接收任务
                asyncio.create_task(self._handle_disconnect())
            
            # 确保在接收循环结束时设置运行状态为False
            if self.is_running:
                self.is_running = False
    
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
    
    async def _handle_response(self, result: AsrResponse):
        """处理服务器响应"""
        # logger.debug(f"ASR响应: {result}")
        if result.event == 150:
            logger.info("连接成功")
            return
        if result.code == INVALID_AUDIO_FORMAT:
            logger.error("音频格式错误")
            return
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
                            # 直接处理所有收到的utterances（服务器现在只返回最新的分句）
                            for i, utterance in enumerate(utterances):
                                if isinstance(utterance, dict) and 'text' in utterance:
                                    # 检查definite属性，只有确定的分句才处理
                                    is_definite = utterance.get('definite', False)
                                    utterance_text = utterance['text'].strip()
                                    if len(utterance_text) > 0:  # 只有非空文本才处理
                                        # 如果是首次收到ASR包，标记会话已开始并触发ASRInfo事件
                                        asr_payload = {
                                                "results": [
                                                    {
                                                        "text": utterance_text,
                                                        "is_interim": is_definite
                                                    }
                                                ]
                                            }
                                        if not self.asr_started:
                                            self.asr_started = True
                                            if self.asr_service_performance_point_id is None:
                                                self.asr_service_performance_point_id = start_performance_point("ASR服务")
                                            await self._on_asr_info(asr_payload)
                                        await self._on_asr_response(asr_payload)
                                        if self.asrend_task is not None:
                                            self.asrend_task.cancel()
                                        self.asrend_task = asyncio.create_task(self._asrend_timer())
    
    async def _asrend_timer(self):
        try:
            await asyncio.sleep(0.3)
            # 300ms内没有新字，发送asrend消息
            if self.asr_started:
                asr_payload = {}
                await self._on_asr_ended(asr_payload)
                self.asr_started = False
        except asyncio.CancelledError:
            pass
    
    def _mark_disconnected(self):
        """标记连接已断开（同步方法，避免在接收循环中创建新任务）"""
        if self.is_running:
            logger.warning("标记ASR连接已断开")
            self.connection_lost = True  # 标记连接丢失，用于重连判断

    async def _handle_disconnect(self):
        """处理连接断开"""
        if self.is_reconnecting:
            logger.debug("重连已在进行中，跳过断开处理")
            return
            
        logger.warning("处理ASR连接断开")
        self.is_running = False
        
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
        self.seq = 1
        # 关闭WebSocket连接
        if self.ws:
            try:
                await self.ws.close()
                logger.debug("WebSocket连接已关闭")
            except Exception as e:
                logger.debug(f"关闭ASR WebSocket时出错: {e}")
            self.ws = None
    
    async def process_audio_chunk(self, audio_chunk: bytes):
        """处理音频块"""
        if not self.is_running or not self.ws:
            if self.is_reconnecting:
                logger.debug("ASR正在重连中，暂时无法处理音频")
            else:
                logger.warning("ASR连接未就绪，无法处理音频")
            return
        # logger.info(f"处理音频块: {len(audio_chunk)}")
        try:
            await self._send_audio_chunk_direct(audio_chunk)
        except Exception as e:
            logger.error(f"处理音频块失败: {e}")
            # 如果发送失败，可能是连接问题，触发重连
            if self.is_running:
                await self._handle_disconnect()
     
    async def _send_audio_chunk_direct(self, chunk: bytes):
        """直接发送音频块（底层方法）"""
        try:
            if not self.ws or not self.is_running:
                raise Exception("WebSocket连接不可用")
            request = RequestBuilder.new_audio_only_request(self.seq, chunk)
            self.seq += 1
            await self.ws.send(request)
            logger.info(f"发送音频块，大小: {len(chunk)}")
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
        current_time = time.time()
        
        return {
            "is_running": self.is_running,
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "current_reconnect_interval": self.current_reconnect_interval,
            "should_reconnect": self.should_reconnect
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
        
        # 重置所有状态
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.connection_lost = False
        
        logger.info("ASR客户端已清理")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.is_running and self.ws is not None
