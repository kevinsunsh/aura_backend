import asyncio
import json
import uuid
import time
import logging
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import websockets
import aiofiles
import fastrand
from utils.utils import start_performance_point, end_performance_point
from .doubao_config import tts_config

logger = logging.getLogger(__name__)

# 发送消息类型
class SendMessageType(Enum):
    """发送消息类型"""
    TEXT = "text"           # 普通文本消息
    KEEPALIVE = "keepalive" # 保活消息

@dataclass
class SendMessage:
    """发送消息"""
    message_type: SendMessageType
    content: str = ""       # 文本内容（仅对TEXT类型有效）
    timestamp: float = 0.0  # 时间戳

# 双向流式TTS相关常量
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type:
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_RESPONSE = 0b1011
FULL_SERVER_RESPONSE = 0b1001
ERROR_INFORMATION = 0b1111

# Message Type Specific Flags
MsgTypeFlagNoSeq = 0b0000  # Non-terminal packet with no sequence
MsgTypeFlagPositiveSeq = 0b1  # Non-terminal packet with sequence > 0
MsgTypeFlagLastNoSeq = 0b10  # last packet with no sequence
MsgTypeFlagNegativeSeq = 0b11  # Payload contains event number (int32)
MsgTypeFlagWithEvent = 0b100

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001

# Message Compression
COMPRESSION_NO = 0b0000
COMPRESSION_GZIP = 0b0001

# TTS事件常量
EVENT_NONE = 0
EVENT_Start_Connection = 1
EVENT_FinishConnection = 2
EVENT_ConnectionStarted = 50
EVENT_ConnectionFailed = 51
EVENT_ConnectionFinished = 52
EVENT_StartSession = 100
EVENT_FinishSession = 102
EVENT_SessionStarted = 150
EVENT_SessionFinished = 152
EVENT_SessionFailed = 153
EVENT_TaskRequest = 200
EVENT_TTSSentenceStart = 350
EVENT_TTSSentenceEnd = 351
EVENT_TTSResponse = 352


class TTSHeader:
    """TTS消息头"""
    def __init__(self,
                 protocol_version=PROTOCOL_VERSION,
                 header_size=DEFAULT_HEADER_SIZE,
                 message_type: int = 0,
                 message_type_specific_flags: int = 0,
                 serial_method: int = NO_SERIALIZATION,
                 compression_type: int = COMPRESSION_NO,
                 reserved_data=0):
        self.header_size = header_size
        self.protocol_version = protocol_version
        self.message_type = message_type
        self.message_type_specific_flags = message_type_specific_flags
        self.serial_method = serial_method
        self.compression_type = compression_type
        self.reserved_data = reserved_data

    def as_bytes(self) -> bytes:
        return bytes([
            (self.protocol_version << 4) | self.header_size,
            (self.message_type << 4) | self.message_type_specific_flags,
            (self.serial_method << 4) | self.compression_type,
            self.reserved_data
        ])


class TTSOptional:
    """TTS可选字段"""
    def __init__(self, event: int = EVENT_NONE, sessionId: str = None, sequence: int = None):
        self.event = event
        self.sessionId = sessionId
        self.errorCode: int = 0
        self.connectionId: str | None = None
        self.response_meta_json: str | None = None
        self.sequence = sequence

    def as_bytes(self) -> bytes:
        option_bytes = bytearray()
        if self.event != EVENT_NONE:
            option_bytes.extend(self.event.to_bytes(4, "big", signed=True))
        if self.sessionId is not None:
            session_id_bytes = str.encode(self.sessionId)
            size = len(session_id_bytes).to_bytes(4, "big", signed=True)
            option_bytes.extend(size)
            option_bytes.extend(session_id_bytes)
        if self.sequence is not None:
            option_bytes.extend(self.sequence.to_bytes(4, "big", signed=True))
        return option_bytes


class TTSResponse:
    """TTS响应"""
    def __init__(self, header: TTSHeader, optional: TTSOptional):
        self.optional = optional
        self.header = header
        self.payload: bytes | None = None
        self.payload_json: str | None = None


