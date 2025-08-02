import asyncio
import datetime
import collections
import gzip
import json
import time
import uuid
import struct
import wave
from io import BytesIO
from loguru import logger
from typing import Dict, Any, Callable, Optional
from enum import Enum
from dataclasses import dataclass
import websockets
from utils.utils import start_performance_point, end_performance_point
from .doubao_config import asr_config
import fastrand
from api_protocol.constant import *

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
            "app_key": "4522921771",
            "access_key": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H"
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
                "uid": str(uuid.uuid4())
            },
            "audio": {
                "format": "pcm",
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
                "show_utterances": False,
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
                 on_asr_info: Callable[[], None] = None,
                 on_asr_response: Callable[[str], None] = None,
                 on_asr_ended: Callable[[], None] = None,
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
        self.uid = str(uuid.uuid4())

        # 回调函数
        self._on_asr_info = on_asr_info
        self._on_asr_response = on_asr_response
        self._on_asr_ended = on_asr_ended

        # 连接状态
        self.ws = None
        self.is_speaking = False
        self.is_running = False
        self.seq = 1
        self.seq_lock = asyncio.Lock()
        # 接收任务
        self.receive_task = None
        
        # 共享变量 - 会被更新的状态
        self.server_asr_result = ""  # 当前utterance文本
        self.audio_queue = collections.deque(maxlen=2)

        # 是否识别出首字
        self.is_asr_info = False
    
    async def start(self):
        """启动ASR连接"""
        if self.is_running:
            return
            
        try:
            await self._connect()
            # 启动接收任务 - 确保没有旧任务在运行
            if self.receive_task and not self.receive_task.done():
                logger.bind(tag="BASE").warning("发现未完成的旧接收任务，正在取消...")
                self.receive_task.cancel()
                try:
                    await self.receive_task
                except asyncio.CancelledError:
                    pass
            
            self.receive_task = asyncio.create_task(self._receive_loop())
            logger.bind(tag="BASE").info("已启动新的接收任务")
        except Exception as e:
            logger.error(f"启动ASR连接失败: {e}")
            self.is_running = False
            
    async def _connect(self):
        """建立WebSocket连接"""
        logger.bind(tag="BASE").info(f"连接ASR服务: {self.ws_url}")
        self.is_running = False
        # 构建连接头
        header = RequestBuilder.new_auth_headers()
        
        # 建立WebSocket连接
        self.ws = await websockets.connect(
            self.ws_url, 
            additional_headers=header, 
            ping_interval=5,        # 更频繁的 ping（原来是 120s）
            ping_timeout=3,         # 更短的超时（原来是 60s）
            close_timeout=2,        # 更短的关闭超时
            max_queue=1024,         # 增大队列（原来是 32）
            compression=None,        # 已禁用压缩
            max_size=1000000000,    # 保持大消息支持
        )
        logger.bind(tag="BASE").info("ASR WebSocket连接已建立")
        self.is_running = True
    
    async def _send_initial_request(self):
        """发送初始请求"""
        try:
            async with self.seq_lock:
                request = RequestBuilder.new_full_client_request(self.seq)
                self.seq += 1  # 发送后递增
                await self.ws.send(request)
            logger.bind(tag="BASE").info(f"Sent full client request with seq: {self.seq-1}")
        except Exception as e:
            logger.bind(tag="BASE").error(f"Failed to send full client request: {e}")
            raise
    
    async def _receive_loop(self):
        """接收循环"""
        try:
            while True:
                try:
                    if not self.is_running or not self.ws:
                        logger.bind(tag="BASE").warning("receive_loop 未就绪，无法处理音频")
                        await self._connect()
                    # 检查WebSocket连接状态
                    if hasattr(self.ws, 'closed') and self.ws.closed:
                        logger.bind(tag="BASE").warning("ASR WebSocket连接已关闭，停止接收")
                        await self._connect()
                    response = await self.ws.recv()
                    result = ResponseParser.parse_response(response)
                    await self._handle_response(result)
                except websockets.exceptions.ConnectionClosed:
                    logger.bind(tag="BASE").warning("ASR WebSocket连接已关闭")
                    await self._connect()
                except websockets.exceptions.ConnectionClosedError:
                    logger.warning("ASR WebSocket连接异常关闭")
                    await self._connect()
                except websockets.exceptions.ConnectionClosedOK:
                    logger.bind(tag="BASE").info("ASR WebSocket连接正常关闭")
                except asyncio.CancelledError:
                    logger.bind(tag="BASE").info("接收任务已取消")
                    break
                except Exception as e:
                    logger.bind(tag="BASE").error(f"ASR接收循环异常: {e}")
                    await self._connect()
        except asyncio.CancelledError:
            logger.bind(tag="BASE").info("接收任务已取消")
        except Exception as e:
            logger.bind(tag="BASE").error(f"ASR接收异常: {e}")
    
    async def _handle_response(self, result: AsrResponse):
        """处理服务器响应"""
        if result.code == INVALID_AUDIO_FORMAT:
            logger.bind(tag="BASE").error("音频格式错误")
            return
        if result.event == ServerEvent.ConnectionFinished:
            logger.bind(tag="BASE").info(f"ASR 连接结束: {result.to_dict()}")
            return
        logger.bind(tag="BASE").info(f"ASR 响应: {result.to_dict()}")
        # 处理ASR结果
        if result.code == 0:
            asr_result = result.payload_msg.get("result", {})
            if "text" in asr_result:
                if not self.is_asr_info:
                    self.is_asr_info = True
                    await self._on_asr_info()
                text = asr_result.get("text")
                asr_payload = {
                        "results": [
                            {
                                "text": text,
                                "is_interim": False
                            }
                        ]
                    }
                await self._on_asr_response(asr_payload)
                if result.is_last_package:
                    self.is_asr_info = False
    
    async def on_speak_started(self):
        try:
            self.seq = 1
            await self._send_initial_request()
            self.is_speaking = True
        except Exception as e:
            logger.bind(tag="BASE").error(f"ASR发送Speak start 失败: {e}")
    
    async def on_speak_ended(self):
        try:
            self.is_speaking = False
            await self._on_asr_ended()
            async with self.seq_lock:
                request = RequestBuilder.new_audio_only_request(self.seq, b"", True)
                await self.ws.send(request)
        except Exception as e:
            logger.bind(tag="BASE").error(f"ASR发送Speak end 失败: {e}")
    
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
            logger.bind(tag="BASE").warning("ASR连接未就绪，无法处理音频")
            return
        try:
            if not self.is_speaking:
                self.audio_queue.append(audio_chunk)
                return
            
            while len(self.audio_queue) > 0:
                audio_buffing = self.audio_queue.popleft()
                audio_chunk = audio_buffing + audio_chunk
            async with self.seq_lock:
                request = RequestBuilder.new_audio_only_request(self.seq, audio_chunk)
                self.seq += 1
                await self.ws.send(request)
            # logger.bind(tag="BASE").info(f"发送音频块，大小: {len(audio_chunk)}")
        except Exception as e:
            logger.bind(tag="BASE").error(f"处理音频块失败: {e}")
        
    async def cleanup(self):
        """清理资源"""
        logger.info("开始清理ASR客户端资源")
        # 停止运行
        self.is_running = False
        # 清理连接
        await self._cleanup_connection()        
        logger.info("ASR客户端已清理")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.is_running and self.ws is not None
