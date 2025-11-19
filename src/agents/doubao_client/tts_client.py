import re
import asyncio
import json
import uuid
import time
from loguru import logger
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import websockets
import fastrand
from utils.utils import start_performance_point, end_performance_point, safe_call
from .doubao_config import tts_config, get_tts_payload_bytes
import threading

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
EVENT_CancelSession = 101
EVENT_FinishSession = 102
EVENT_SessionStarted = 150
EVENT_SessionCanceled = 151
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
                 app_id: str = None,
                 token: str = None,
                 speaker: str = None,
                 tts_sentence_start_callback: Callable[[dict, str], None] = None,
                 tts_response_callback: Callable[[bytes, str], None] = None,
                 tts_sentence_end_callback: Callable[[str], None] = None,
                 tts_ended_callback: Callable[[str], None] = None,
                 session_id: Optional[Any] = None,
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
        """
        # 使用配置文件中的设置，也可以通过参数覆盖
        self.app_id = app_id or tts_config["app_id"]
        self.token = token or tts_config["token"] 
        self.speaker = speaker or tts_config["speaker"]
        self.ws_url = kwargs.get("ws_url", tts_config["ws_url"])
        self.recv_timeout = kwargs.get("recv_timeout", 0.1)
        self.uid = None
        self.chat_id = None
        # 回调函数
        self.tts_sentence_start_callback = tts_sentence_start_callback
        self.tts_response_callback = tts_response_callback
        self.tts_sentence_end_callback = tts_sentence_end_callback
        self.tts_ended_callback = tts_ended_callback
        
        # 连接状态
        self.ws = None
        self.is_running = False
        self.session_id_str = None
        # self.session_id = session_id
        self.connection_id = None
        self.connection_lost = False  # 新增：标记连接是否丢失
        self.need_reconnect = False
        
        # TTS会话状态
        self._tts_session_active = False
        self.buffer_text = ""
        self.mood_code = 'neutral'
        self.mood_level = 3
        self.speech_rate = 3

        # 消息循环线程
        self._message_loop_thread = None
        self._receive_task = None  # 接收循环任务引用（用于取消）
        
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
                      or optional.event == EVENT_SessionFinished
                      or optional.event == EVENT_SessionCanceled):
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
    
    def _run_message_loop_thread(self):
        """在线程中直接运行消息循环"""
        # 创建新的事件循环（每个线程需要自己的事件循环）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 直接运行消息循环
            self._receive_task = loop.create_task(self.message_receive_loop())
            loop.run_until_complete(self._receive_task)
        except asyncio.CancelledError:
            logger.bind(tag="TTS").info("消息循环任务已取消")
        except Exception as e:
            logger.bind(tag="TTS").error(f"消息循环线程异常: {e}")
        finally:
            # 清理连接
            try:
                if self.ws:
                    loop.run_until_complete(self._cleanup_connection())
            except Exception as e:
                logger.debug(f"清理连接时出错: {e}")
            loop.close()
    
    def start_message_receive_loop(self, chat_id: str, user_id: str):
        """
        在独立的消息循环线程中启动TTS接收循环
        
        Args:
            chat_id: 聊天ID
            user_id: 用户ID
        """
        self.uid = user_id
        self.chat_id = chat_id
        
        # 如果消息循环线程已存在且正在运行，先停止它
        if self._message_loop_thread is not None and self._message_loop_thread.is_alive():
            logger.bind(tag="TTS").warning("已有消息循环线程在运行，先停止旧线程")
            # 设置停止标志，让循环自然退出
            self.is_running = False
            # 等待线程结束（最多等待2秒）
            self._message_loop_thread.join(timeout=2)
            if self._message_loop_thread.is_alive():
                logger.warning("旧的消息循环线程未能及时结束")
        
        # 创建新的消息循环线程
        logger.bind(tag="TTS").info("创建消息循环线程")
        self.is_running = True
        self._message_loop_thread = threading.Thread(target=self._run_message_loop_thread, daemon=True)
        self._message_loop_thread.start()
        logger.bind(tag="TTS").info("TTS消息接收循环线程已启动")
    
    async def _tts_start_connection(self, websocket):
        """TTS开始连接"""
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent).as_bytes()
        optional = TTSOptional(event=EVENT_Start_Connection).as_bytes()
        payload = str.encode("{}")
        return await self._send_tts_event(websocket, header, optional, payload)

    async def _tts_start_session(self, websocket, speaker, session_id, mood_code='neutral', mood_level=3, speech_rate=3):
        """TTS开始会话"""
        logger.bind(tag="TTS").info(f"===========TTS开始会话: {session_id} with mood_code={mood_code}, mood_level={mood_level}, speech_rate={speech_rate}")
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_StartSession, sessionId=session_id).as_bytes()
        payload = get_tts_payload_bytes(uid=self.uid, event=EVENT_StartSession, speaker=speaker, mood_code=mood_code, mood_level=mood_level, speech_rate=speech_rate)
        return await self._send_tts_event(websocket, header, optional, payload)

    async def _tts_send_text(self, ws, speaker: str, text: str, session_id, mood_code='neutral', mood_level=3, speech_rate=3):
        """TTS发送文本"""
        logger.bind(tag="TTS").info(f"===========TTS发送文本: {text} with mood_code={mood_code}, mood_level={mood_level}, speech_rate={speech_rate}")
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_TaskRequest, sessionId=session_id).as_bytes()
        payload = get_tts_payload_bytes(uid=self.uid, event=EVENT_TaskRequest, text=text, speaker=speaker, mood_code=mood_code, mood_level=mood_level, speech_rate=speech_rate)
        return await self._send_tts_event(ws, header, optional, payload)
    
    async def _tts_finish_session(self, ws, session_id):
        """TTS结束会话"""
        logger.bind(tag="TTS").info(f"===========TTS结束会话: {session_id}")
        self._tts_session_active = False
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_FinishSession, sessionId=session_id).as_bytes()
        payload = str.encode('{}')
        return await self._send_tts_event(ws, header, optional, payload)
    
    def cleanup_background(self):
        """
        停止消息循环线程并清理资源
        
        注意：调用此方法后，消息循环线程将停止
        """
        try:
            # 设置停止标志，让消息循环自然退出
            self.is_running = False
            
            # 等待消息循环线程结束（线程内部会自动清理连接）
            if self._message_loop_thread is not None and self._message_loop_thread.is_alive():
                logger.bind(tag="TTS").info("等待消息循环线程结束")
                self._message_loop_thread.join(timeout=3)
                if self._message_loop_thread.is_alive():
                    logger.warning("消息循环线程未能及时结束")
                else:
                    logger.bind(tag="TTS").info("消息循环线程已结束")
            
            logger.bind(tag="TTS").info("TTS客户端后台清理完成")
        except Exception as e:
            logger.error(f"停止消息循环失败: {e}")
    
    async def _tts_cancel_session(self, ws, session_id):
        """TTS取消会话"""
        logger.bind(tag="TTS").info(f"===========TTS取消会话: {session_id}")
        self._tts_session_active = False
        header = TTSHeader(message_type=FULL_CLIENT_REQUEST,
                          message_type_specific_flags=MsgTypeFlagWithEvent,
                          serial_method=JSON).as_bytes()
        optional = TTSOptional(event=EVENT_CancelSession, sessionId=session_id).as_bytes()
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
    
    async def set_tts_params(self, mood_code='neutral', mood_level=3, speech_rate=3):
        """设置TTS参数"""
        logger.bind(tag="TTS").info(f"设置TTS参数: mood_code={mood_code}, mood_level={mood_level}, speech_rate={speech_rate}")
        # if self._tts_session_active == False:
        #     # 开始会话
        #     self.mood_code = mood_code
        #     self.mood_level = mood_level
        #     self.speech_rate = speech_rate
        #     # self.session_id_str = str(uuid.uuid4()).replace('-', '')
        #     # self.session_id.value = self.session_id_str.encode('utf-8')
        #     # await self._tts_start_session(self.ws, self.speaker, self.session_id_str, mood_code, mood_level, speech_rate)
        # else:
        #     if self.mood_code == mood_code and self.mood_level == mood_level and self.speech_rate == speech_rate:
        #         return
        #     self.mood_code = mood_code
        #     self.mood_level = mood_level
        #     self.speech_rate = speech_rate
            # await self._tts_finish_session(self.ws, self.session_id_str)
    
    async def _connect_tts_server(self):
        """建立TTS服务器连接和会话"""
        logger.bind(tag="TTS").info(f"建立TTS服务器连接: {self.ws_url}")
        self._tts_session_active = False
        self.is_running = False
        self.log_id = self._gen_log_id()
        
        ws_header = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.token,
            "X-Api-Resource-Id": 'volc.service_type.10029',
            "X-Api-Session-Id": 'seed-tts-2.0',
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Tt-Logid": self.log_id,
        }
        
        # 建立WebSocket连接
        self.ws = await websockets.connect(self.ws_url, additional_headers=ws_header,
                                           ping_interval=5,        # 更频繁的 ping（原来是 120s）
                                           ping_timeout=3,         # 更短的超时（原来是 60s）
                                           close_timeout=2,        # 更短的关闭超时
                                           max_queue=1024,         # 增大队列（原来是 32）
                                           compression=None,        # 已禁用压缩
                                           max_size=1000000000,    # 保持大消息支持
                                           )
        
        # 开始连接
        await self._tts_start_connection(self.ws)
        res = self._parse_tts_response(await self.ws.recv())
        logger.bind(tag="TTS").info(f"TTS连接响应: event={res.optional.event}")
        
        if res.optional.event != EVENT_ConnectionStarted:
            raise RuntimeError("TTS连接失败")
        
        self.connection_id = res.optional.connectionId
        
        # 开始会话
        self.session_id_str = str(uuid.uuid4()).replace('-', '')
        # self.session_id.value = self.session_id_str.encode('utf-8')
        await self._tts_start_session(self.ws, self.speaker, self.session_id_str, self.mood_code, self.mood_level, self.speech_rate)
        res = self._parse_tts_response(await self.ws.recv())
        logger.bind(tag="TTS").info(f"TTS会话响应: event={res.optional.event}")
        if res.optional.event != EVENT_SessionStarted:
            raise RuntimeError('连接TTS会话启动失败')
        
        self.is_running = True
        self._tts_session_active = True
        logger.info("TTS连接和会话建立成功")
    
    async def message_receive_loop(self):
        """
        接收音频数据循环
        设计原则：在连接时开始，在断开时结束
        - 连接建立后开始接收消息
        - 会话级错误时，重新连接TTS服务器并继续循环
        - 连接级错误时，退出循环
        """
        try:
            # 建立TTS服务器连接
            await self._connect_tts_server()
            logger.bind(tag="TTS").info("TTS消息接收循环已启动")
            
            # 连接建立后，开始接收消息循环
            # 循环条件：运行中且连接正常
            while self.is_running and self.is_connected():
                try:
                    # 接收消息（带超时）
                    try:
                        res = self._parse_tts_response(
                            await asyncio.wait_for(self.ws.recv(), timeout=self.recv_timeout)
                        )
                    except asyncio.TimeoutError:
                        # 超时是正常的，继续等待
                        # 检查是否需要重连
                        # logger.bind(tag="TTS").info(f"检测到超时，need_reconnect: {self.need_reconnect}")
                        if self.need_reconnect:
                            logger.bind(tag="TTS").info("检测到需要重连，重新连接TTS服务器")
                            await self._connect_tts_server()
                            self.need_reconnect = False
                        continue
                    
                    logger.debug(
                        f"TTS响应: cur session_id={self.session_id_str}, "
                        f"event_session_id={res.optional.sessionId}, "
                        f"event={res.optional.event}, type={res.header.message_type}"
                    )
                    
                    # 处理各种TTS事件
                    if res.optional.event == EVENT_TTSResponse and res.header.message_type == AUDIO_ONLY_RESPONSE:
                        if res.payload:
                            # 触发TTS响应回调
                            if self.tts_response_callback:
                                await safe_call(self.tts_response_callback, res.payload, res.optional.sessionId)
                    
                    elif res.optional.event == EVENT_TTSSentenceStart:
                        logger.bind(tag="TTS").info(f"TTS句子开始: {res.optional.event}")
                        json_data = json.loads(res.payload_json)
                        text = json_data.get("text", "")
                        # 第一次开始合成时触发开始回调
                        if self.tts_sentence_start_callback:
                            await safe_call(self.tts_sentence_start_callback, {"text": text}, res.optional.sessionId)
                    
                    elif res.optional.event == EVENT_TTSSentenceEnd:
                        logger.bind(tag="TTS").info(f"TTS句子结束: {res.optional.event}")
                        if self.tts_sentence_end_callback:
                            await safe_call(self.tts_sentence_end_callback, res.optional.sessionId)
                    
                    elif res.optional.event == EVENT_SessionStarted:
                        logger.bind(tag="TTS").info(f"TTS会话开始: {res.optional.event}")
                        self._tts_session_active = True
                    
                    elif res.optional.event == EVENT_SessionCanceled:
                        logger.bind(tag="TTS").info(f"TTS会话取消: {res.optional.event}")
                        self._tts_session_active = False
                        # 会话取消后，重新连接TTS服务器
                        await self._connect_tts_server()
                    
                    elif res.optional.event == EVENT_SessionFailed:
                        logger.bind(tag="TTS").error(f"TTS会话失败: {res.optional.event}")
                        self._tts_session_active = False
                        if self.tts_ended_callback:
                            await safe_call(self.tts_ended_callback, res.optional.sessionId)
                        # 会话失败后，重新连接TTS服务器
                        await self._connect_tts_server()
                    
                    elif res.optional.event == EVENT_SessionFinished:
                        logger.bind(tag="TTS").info(f"TTS会话结束: {res.optional.event}")
                        # 重新开始会话（不重新连接，只重新开始会话）
                        await self._tts_start_session(
                            self.ws, self.speaker, self.session_id_str, 
                            self.mood_code, self.mood_level, self.speech_rate
                        )
                        if self.tts_ended_callback:
                            await safe_call(self.tts_ended_callback, res.optional.sessionId)
                    
                    elif res.optional.event == EVENT_ConnectionFailed:
                        logger.bind(tag="TTS").error(f"TTS连接失败: {res.optional.event}")
                        # 连接失败，尝试重新连接
                        await self._connect_tts_server()
                    
                    elif res.optional.event == EVENT_ConnectionFinished:
                        logger.bind(tag="TTS").info(f"TTS连接结束: {res.optional.event}")
                        # 连接结束，尝试重新连接
                        await self._connect_tts_server()
                
                except websockets.exceptions.ConnectionClosedOK:
                    # 正常关闭，退出循环
                    logger.bind(tag="TTS").info("TTS WebSocket连接正常关闭")
                    break
                
                except (websockets.exceptions.ConnectionClosed, 
                        websockets.exceptions.ConnectionClosedError) as e:
                    # 连接异常关闭，尝试重新连接
                    logger.bind(tag="TTS").warning(
                        f"TTS WebSocket连接异常关闭, log_id={self.log_id}, "
                        f"code={getattr(e, 'code', None)}, reason={getattr(e, 'reason', None)}"
                    )
                    try:
                        await self._connect_tts_server()
                    except Exception as reconnect_error:
                        logger.bind(tag="TTS").error(f"重新连接TTS服务器失败: {reconnect_error}")
                        # 重连失败，退出循环
                        break
                
                except asyncio.CancelledError:
                    # 任务被取消，退出循环
                    logger.bind(tag="TTS").info("TTS接收任务已取消")
                    break
                
                except Exception as e:
                    # 其他异常，记录日志
                    logger.bind(tag="TTS").error(f"接收TTS音频数据失败: {e}")
                    # 检查连接状态，如果连接断开则尝试重连
                    if not self.is_connected():
                        logger.bind(tag="TTS").info("连接已断开，尝试重新连接TTS服务器")
                        try:
                            await self._connect_tts_server()
                        except Exception as reconnect_error:
                            logger.bind(tag="TTS").error(f"重新连接TTS服务器失败: {reconnect_error}")
                            # 重连失败，退出循环
                            break
                    # 如果连接正常，继续接收（可能是临时错误）
                    continue
        
        except asyncio.CancelledError:
            logger.bind(tag="TTS").info("TTS接收任务已取消")
        
        except Exception as e:
            logger.bind(tag="TTS").error(f"TTS接收循环出现错误: {e}")
        
        finally:
            # 清理状态
            self.is_running = False
            self._tts_session_active = False
            logger.bind(tag="TTS").info("TTS消息接收循环已结束")
    
    async def _cleanup_connection(self):
        """清理连接相关资源（不重置重连状态）"""
        # 关闭WebSocket连接
        if self.ws:
            try:
                # 尝试正常结束会话和连接
                # if self.session_id.value:
                #     try:
                #         await self._tts_finish_session(self.ws, self.session_id.value)
                #     except:
                #         pass
                try:
                    await self._tts_finish_connection(self.ws)
                except:
                    pass
                await self.ws.close()
            except Exception as e:
                logger.debug(f"关闭TTS WebSocket时出错: {e}")
            self.ws = None
            
        # 重置会话相关状态
        logger.info(f"重置TTS会话相关状态: {self.session_id_str}")
        self._tts_session_active = False
        self.buffer_text = ""
        self.connection_id = None
        # 注意：不在这里重置 connection_lost，因为重连时需要保持这个状态
    
    async def send_text_chunk(self, text: str, start: bool = False, end: bool = False):
        """
        发送文本片段进行流式合成（异步队列版本）
        
        Args:
            text: 文本片段
        """
        try:
            # 过滤掉换行符、空格、单双引号
            text = re.sub(r'[\n\r\s"\'（）]', '', text)
            text = text.replace("...", "，")
            text = text.replace("~", "。")
            self.buffer_text += text
            if self.is_connected() == False or self._tts_session_active == False:
                logger.bind(tag="TTS").info(f"TTS会话未激活，跳过发送: {text[:50]}...")
                # self.cleanup_background()
                # self.start_message_receive_loop(self.chat_id, self.uid)
                self.need_reconnect = True
                # self.session_id_str = str(uuid.uuid4()).replace('-', '')
                # self.session_id.value = self.session_id_str.encode('utf-8')
                # await self._tts_start_session(self.ws, self.speaker, self.session_id_str, self.mood_code, self.mood_level, self.speech_rate)
                return
            if len(self.buffer_text) > 0:
                await self._tts_send_text(self.ws, self.speaker, self.buffer_text, self.session_id_str, self.mood_code, self.mood_level, self.speech_rate)
                self.buffer_text = ""
            if end:
                logger.bind(tag="TTS").info(f"TTS句子结束: {text}")
                await self._tts_finish_session(self.ws, self.session_id_str)
            logger.bind(tag="TTS").debug(f"文本已加入发送队列: {text[:50]}...")
        except Exception as e:
            logger.error(f"发送文本片段失败: {e}")
    
    async def user_input_interruption(self):
        """用户输入中断"""
        pass
        # if self.is_connected() == False:
        #     return
        # if self.is_running == False:
        #     return
        # if self._tts_session_active == True:
        #     await self._tts_cancel_session(self.ws, self.session_id_str)
        # await self._tts_finish_connection(self.ws)
        # self.need_reconnect = True
    
    async def cleanup(self):
        """清理资源"""
        try:
            self.is_running = False
            await self._cleanup_connection()
            logger.debug("TTS客户端已清理")
        except Exception as e:
            logger.error(f"清理TTS客户端时出错: {e}")

    
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            return self.ws is not None and self._is_websocket_open()
        except Exception as e:
            logger.debug(f"检查连接状态时出错: {e}")
            return False
    
    def _is_websocket_open(self) -> bool:
        """检查WebSocket是否开启"""
        try:
            if self.ws is None:
                return False
            
            # 检查是否有state属性 (新版websockets)
            if hasattr(self.ws, 'state'):
                # 导入State枚举
                try:
                    from websockets.protocol import State
                    if self.ws.state == State.OPEN:
                        return True
                    else:
                        return False
                except ImportError:
                    # 如果导入失败，尝试其他方法
                    pass
            
            # 检查是否有closed属性 (旧版websockets)
            if hasattr(self.ws, 'closed'):
                return not self.ws.closed
            
            # 检查是否有open属性 (某些版本)
            if hasattr(self.ws, 'open'):
                return self.ws.open
            
            # 如果以上都没有，尝试通过其他方式检查
            # 检查是否有close_code属性，如果有且不为None，说明连接已关闭
            if hasattr(self.ws, 'close_code'):
                return self.ws.close_code is None
            
            # 最后的兜底方案，假设连接是开启的
            logger.warning("无法确定WebSocket连接状态，假设连接正常")
            return True
            
        except Exception as e:
            logger.debug(f"检查WebSocket状态时出错: {e}")
            return False
