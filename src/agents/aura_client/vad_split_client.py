import ssl
import time
import asyncio
import websockets
from .config import *
import multiprocessing
from loguru import logger
from typing import Dict, Any, List
import json

from .base_client import BaseClient
from .config import vad_config
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response
from utils.utils import atomic_compare_and_set

class VADSplitClient(BaseClient):
    """
    VAD Split客户端，用于处理TTS音频的智能断句
    接收TTS音频数据，发送给VAD服务进行时间戳检测，然后插入TTSSentenceStart和TTSSentenceEnd事件
    """
    
    def __init__(self, config: Dict[str, Any], input_queue: multiprocessing.Queue, output_client_queue: multiprocessing.Queue, is_process_running: Any, process_timer: Any):
        super().__init__(config)
        self.input_queue = input_queue
        self.output_client_queue = output_client_queue
        self.is_process_running = is_process_running
        self.process_timer = process_timer
        self.is_tts_started = False
        self.current_text = ""
        self.current_session_id = None
        self.audio_buffer = bytearray()
        self.audio_start_time = 0  # 当前音频流的开始时间（毫秒）
        self.audio_position = 0    # 当前音频位置（毫秒）
        self.vad_timestamps = []   # VAD返回的时间戳列表
        self.pending_sentence_start = False
        self.text_segments = []    # 分割后的文本段落
        self.current_segment_index = 0  # 当前文本段落索引
    
    async def task_request(self, audio: bytes) -> None:
        """TaskRequest - 客户端事件ID: 200"""
        if not self.is_running:
            logger.bind(tag="BASE").warning("VADSplit客户端未启动")
            return
        # 发送前检查SSL连接状态
        if self._is_websocket_closed():
            logger.warning("发送音频数据前检测到SSL连接已关闭")
            raise websockets.exceptions.ConnectionClosed(None, 1000, "SSL connection is closed")
        
        task_request = client_generate_request(
            payload_data=audio,
            message_type=CLIENT_AUDIO_ONLY_REQUEST,
            message_type_specific_flags=MSG_WITH_EVENT,
            serial_method=NO_SERIALIZATION,
            compression_type=GZIP,
            event=ClientEvent.TaskRequest,
            session_id=self.session_id,
            skip_audio_compression=True
        )
        try:
            await self.ws.send(task_request)
        except (websockets.exceptions.ConnectionClosed, 
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.WebSocketException,
                OSError, 
                ConnectionResetError, 
                BrokenPipeError,
                ssl.SSLError) as e:
            # 捕获所有可能的连接相关异常
            error_msg = str(e).lower()
            if "ssl" in error_msg or "connection" in error_msg:
                logger.warning(f"发送音频数据时检测到连接问题: {e}")
                raise websockets.exceptions.ConnectionClosed(None, 1000, f"Connection error during send: {e}")
            else:
                # 重新抛出其他类型的异常
                raise
    
    @staticmethod
    def process_entry(input_queue, output_client_queue, is_process_running, process_timer):
        asyncio.run(VADSplitClient.main(input_queue, output_client_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, output_client_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = VADSplitClient(
            config=vad_split_config,
            input_queue=input_queue,
            output_client_queue=output_client_queue,
            is_process_running=is_process_running,
            process_timer=process_timer
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                client.is_process_running.value = await client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                logger.bind(tag="BASE").info("VADSplit客户端启动")
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.cleanup()
                client.is_process_running.value = False
                logger.bind(tag="BASE").info("VADSplit客户端停止")
            elif isinstance(msg, dict) and msg.get("event") == ServerEvent.TTSSentenceStart:
                if client.is_process_running.value:
                    await client._handle_tts_sentence_start(msg["payload_msg"], msg.get("session_id"))
            elif isinstance(msg, dict) and msg.get("event") == ServerEvent.TTSSentenceEnd:
                if client.is_process_running.value:
                    await client._handle_tts_sentence_end(msg.get("session_id"))
            elif isinstance(msg, dict) and msg.get("event") == ServerEvent.TTSResponse:
                if client.is_process_running.value:
                    await client._handle_tts_response(msg["payload_msg"], msg.get("session_id"))
            elif isinstance(msg, dict) and msg.get("event") == ServerEvent.TTSEnded:
                if client.is_process_running.value:
                    await client._handle_tts_ended(msg.get("session_id"))
    
    async def _handle_tts_response(self, payload: bytes, session_id: str = None):
        """处理TTS音频响应事件"""
        # 将音频数据添加到缓冲区
        self.audio_buffer.extend(payload)
        
        # 计算音频时长（16kHz, 16bit = 2字节/样本）
        audio_duration_ms = len(payload) / (16000 * 2) * 1000  # 转换为毫秒
        
        # 更新音频位置
        self.audio_position += audio_duration_ms
        
        # 当缓冲区达到一定大小时，发送给VAD进行断句检测
        if len(self.audio_buffer) >= 3200:  # 假设16kHz, 16bit, 100ms的数据
            await self._send_audio_to_vad()
    
    async def _handle_tts_sentence_start(self, payload: Dict[str, Any], session_id: str = None):
        """处理TTS句子开始事件"""
        text = payload.get("text", "")
        logger.debug(f"VADSplit收到TTS句子开始: {text}")
        self.current_text = text
        self.is_tts_started = True
        self.current_session_id = session_id
        
        # 分割文本
        self.text_segments = self._split_text_by_punctuation(text)
        self.current_segment_index = 0
        logger.debug(f"VADSplit分割文本为{len(self.text_segments)}个段落: {self.text_segments}")
        
        # 重置音频位置和状态
        self.audio_start_time = self.audio_position
        self.audio_position = 0
        self.vad_timestamps = []
        self.pending_sentence_start = False
    
    async def _handle_tts_sentence_end(self, session_id: str = None):
        """处理TTS句子结束事件"""
        logger.debug("VADSplit收到TTS句子结束")
        
        # 直接输出剩余的音频数据
        if len(self.audio_buffer) > 0:
            await self._output_audio_chunk(self.audio_buffer, self.current_session_id)
            self.audio_buffer.clear()
        
        # 直接发送TTSSentenceEnd事件，不等待VAD结果
        output_msg = {
            "event": ServerEvent.TTSSentenceEnd
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
        logger.debug("VADSplit直接输出TTSSentenceEnd事件")
        
        self.is_tts_started = False
        self.current_text = ""
        self.text_segments = []
        self.current_segment_index = 0
        self.audio_start_time = 0
        self.audio_position = 0
        self.vad_timestamps = []
        self.pending_sentence_start = False
    
    async def _handle_tts_ended(self, session_id: str = None):
        """处理TTS结束事件"""
        logger.debug("VADSplit收到TTS结束")
        
        # 发送剩余的音频数据给VAD
        if len(self.audio_buffer) > 0:
            await self._send_audio_to_vad()
        
        # 等待VAD处理完成
        await asyncio.sleep(0.1)
        
        # 输出剩余的音频数据
        if len(self.audio_buffer) > 0:
            await self._output_audio_chunk(self.audio_buffer, self.current_session_id)
            self.audio_buffer.clear()
        
        # 发送TTSEnded事件（这个事件仍然立即发送，因为它是整个TTS会话的结束）
        output_msg = {
            "event": ServerEvent.TTSEnded
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
        
        self.is_tts_started = False
        self.current_text = ""
        self.text_segments = []
        self.current_segment_index = 0
        self.audio_start_time = 0
        self.audio_position = 0
        self.vad_timestamps = []
        self.pending_sentence_start = False
    
    async def _output_audio_chunk(self, audio_data: bytes, session_id: str = None):
        """输出音频数据块"""
        output_msg = {
            "event": ServerEvent.TTSResponse,
            "payload_msg": audio_data
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
    
    async def _send_audio_to_vad(self):
        """发送音频数据给VAD进行断句检测"""
        if len(self.audio_buffer) == 0:
            return
        
        # 发送音频数据给VAD
        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        
        try:
            await self.task_request(audio_data)
            logger.debug(f"VADSplit发送{len(audio_data)}字节音频数据给VAD")
        except Exception as e:
            logger.error(f"VADSplit发送音频数据给VAD失败: {e}")
    
    async def _handle_server_response(self, response: Dict[str, Any]):
        """处理服务器响应"""
        try:
            # 处理事件类型响应
            if response.get('event') is None:
                return
            event_id = response.get('event')
            
            # Connect类事件 (50-52)
            if event_id == ServerEvent.ConnectionStarted:
                logger.bind(tag="BASE").info("VADSplit连接建立成功")
            elif event_id == ServerEvent.ConnectionFailed:
                logger.bind(tag="BASE").error("VADSplit连接建立失败")
            elif event_id == ServerEvent.ConnectionFinished:
                logger.bind(tag="BASE").info("VADSplit连接已结束")
            
            # Session类事件 (150-153)
            elif event_id == ServerEvent.SessionStarted:
                logger.bind(tag="BASE").info("VADSplit会话启动成功")
            elif event_id == ServerEvent.SessionFinished:
                logger.bind(tag="BASE").info("VADSplit会话已结束")
            elif event_id == ServerEvent.SessionFailed:
                logger.bind(tag="BASE").error("VADSplit会话失败")
            
            # VAD类事件 - 新的VADResponse格式
            elif event_id == ServerEvent.VADResponse:
                logger.bind(tag="DELAY").debug(f"VADSplit收到VAD响应: {response}")
                await self._handle_vad_response(response)
            
            else:
                logger.bind(tag="DELAY").warning(f"VADSplit收到未知事件: {event_id}")
                
        except Exception as e:
            logger.error(f"VADSplit处理服务器响应失败: {e}")
    
    async def _handle_vad_response(self, response: Dict[str, Any]):
        """处理VAD响应，根据时间戳插入断句事件"""
        try:
            # 解析VAD时间戳数据
            payload = response.get("payload", {})
            timestamps = payload.get("timestamps", [])
            if not timestamps:
                return
            
            # 添加时间戳到列表
            self.vad_timestamps.extend(timestamps)
            
            # 处理时间戳，插入断句事件
            await self._process_vad_timestamps()
            
        except Exception as e:
            logger.error(f"VADSplit处理VAD响应失败: {e}")
    
    async def _process_vad_timestamps(self):
        """处理VAD时间戳，根据VAD结果决定音频输出和断句时机"""
        if not self.is_tts_started or not self.text_segments:
            return
        
        # 检查是否有新的时间戳需要处理
        for timestamp in self.vad_timestamps:
            if isinstance(timestamp, list) and len(timestamp) >= 2:
                start_time = timestamp[0]  # 语音开始时间（毫秒）
                end_time = timestamp[1]    # 语音结束时间（毫秒）
                
                # 检查是否应该插入TTSSentenceStart
                if start_time >= 0 and not self.pending_sentence_start:
                    # 计算音频位置是否到达了开始时间
                    if self.audio_position >= start_time:
                        # 获取当前文本段落
                        current_segment = self._get_current_text_segment()
                        if current_segment:
                            # 插入TTSSentenceStart事件
                            output_msg = {
                                "event": ServerEvent.TTSSentenceStart,
                                "payload_msg": {"text": current_segment}
                            }
                            if self.current_session_id:
                                output_msg["session_id"] = self.current_session_id
                            self.output_client_queue.put(output_msg)
                            logger.bind(tag="DELAY").info(f"VADSplit在{start_time}ms处插入TTSSentenceStart事件，文本: {current_segment}")
                            self.pending_sentence_start = True
                
                # 检查是否应该插入TTSSentenceEnd
                if end_time >= 0 and self.pending_sentence_start:
                    # 计算音频位置是否到达了结束时间
                    if self.audio_position >= end_time:
                        # 输出到结束时间点的音频数据作为一个完整的TTSResponse
                        audio_bytes_to_output = int(end_time / 1000 * 16000 * 2)  # 转换为字节数
                        if len(self.audio_buffer) >= audio_bytes_to_output:
                            audio_chunk = self.audio_buffer[:audio_bytes_to_output]
                            await self._output_audio_chunk(audio_chunk, self.current_session_id)
                            # 移除已输出的音频数据
                            self.audio_buffer = self.audio_buffer[audio_bytes_to_output:]
                        
                        # 插入TTSSentenceEnd事件
                        output_msg = {
                            "event": ServerEvent.TTSSentenceEnd
                        }
                        if self.current_session_id:
                            output_msg["session_id"] = self.current_session_id
                        self.output_client_queue.put(output_msg)
                        logger.bind(tag="DELAY").info(f"VADSplit在{end_time}ms处插入TTSSentenceEnd事件")
                        self.pending_sentence_start = False
                        
                        # 移动到下一个文本段落
                        self.current_segment_index += 1
                        
                        # 如果还有剩余音频数据和文本段落，插入新的TTSSentenceStart
                        if len(self.audio_buffer) > 0 and self.current_segment_index < len(self.text_segments):
                            next_segment = self._get_current_text_segment()
                            if next_segment:
                                output_msg = {
                                    "event": ServerEvent.TTSSentenceStart,
                                    "payload_msg": {"text": next_segment}
                                }
                                if self.current_session_id:
                                    output_msg["session_id"] = self.current_session_id
                                self.output_client_queue.put(output_msg)
                                logger.bind(tag="DELAY").info(f"VADSplit插入新的TTSSentenceStart事件，文本: {next_segment}")
                                self.pending_sentence_start = True
        
        # 清理已处理的时间戳
        self.vad_timestamps = []
    
    def _split_text_by_punctuation(self, text: str) -> List[str]:
        """根据标点符号分割文本"""
        import re
        # 定义中文和英文的句末标点符号
        sentence_endings = r'[。！？.!?]'
        # 分割文本
        segments = re.split(sentence_endings, text)
        # 过滤空字符串并添加标点符号
        result = []
        for i, segment in enumerate(segments):
            if segment.strip():
                # 找到对应的标点符号
                if i < len(segments) - 1:
                    # 查找下一个标点符号
                    match = re.search(sentence_endings, text[text.find(segment) + len(segment):])
                    if match:
                        result.append(segment.strip() + match.group())
                    else:
                        result.append(segment.strip())
                else:
                    result.append(segment.strip())
        return result
    
    def _get_current_text_segment(self) -> str:
        """获取当前文本段落"""
        if self.current_segment_index < len(self.text_segments):
            return self.text_segments[self.current_segment_index]
        return "" 