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
from enum import Enum
from dataclasses import dataclass
import websockets
from utils.utils import start_performance_point, end_performance_point

from .config import asr_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class SendMessageType(Enum):
    """发送消息类型"""
    AUDIO = "audio"
    KEEPALIVE = "keepalive"


@dataclass
class SendMessage:
    """发送消息数据类"""
    type: SendMessageType
    content: bytes  # 音频数据
    is_last: bool = False
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class AsrConnectionError(Exception):
    """ASR连接错误异常"""
    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"ASR连接错误: code={code}, message={message}")


class AsrServiceError(Exception):
    """ASR服务错误异常"""
    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"ASR服务错误: code={code}, message={message}")


# 需要触发重连的ASR错误码
RECONNECT_ERROR_CODES = {
    45000001,  # 请求参数无效 - 请求参数缺失必需字段/字段值无效/重复请求
    45000081,  # 等包超时
    55000031,  # 服务器繁忙 - 服务过载，无法处理当前请求
}

# 不需要重连的错误码（仅记录，供参考）
# 45000002: 空音频 - 客户端音频问题，重连无效
# 45000151: 音频格式不正确 - 配置问题，重连无效

def should_reconnect_on_error(code: int) -> bool:
    """
    判断错误码是否需要触发重连
    
    需要重连的错误码：
    - 45000001: 请求参数无效
    - 45000081: 等包超时  
    - 55000031: 服务器繁忙
    - 550xxxxx: 服务内部处理错误（55000000-55099999范围）
    
    不需要重连的错误码：
    - 45000002: 空音频（客户端问题）
    - 45000151: 音频格式不正确（配置问题）
    """
    # 检查精确匹配的错误码
    if code in RECONNECT_ERROR_CODES:
        return True
    
    # 检查550xxxxx范围的服务内部处理错误
    if 55000000 <= code <= 55099999:
        return True
    
    return False

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
        self.ws_url = kwargs.get("ws_url", asr_config["ws_url"])
        self.uid = uid
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
        self.asr_started = False
        self.seq = 1
        self.reqid = None
        self.connection_lost = False  # 新增：标记连接是否丢失
        
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
        
        # 回调任务管理 - 使用专门的异步循环任务
        self.callback_loop_task = None  # 专门负责调用asr_response_callback的异步循环任务
        self.callback_loop_lock = asyncio.Lock()  # 循环任务管理锁
        
        # 共享变量 - 会被更新的状态
        self.cur_utterance_text = ""  # 当前utterance文本
        self.is_interim = False  # interim标记
        self.last_update_time = 0  # 最后更新时间戳
        self.callback_interval = 1.0  # 回调间隔时间（秒）
        
        # 发送队列和保活机制
        self.send_queue = None  # 发送队列，在连接时初始化
        self.send_task = None  # 发送任务
        self.keepalive_interval = kwargs.get("keepalive_interval", 5.0)  # 保活间隔（秒）
        self.last_send_time = 0  # 最后发送时间
        self.keepalive_enabled = kwargs.get("keepalive_enabled", True)  # 是否启用自动保活
        self.silence_audio_cache = None  # 静音音频缓存

        # 性能点
        # self.send_audio_chunk_performance_point_id = None

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
                "show_utterances": True,
                "result_type": "single",
                "end_window_size": 600
            }
        }
        return req
        
    def _generate_silence_audio(self, duration_seconds: float = 1.0) -> bytes:
        """
        生成指定时长的静音音频数据
        :param duration_seconds: 静音时长（秒）
        :return: PCM音频数据
        """
        if self.silence_audio_cache is None:
            # 计算音频数据大小：采样率 * 通道数 * 位深度(字节) * 时长
            bytes_per_sample = self.bits // 8
            total_samples = int(self.rate * self.channel * duration_seconds)
            audio_data_size = total_samples * bytes_per_sample
            
            # 生成静音数据（全为0）
            self.silence_audio_cache = b'\x00' * audio_data_size
            logger.debug(f"生成静音音频缓存: {audio_data_size} 字节 "
                        f"(采样率={self.rate}, 通道={self.channel}, 位深={self.bits}, 时长={duration_seconds}秒)")
        
        return self.silence_audio_cache
        
    def _should_send_keepalive(self) -> bool:
        # return False
        """检查是否需要发送保活音频"""
        if not self.keepalive_enabled:
            return False
        
        current_time = time.time()
        time_since_last_send = current_time - self.last_send_time
        
        return time_since_last_send >= self.keepalive_interval
        
    async def _send_keepalive(self):
        """发送保活音频（静音）"""
        try:
            silence_audio = self._generate_silence_audio(1.0)  # 1秒静音
            logger.debug(f"发送ASR保活音频: {len(silence_audio)} 字节")
            await self._send_audio_chunk_direct(silence_audio, last=False)
            self.last_send_time = time.time()
        except Exception as e:
            logger.error(f"发送ASR保活音频失败: {e}")
            raise
            
    async def _send_loop(self):
        """发送循环，处理队列中的音频消息和自动保活"""
        logger.debug("ASR发送循环已启动")
        
        # 计算检查间隔：保活间隔的1/3，但不超过5秒，不少于1秒
        check_interval = max(1.0, min(5.0, self.keepalive_interval / 3))
        
        try:
            while self.is_running and self.ws:
                try:
                    # 尝试从队列获取消息，使用较短的超时时间确保能定期检查保活
                    try:
                        message = await asyncio.wait_for(
                            self.send_queue.get(), 
                            timeout=check_interval
                        )
                        
                        # 处理音频消息
                        if message.type == SendMessageType.AUDIO:
                            await self._send_audio_chunk_direct(message.content, message.is_last)
                            self.last_send_time = time.time()  # 更新最后发送时间
                            # logger.debug(f"发送音频数据: {len(message.content)} 字节, last={message.is_last}")
                            
                        # 标记队列任务完成（asyncio.Queue标准用法）
                        self.send_queue.task_done()
                        
                    except asyncio.TimeoutError:
                        # 队列超时，检查是否需要发送保活
                        if self._should_send_keepalive():
                            logger.debug(f"触发ASR自动保活，距离上次发送: {time.time() - self.last_send_time:.1f}秒")
                            await self._send_keepalive()
                        
                except Exception as e:
                    logger.error(f"ASR发送循环处理消息时出错: {e}")
                    # 发送错误可能表示连接问题，标记断开
                    self._mark_disconnected()
                    break
                    
        except Exception as e:
            logger.error(f"ASR发送循环异常: {e}")
        finally:
            logger.debug("ASR发送循环已结束")
    
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
        
        # 初始化发送队列（最大容量100）
        self.send_queue = asyncio.Queue(maxsize=100)
        
        # 启动发送任务 - 确保没有旧任务在运行
        if self.send_task and not self.send_task.done():
            logger.warning("发现未完成的旧发送任务，正在取消...")
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
        
        self.send_task = asyncio.create_task(self._send_loop())
        logger.debug("已启动新的发送任务")
        
        # 启动回调循环任务 - 确保没有旧任务在运行
        if self.callback_loop_task and not self.callback_loop_task.done():
            logger.warning("发现未完成的旧回调循环任务，正在取消...")
            self.callback_loop_task.cancel()
            try:
                await self.callback_loop_task
            except asyncio.CancelledError:
                pass
        
        self.callback_loop_task = asyncio.create_task(self._callback_loop())
        logger.debug("已启动新的回调循环任务")
        
        # 初始化保活状态
        self.last_send_time = time.time()
        
        # 重置重连状态
        if self.is_reconnecting:
            self.is_reconnecting = False
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval
            self.connection_lost = False  # 重连成功后重置连接丢失标志
            logger.info("ASR重连成功")
            if self.asr_reconnect_callback:
                # 异步执行重连回调，不阻塞连接流程
                asyncio.create_task(self._safe_execute_callback(self.asr_reconnect_callback))

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
                    # 检查WebSocket连接状态
                    if hasattr(self.ws, 'closed') and self.ws.closed:
                        logger.warning("ASR WebSocket连接已关闭，停止接收")
                        self._mark_disconnected()
                        break
                    
                    # logger.debug(f"开始接收新的ASR响应")
                    response = await self.ws.recv()
                    result = parse_response(response)
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
                except (AsrConnectionError, AsrServiceError) as e:
                    logger.error(f"ASR服务错误，触发重连: {e}")
                    self._mark_disconnected()
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
                
    async def _handle_response(self, result: Dict[str, Any]):
        """处理服务器响应"""
        # logger.debug(f"ASR响应: {result}")
        
        # 处理ASR结果
        if 'payload_msg' in result and result['payload_msg']:
            payload = result['payload_msg']
            # logger.info(f"ASR payload: {payload}")
            
            # 检查是否有识别结果
            if isinstance(payload, dict):
                # 检查是否有result字段（包含识别文本）
                if 'result' in payload and payload['result']:
                    asr_result = payload['result']
                    
                    # 如果是首次收到ASR包，标记会话已开始并触发ASRInfo事件
                    if not self.asr_started:
                        self.asr_started = True
                        if self.asr_start_callback:
                            # 异步执行开始回调，不阻塞接收循环
                            asyncio.create_task(self._safe_execute_callback(self.asr_start_callback))
                    
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
                                    if utterance_text and self.asr_response_callback:  # 只有非空文本才处理
                                        logger.info(f"ASR 新utterance结果 [{i+1}] (definite={is_definite}): {utterance_text}")
                                        # 更新共享变量，让专门的循环任务处理回调
                                        await self._update_callback_state(utterance_text, is_definite)
                    
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
                        
                        # 只有特定错误码才抛出异常触发重连
                        if should_reconnect_on_error(code):
                            logger.warning(f"错误码 {code} 需要重连，抛出异常")
                            raise AsrServiceError(code, message)
                        else:
                            logger.info(f"错误码 {code} 不需要重连，继续处理")
                        
        # 处理错误响应
        if 'code' in result:
            error_code = result['code']
            message = result.get('message', '未知错误')
            logger.error(f"ASR连接错误: code={error_code}, message={message}")
            
            # 只有特定错误码才抛出异常触发重连
            if should_reconnect_on_error(error_code):
                logger.warning(f"连接错误码 {error_code} 需要重连，抛出异常")
                raise AsrConnectionError(error_code, message)
            else:
                logger.info(f"连接错误码 {error_code} 不需要重连，继续处理")
            
        # 检查是否是最后一个包
        if result.get('is_last_package', False):
            logger.info("收到ASR最后响应包")

    async def _safe_execute_callback(self, callback, *args):
        """安全执行回调函数，捕获异常避免影响主流程"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"执行回调函数失败: {e}")
            # 不重新抛出异常，避免影响主流程

    async def _update_callback_state(self, utterance_text: str, is_interim: bool = False):
        """更新回调状态，让专门的循环任务处理回调"""
        async with self.callback_loop_lock:
            # 更新共享变量
            self.cur_utterance_text = utterance_text
            self.is_interim = is_interim
            self.last_update_time = time.time()
            
            logger.debug(f"更新回调状态: text='{utterance_text[:30]}...', interim={is_interim}")

    async def _callback_loop(self):
        """专门的异步循环任务，负责调用asr_response_callback"""
        logger.info("ASR回调循环任务已启动")
        
        try:
            while self.is_running:
                try:
                    current_time = time.time()
                    
                    # 检查是否有内容需要处理
                    if self.cur_utterance_text:
                        # 条件1: 如果是interim，立即调用
                        if self.is_interim:
                            text_to_call = self.cur_utterance_text
                            interim_flag = self.is_interim
                            
                            # 清空状态，避免重复调用
                            self.cur_utterance_text = ""
                            self.is_interim = False
                            logger.info(f"立即调用interim回调: '{text_to_call[:30]}...'")
                            await self._safe_execute_callback(self.asr_response_callback, text_to_call, interim_flag)
                            
                            self.asr_started = False

                        # 条件2: 如果时间间隔达到1秒，调用回调
                        elif current_time - self.last_update_time >= self.callback_interval:
                            text_to_call = self.cur_utterance_text
                            interim_flag = self.is_interim
                            
                            # 清空状态，避免重复调用
                            self.cur_utterance_text = ""
                            self.is_interim = False
                            
                            logger.info(f"定时调用回调: '{text_to_call[:30]}...' (间隔: {current_time - self.last_update_time:.3f}秒)")
                            await self._safe_execute_callback(self.asr_response_callback, text_to_call, interim_flag)
                            
                            self.asr_started = False

                    # 等待一小段时间再检查
                    await asyncio.sleep(0.1)  # 100ms检查间隔
                    
                except asyncio.CancelledError:
                    logger.info("ASR回调循环任务被取消")
                    break
                except Exception as e:
                    logger.error(f"ASR回调循环任务出错: {e}")
                    await asyncio.sleep(0.1)  # 出错时也等待一下
                    
        except Exception as e:
            logger.error(f"ASR回调循环任务异常: {e}")
        finally:
            logger.info("ASR回调循环任务已结束")

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
        
        # 调用断开连接回调
        if self.asr_disconnect_callback:
            # 异步执行断开连接回调，不阻塞重连流程
            asyncio.create_task(self._safe_execute_callback(self.asr_disconnect_callback))
        
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
        # 取消并等待发送任务完成
        if self.send_task and not self.send_task.done():
            logger.debug("取消发送任务...")
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                logger.debug("发送任务已取消")
            except Exception as e:
                logger.error(f"等待发送任务结束时出错: {e}")
        self.send_task = None
        
        # 清空发送队列
        if self.send_queue:
            while not self.send_queue.empty():
                try:
                    self.send_queue.get_nowait()
                    self.send_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            self.send_queue = None
        
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
        
        # 取消回调循环任务（重连时也需要清理）
        async with self.callback_loop_lock:
            if self.callback_loop_task and not self.callback_loop_task.done():
                logger.debug("清理时取消ASR回调循环任务...")
                self.callback_loop_task.cancel()
                try:
                    await asyncio.wait_for(self.callback_loop_task, timeout=0.5)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    logger.debug("ASR回调循环任务已取消")
                except Exception as e:
                    logger.error(f"取消ASR回调循环任务时出错: {e}")
                self.callback_loop_task = None
            
            # 重置回调状态
            self.cur_utterance_text = ""
            self.is_interim = False
            self.last_update_time = 0
        
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
        # 注意：不在这里重置 connection_lost，因为重连时需要保持这个状态

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
            async with self.buffer_lock:
                self.audio_buffer.extend(audio_chunk)
                
                # 计算分片大小（PCM格式：采样率 * 通道数 * 位深/8 * 时长）
                segment_size = int(self.rate * self.channel * (self.bits // 8) * self.seg_duration / 1000)
                # segment_size = 3200
                
                # 如果缓冲区足够大，发送数据
                while len(self.audio_buffer) >= segment_size:
                    chunk_to_send = bytes(self.audio_buffer[:segment_size])
                    self.audio_buffer = self.audio_buffer[segment_size:]
                    # self.send_audio_chunk_performance_point_id = start_performance_point("发送音频块")
                    await self._send_audio_chunk_direct(chunk_to_send, last=False)
                    
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
            
    async def _send_audio_chunk_direct(self, chunk: bytes, last: bool = False):
        """直接发送音频块（底层方法）"""
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
            # end_performance_point(self.send_audio_chunk_performance_point_id)
        except Exception as e:
            logger.error(f"发送音频块失败: {e}")
            raise
            
    async def _send_audio_chunk(self, chunk: bytes, last: bool = False):
        """通过队列发送音频块"""
        if not self.is_running or not self.send_queue:
            logger.warning("ASR连接未就绪或发送队列不可用，无法发送音频")
            return
            
        try:
            # 创建发送消息
            message = SendMessage(
                type=SendMessageType.AUDIO,
                content=chunk,
                is_last=last
            )
            
            # 非阻塞方式放入队列
            try:
                self.send_queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("ASR发送队列已满，丢弃音频数据")
                
        except Exception as e:
            logger.error(f"将音频加入发送队列失败: {e}")
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
        send_queue_size = self.send_queue.qsize() if self.send_queue else 0
        time_since_last_send = current_time - self.last_send_time if self.last_send_time > 0 else 0
        
        return {
            "is_running": self.is_running,
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "current_reconnect_interval": self.current_reconnect_interval,
            "should_reconnect": self.should_reconnect,
            "session_started": self.session_started,
            "send_queue_size": send_queue_size,
            "keepalive_enabled": self.keepalive_enabled,
            "keepalive_interval": self.keepalive_interval,
            "last_send_time": self.last_send_time,
            "time_since_last_send": time_since_last_send
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
        
        # 取消发送任务
        if self.send_task:
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
            self.send_task = None
        
        # 取消回调循环任务
        async with self.callback_loop_lock:
            if self.callback_loop_task and not self.callback_loop_task.done():
                logger.debug("取消ASR回调循环任务...")
                self.callback_loop_task.cancel()
                try:
                    await asyncio.wait_for(self.callback_loop_task, timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    logger.debug("ASR回调循环任务已取消")
                except Exception as e:
                    logger.error(f"取消ASR回调循环任务时出错: {e}")
                self.callback_loop_task = None
            
            # 重置回调状态
            self.cur_utterance_text = ""
            self.is_interim = False
            self.last_update_time = 0
        
        # 清理连接
        await self._cleanup_connection()
        
        # 重置所有状态
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.connection_lost = False
        
        logger.info("ASR客户端已清理")
        