class TtsClient:
    """TTS客户端，支持双向流式语音合成和断线重连"""
    
    def __init__(self, 
                 uid: str = None,
                 app_id: str = None,
                 token: str = None,
                 speaker: str = None,
                 tts_start_callback: Callable[[str], None] = None,
                 tts_response_callback: Callable[[bytes], None] = None,
                 tts_end_callback: Callable[[], None] = None,
                 tts_reconnect_callback: Callable[[], None] = None,
                 tts_disconnect_callback: Callable[[], None] = None,
                 max_reconnect_attempts: int = 5,
                 reconnect_interval: float = 2.0,
                 reconnect_backoff_factor: float = 1.5,
                 max_reconnect_interval: float = 30.0,
                 **kwargs):
        """
        初始化TTS客户端
        
        Args:
            app_id: 应用ID，如果为None则从配置文件获取
            token: 访问令牌，如果为None则从配置文件获取
            speaker: 说话人ID，如果为None则从配置文件获取
            tts_start_callback: TTS开始回调
            tts_response_callback: TTS音频数据回调，参数为音频数据bytes
            tts_end_callback: TTS结束回调
            tts_reconnect_callback: 重连成功回调
            tts_disconnect_callback: 连接断开回调
            max_reconnect_attempts: 最大重连尝试次数，0表示无限重连
            reconnect_interval: 重连间隔（秒）
            reconnect_backoff_factor: 重连间隔指数退避因子
            max_reconnect_interval: 最大重连间隔（秒）
        """
        # 使用配置文件中的设置，也可以通过参数覆盖
        self.app_id = app_id or tts_config["app_id"]
        self.token = token or tts_config["token"] 
        self.speaker = speaker or tts_config["speaker"]
        self.ws_url = kwargs.get("ws_url", tts_config["ws_url"])
        self.uid = uid

        # 音频配置
        self.audio_format = kwargs.get("audio_format", tts_config["audio"]["format"])
        self.audio_sample_rate = kwargs.get("audio_sample_rate", tts_config["audio"]["sample_rate"])
        
        # 回调函数
        self.tts_start_callback = tts_start_callback
        self.tts_response_callback = tts_response_callback
        self.tts_end_callback = tts_end_callback
        self.tts_reconnect_callback = tts_reconnect_callback
        self.tts_disconnect_callback = tts_disconnect_callback
        
        # 重连配置
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_interval = reconnect_interval
        self.reconnect_backoff_factor = reconnect_backoff_factor
        self.max_reconnect_interval = max_reconnect_interval
        
        # 连接状态
        self.ws = None
        self.is_running = False
        self.session_id = None
        self.connection_id = None
        self.connection_lost = False  # 新增：标记连接是否丢失
        
        # 重连状态
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        self.current_reconnect_interval = self.reconnect_interval
        self.should_reconnect = True
        self.reconnect_task = None
        
        # 任务管理
        self._receive_task = None
        self._send_task = None  # 新增：发送任务
        
        # TTS会话状态
        self._tts_session_active = False
        self.buffer_text = ""
        # 性能指标
        self.tts_service_performance_point_id = None
        
    def _gen_log_id(self):
        """生成logID"""
        ts = int(time.time() * 1000)  # 毫秒时间戳
        r = fastrand.pcg32bounded(1 << 24) + (1 << 20)
        local_ip = "00000000000000000000000000000000"
        return f"02{ts}{local_ip}{r:08x}"

    async def _send_tts_event(self, ws, header: bytes, optional: bytes = None, payload: bytes = None):
        """发送TTS事件"""
        full_client_request = bytearray(header)
        if optional is not None:
            full_client_request.extend(optional)
        if payload is not None:
            payload_size = len(payload).to_bytes(4, 'big', signed=True)
            full_client_request.extend(payload_size)
            full_client_request.extend(payload)
        await ws.send(full_client_request)

    def _read_tts_content(self, res: bytes, offset: int):
        """读取TTS响应内容"""
        content_size = int.from_bytes(res[offset: offset + 4])
        offset += 4
        content = str(res[offset: offset + content_size], encoding='utf8')
        offset += content_size
        return content, offset

    def _read_tts_payload(self, res: bytes, offset: int):
        """读取TTS响应payload"""
        payload_size = int.from_bytes(res[offset: offset + 4])
        offset += 4
        payload = res[offset: offset + payload_size]
        offset += payload_size
        return payload, offset

    def _parse_tts_response(self, res) -> TTSResponse:
        """解析TTS响应结果"""
        if isinstance(res, str):
            raise RuntimeError(res)
        response = TTSResponse(TTSHeader(), TTSOptional())
        
        # 解析header
        header = response.header
        num = 0b00001111
        header.protocol_version = res[0] >> 4 & num
        header.header_size = res[0] & 0x0f
        header.message_type = (res[1] >> 4) & num
        header.message_type_specific_flags = res[1] & 0x0f
        header.serial_method = res[2] >> num
        header.compression_type = res[2] & 0x0f
        header.reserved = res[3]
        
        offset = 4
        optional = response.optional
        
        if header.message_type == FULL_SERVER_RESPONSE or AUDIO_ONLY_RESPONSE:
            if header.message_type_specific_flags == MsgTypeFlagWithEvent:
                optional.event = int.from_bytes(res[offset:offset+4])
                offset += 4
                if optional.event == EVENT_NONE:
                    return response
                elif optional.event == EVENT_ConnectionStarted:
                    optional.connectionId, offset = self._read_tts_content(res, offset)
                elif optional.event == EVENT_ConnectionFailed:
                    optional.response_meta_json, offset = self._read_tts_content(res, offset)
                elif (optional.event == EVENT_SessionStarted
                      or optional.event == EVENT_SessionFailed
                      or optional.event == EVENT_SessionFinished):
                    optional.sessionId, offset = self._read_tts_content(res, offset)
                    optional.response_meta_json, offset = self._read_tts_content(res, offset)
                elif optional.event == EVENT_TTSResponse:
                    optional.sessionId, offset = self._read_tts_content(res, offset)
                    response.payload, offset = self._read_tts_payload(res, offset)
                elif optional.event == EVENT_TTSSentenceEnd or optional.event == EVENT_TTSSentenceStart:
                    optional.sessionId, offset = self._read_tts_content(res, offset)
                    response.payload_json, offset = self._read_tts_content(res, offset)
        
        elif header.message_type == ERROR_INFORMATION:
            optional.errorCode = int.from_bytes(res[offset:offset+4], "big", signed=True)
            offset += 4
            response.payload, offset = self._read_tts_payload(res, offset)
        
        return response

    def _get_tts_payload_bytes(self, uid='1234', event=EVENT_NONE, text='', speaker=''):
        """生成TTS payload字节"""
        return str.encode(json.dumps({
            "user": {"uid": uid},
            "event": event,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {
                    "format": self.audio_format,
                    "sample_rate": self.audio_sample_rate
                }
            }
        }))

    async def _tts_start_connection(self, websocket):
        """TTS开始连接"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent).as_bytes()
        optional = TTSOptional(event=EVENT_Start_Connection).as_bytes()
        payload = str.encode("{}")
        return await self._send_tts_event(websocket, header, optional, payload)

    async def _tts_start_session(self, websocket, speaker, session_id):
        """TTS开始会话"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_StartSession, sessionId=session_id).as_bytes()
        payload = self._get_tts_payload_bytes(uid=self.uid, event=EVENT_StartSession, speaker=speaker)
        return await self._send_tts_event(websocket, header, optional, payload)

    async def _tts_send_text(self, ws, speaker: str, text: str, session_id):
        """TTS发送文本"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_TaskRequest, sessionId=session_id).as_bytes()
        payload = self._get_tts_payload_bytes(uid=self.uid, event=EVENT_TaskRequest, text=text, speaker=speaker)
        return await self._send_tts_event(ws, header, optional, payload)

    async def _tts_finish_session(self, ws, session_id):
        """TTS结束会话"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_FinishSession, sessionId=session_id).as_bytes()
        payload = str.encode('{}')
        return await self._send_tts_event(ws, header, optional, payload)

    async def _tts_finish_connection(self, ws):
        """TTS结束连接"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_FinishConnection).as_bytes()
        payload = str.encode('{}')
        return await self._send_tts_event(ws, header, optional, payload)

    async def start(self):
        """启动TTS连接并建立会话"""
        if self.is_running:
            return
            
        try:
            await self._connect()
        except Exception as e:
            logger.error(f"启动TTS连接失败: {e}")
            if self.should_reconnect:
                await self._handle_reconnect()
            else:
                raise

    async def _connect(self):
        """建立TTS连接和会话"""
        logger.info(f"建立TTS连接: {self.ws_url}")
        
        log_id = self._gen_log_id()
        
        ws_header = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.token,
            "X-Api-Resource-Id": 'volc.service_type.10029',
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Tt-Logid": log_id,
        }
        
        # 建立WebSocket连接
        self.ws = await websockets.connect(self.ws_url, additional_headers=ws_header, max_size=1000000000)
        
        # 开始连接
        await self._tts_start_connection(self.ws)
        res = self._parse_tts_response(await self.ws.recv())
        logger.debug(f"TTS连接响应: event={res.optional.event}")
        
        if res.optional.event != EVENT_ConnectionStarted:
            raise RuntimeError("TTS连接失败")
        
        self.connection_id = res.optional.connectionId
        
        # 开始会话
        self.session_id = str(uuid.uuid4()).replace('-', '')
        await self._tts_start_session(self.ws, self.speaker, self.session_id)
        res = self._parse_tts_response(await self.ws.recv())
        logger.debug(f"TTS会话响应: event={res.optional.event}")
        if res.optional.event != EVENT_SessionStarted:
            raise RuntimeError('连接TTS会话启动失败')
        
        self.is_running = True
        self._tts_session_active = True
        self.buffer_text = ""
        # 重置重连状态
        if self.is_reconnecting:
            self.is_reconnecting = False
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval
            self.connection_lost = False  # 重连成功后重置连接丢失标志
            
            # 触发重连成功回调
            if self.tts_reconnect_callback:
                try:
                    if asyncio.iscoroutinefunction(self.tts_reconnect_callback):
                        await self.tts_reconnect_callback()
                    else:
                        self.tts_reconnect_callback()
                except Exception as e:
                    logger.error(f"TTS重连回调执行失败: {e}")
        
        logger.info("TTS连接和会话建立成功")
        
        # 启动接收和发送任务
        self._receive_task = asyncio.create_task(self._receive_loop())
        
        # 初始化最后发送时间
        self.last_send_time = time.time()

    async def _receive_loop(self):
        """接收音频数据循环"""
        try:
            while self.is_running and self.ws:
                try:
                    res = self._parse_tts_response(await self.ws.recv())
                    logger.debug(f"TTS响应: event={res.optional.event}, type={res.header.message_type}")
                    
                    if res.optional.event == EVENT_TTSResponse and res.header.message_type == AUDIO_ONLY_RESPONSE:
                        if res.payload:
                            # 触发TTS响应回调
                            end_performance_point(self.tts_service_performance_point_id)
                            if self.tts_response_callback:
                                try:
                                    if asyncio.iscoroutinefunction(self.tts_response_callback):
                                        await self.tts_response_callback(res.payload)
                                    else:
                                        self.tts_response_callback(res.payload)
                                except Exception as e:
                                    logger.error(f"TTS响应回调执行失败: {e}")
                    elif res.optional.event == EVENT_TTSSentenceStart:
                        logger.debug(f"TTS句子事件: {res.optional.event}")
                        json_data = json.loads(res.payload_json)
                        text = json_data.get("text", "")
                        # 第一次开始合成时触发开始回调
                        if self.tts_start_callback:
                            try:
                                if asyncio.iscoroutinefunction(self.tts_start_callback):
                                    await self.tts_start_callback(text)
                                else:
                                    self.tts_start_callback(text)
                            except Exception as e:
                                logger.error(f"TTS开始回调执行失败: {e}")
                    elif res.optional.event == EVENT_TTSSentenceEnd:
                        logger.debug(f"TTS句子结束: {res.optional.event}")
                        if self.tts_end_callback:
                            try:
                                if asyncio.iscoroutinefunction(self.tts_end_callback):
                                    await self.tts_end_callback()
                                else:
                                    self.tts_end_callback()
                            except Exception as e:
                                logger.error(f"TTS结束回调执行失败: {e}")
                    elif res.optional.event == EVENT_SessionStarted:
                        logger.debug(f"TTS会话开始: {res.optional.event}")
                        self._tts_session_active = True
                    elif res.optional.event == EVENT_SessionFailed:
                        logger.error(f"TTS会话失败: {res.optional.event}")
                        self._tts_session_active = False
                        # 会话失败时只标记断开
                        self._mark_disconnected()
                        break
                    elif res.optional.event == EVENT_SessionFinished:
                        # 会话结束，触发结束回调
                        logger.debug(f"TTS会话结束: {res.optional.event}")
                        self._tts_session_active = False
                        self.session_id = str(uuid.uuid4()).replace('-', '')
                        await self._tts_start_session(self.ws, self.speaker, self.session_id)
                    elif res.optional.event == EVENT_ConnectionFailed:
                        logger.error(f"TTS连接失败: {res.optional.event}")
                        self._mark_disconnected()
                        break
                
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("TTS WebSocket连接已关闭")
                    self._mark_disconnected()
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.warning("TTS WebSocket连接异常关闭")
                    self._mark_disconnected()
                    break
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("TTS WebSocket连接正常关闭")
                    break
                except Exception as e:
                    logger.error(f"接收TTS音频数据失败: {e}")
                    self._mark_disconnected()
                    break
                    
        except Exception as e:
            logger.error(f"TTS接收循环出现错误: {e}")
            self._mark_disconnected()
        except asyncio.CancelledError:
            logger.info("TTS接收任务已取消")
        finally:
            # 接收循环结束时，根据连接丢失状态决定是否重连
            if self.connection_lost and self.should_reconnect:
                logger.info("TTS接收循环结束，检测到连接丢失，启动重连逻辑")
                # 在这里触发重连，避免在循环中创建新的接收任务
                asyncio.create_task(self._handle_disconnect())
            
            # 确保在接收循环结束时设置运行状态为False
            if self.is_running:
                self.is_running = False

    def _mark_disconnected(self):
        """标记连接已断开（同步方法，避免在接收循环中创建新任务）"""
        if self.is_running:
            logger.warning("标记TTS连接已断开")
            self.connection_lost = True  # 标记连接丢失，用于重连判断
            self._tts_session_active = False

    async def _handle_disconnect(self):
        """处理连接断开"""
        if self.is_reconnecting:
            logger.debug("TTS重连已在进行中，跳过断开处理")
            return
            
        logger.warning("处理TTS连接断开")
        self.is_running = False
        self._tts_session_active = False
        
        # 调用断开连接回调
        if self.tts_disconnect_callback:
            try:
                if asyncio.iscoroutinefunction(self.tts_disconnect_callback):
                    await self.tts_disconnect_callback()
                else:
                    self.tts_disconnect_callback()
            except Exception as e:
                logger.error(f"执行TTS断开连接回调失败: {e}")
        
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
            
            logger.info(f"尝试TTS重连 ({self.reconnect_attempts}/{self.max_reconnect_attempts if self.max_reconnect_attempts > 0 else '∞'})")
            
            try:
                # 等待重连间隔
                await asyncio.sleep(self.current_reconnect_interval)
                
                # 清理之前的连接
                await self._cleanup_connection()
                
                # 尝试重连
                await self._connect()
                
                logger.info("TTS重连成功")
                return
                
            except Exception as e:
                logger.error(f"TTS重连失败: {e}")
                
                # 增加重连间隔（指数退避）
                self.current_reconnect_interval = min(
                    self.current_reconnect_interval * self.reconnect_backoff_factor,
                    self.max_reconnect_interval
                )
                
        # 重连失败
        if self.should_reconnect:
            logger.error(f"TTS重连达到最大尝试次数 ({self.max_reconnect_attempts})，停止重连")
            self.is_reconnecting = False
            
    async def _cleanup_connection(self):
        """清理连接相关资源（不重置重连状态）"""
        # 取消并等待接收任务完成
        if self._receive_task and not self._receive_task.done():
            logger.debug("取消TTS接收任务...")
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                logger.debug("TTS接收任务已取消")
            except Exception as e:
                logger.error(f"等待TTS接收任务结束时出错: {e}")
        self._receive_task = None
        
        # 关闭WebSocket连接
        if self.ws:
            try:
                # 尝试正常结束会话和连接
                # if self.session_id:
                #     try:
                #         await self._tts_finish_session(self.ws, self.session_id)
                #     except:
                #         pass
                try:
                    await self._tts_finish_connection(self.ws)
                except:
                    pass
                await self.ws.close()
                logger.debug("TTS WebSocket连接已关闭")
            except Exception as e:
                logger.debug(f"关闭TTS WebSocket时出错: {e}")
            self.ws = None
            
        # 重置会话相关状态
        self._tts_session_active = False
        self.buffer_text = ""
        self.session_id = None
        self.connection_id = None
        # 注意：不在这里重置 connection_lost，因为重连时需要保持这个状态
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False):
        """
        发送文本片段进行流式合成（异步队列版本）
        
        Args:
            text: 文本片段
        """
        if not self.is_running or not self.ws:
            return
        
        if not self._tts_session_active:
            self.buffer_text += text
            return
        
        try:
            # 非阻塞方式放入队列，如果队列满了就记录警告
            try:
                await self._send_text_internal(self.buffer_text + text)
                if end:
                    await self._tts_finish_session(self.ws, self.session_id)
                logger.debug(f"文本已加入发送队列: {text[:50]}...")
            except asyncio.QueueFull:
                logger.warning("发送队列已满，文本将被丢弃")
                
        except Exception as e:
            logger.error(f"发送文本片段失败: {e}")
            if self.is_running:
                await self._handle_disconnect()

    async def _send_text_internal(self, text: str):
        """内部发送文本方法"""
        if self.tts_service_performance_point_id is None:
            self.tts_service_performance_point_id = start_performance_point("TTS服务")
        if len(text) > 0:
            await self._tts_send_text(self.ws, self.speaker, text, self.session_id)
            logger.info(f"已发送文本片段: {text[:50]}...")

    def enable_reconnect(self):
        """启用自动重连"""
        self.should_reconnect = True

    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态信息"""
        return {
            "is_running": self.is_running,
            "is_reconnecting": self.is_reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "should_reconnect": self.should_reconnect,
            "session_active": self._tts_session_active,
            "has_connection": self.ws is not None
        }

    async def cleanup(self):
        """清理资源"""
        try:
            self.is_running = False
            self.should_reconnect = False
            
            # 取消重连任务
            if self.reconnect_task and not self.reconnect_task.done():
                self.reconnect_task.cancel()
                try:
                    await self.reconnect_task
                except asyncio.CancelledError:
                    pass
                    
            # 清理连接
            await self._cleanup_connection()
            
            # 重置所有状态
            self.is_reconnecting = False
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval
            self.connection_lost = False
                
            logger.info("TTS客户端已清理")
        except Exception as e:
            logger.error(f"清理TTS客户端时出错: {e}")

    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.is_running and self.ws is not None