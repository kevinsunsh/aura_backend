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

from .doubao_config import asr_config

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

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
        
        # 共享变量 - 会被更新的状态
        self.server_asr_result = ""  # 当前utterance文本
        
        # 发送队列和保活机制
        self.send_queue = None  # 发送队列，在连接时初始化
        self.asrend_task = None

        # 性能点
        self.asr_service_performance_point_id = None

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
            max_size=1000000000
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
        
        full_client_request = bytearray(generate_header())
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
                
            payload_bytes =chunk
            audio_request = bytearray(generate_header(message_type=AUDIO_ONLY_REQUEST))
            audio_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            audio_request.extend(payload_bytes)
            
            await self.ws.send(audio_request)
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
