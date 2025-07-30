import ssl
import time
import asyncio
import websockets
from .config import *
import multiprocessing
from loguru import logger
from typing import Dict, Any, List
import json
import numpy as np
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
        self.is_vad_started = False
        self.is_tts_start_sent = False
        self.current_session_id = None
        # 音频相关
        self.audio_buffer = np.array([], dtype=np.int16)
        self.audio_start_time = 0  # 当前音频流的开始时间（毫秒）
        self.audio_position = 0    # 当前音频位置（毫秒）
        self.audio_sample_rate = 16 # 16000Hz
        # 文本相关
        # self.text_segments = []    # 分割后的文本段落
    
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
            # skip_audio_compression=True
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
        audio_array = np.frombuffer(payload, dtype=np.int16)
        # logger.bind(tag="DELAY").info(f"VADSplit收到TTS音频响应: {len(audio_array)}字节")
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_array])
        # 发送给VAD进行断句检测
        await self._send_audio_to_vad(payload)
    
    async def _handle_tts_sentence_start(self, payload: Dict[str, Any], session_id: str = None):
        """处理TTS句子开始事件"""
        text = payload.get("text", "")
        logger.bind(tag="DELAY").info(f"VADSplit收到TTS句子开始: {text} delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
        self.current_session_id = session_id
        self.audio_position = 0
        # self._split_text_by_punctuation(text)
        self.is_tts_started = True
        await self._output_tts_sentence_start(text, self.current_session_id)
    
    async def _handle_tts_sentence_end(self, session_id: str = None):
        """处理TTS句子结束事件"""
        logger.bind(tag="DELAY").info("VADSplit收到TTS句子结束")
        self.is_tts_started = False
        # 直接输出剩余的音频数据
        begin_index = int(self.audio_position * self.audio_sample_rate)
        audio_buffer = self.audio_buffer[begin_index:]
        if len(audio_buffer) > 0:
            if not self.is_tts_start_sent:
                await self._output_tts_sentence_start("", self.current_session_id)
            await self._output_audio_chunk(audio_buffer.tobytes(), self.current_session_id)
            await self._output_tts_sentence_end(self.current_session_id)
            self.audio_start_time = int(len(self.audio_buffer) / self.audio_sample_rate)
            del self.audio_buffer
            self.audio_buffer = np.array([], dtype=np.int16)
    
    async def _handle_tts_ended(self, session_id: str = None):
        """处理TTS结束事件"""
        logger.debug("VADSplit收到TTS结束")
        output_msg = {
            "event": ServerEvent.TTSEnded
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
    
    async def _output_audio_chunk(self, audio_data: bytes, session_id: str = None):
        """输出音频数据块"""
        output_msg = {
            "event": ServerEvent.TTSResponse,
            "payload_msg": audio_data
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
    
    async def _output_tts_sentence_start(self, text: str, session_id: str = None):
        """输出TTS句子开始事件"""
        output_msg = {
            "event": ServerEvent.TTSSentenceStart,
            "payload_msg": {"text": text}
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
        self.is_tts_start_sent = True
    
    async def _output_tts_sentence_end(self, session_id: str = None):
        """输出TTS句子结束事件"""
        output_msg = {
            "event": ServerEvent.TTSSentenceEnd
        }
        if session_id:
            output_msg["session_id"] = session_id
        self.output_client_queue.put(output_msg)
        self.is_tts_start_sent = False
    
    async def _send_audio_to_vad(self, audio_data: bytes):
        """发送音频数据给VAD进行断句检测"""
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
                logger.bind(tag="DELAY").info(f"VADSplit收到VAD响应: {response}")
                await self._handle_vad_response(response)
            else:
                logger.bind(tag="DELAY").warning(f"VADSplit收到未知事件: {event_id}")
                
        except Exception as e:
            logger.error(f"VADSplit处理服务器响应失败: {e}")
    
    async def _handle_vad_response(self, response: Dict[str, Any]):
        """处理VAD响应，根据时间戳插入断句事件"""
        try:
            logger.bind(tag="DELAY").info(f"VADSplit收到VAD响应: {self.is_tts_started} delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
            if not self.is_tts_started:
                return
            # 解析VAD时间戳数据
            vad_response = response.get("payload_msg", {})
            timestamps = vad_response[0][0]
            if not self.is_vad_started:
                self.is_vad_started = True
                if timestamps[0] == -1:
                    self.audio_start_time = 0
                else:
                    self.audio_start_time = timestamps[0]
            
            if timestamps[0] == -1:
                end_time = timestamps[1]
            else:
                end_time = timestamps[0]
            if end_time < self.audio_start_time:
                logger.bind(tag="BASE").info(f"VADSplit收到VAD响应，但音频开始时间小于VAD开始时间: {end_time} < {self.audio_start_time}")
                return
            offset_time = end_time - self.audio_start_time
            if offset_time < self.audio_position:
                logger.bind(tag="BASE").info(f"VADSplit收到VAD响应，但音频位置小于VAD开始时间: {offset_time} < {self.audio_position}")
                return
            if not self.is_tts_start_sent:
                await self._output_tts_sentence_start("", self.current_session_id)
            begin_index = int(self.audio_position * self.audio_sample_rate)
            end_index = int(offset_time * self.audio_sample_rate)
            await self._output_audio_chunk(self.audio_buffer[begin_index:end_index].tobytes(), self.current_session_id)
            await self._output_tts_sentence_end(self.current_session_id)
            logger.bind(tag="DELAY").info(f"VADSplit输出音频数据块: {self.audio_position} - {offset_time}")
            self.audio_position = offset_time
        except Exception as e:
            logger.bind(tag="BASE").error(f"VADSplit处理VAD响应失败: {e}")
    
    async def cleanup(self) -> None:
        """清理资源"""
        await super().cleanup()
        self.is_tts_started = False
        self.is_vad_started = False
        self.is_tts_start_sent = False
        self.current_session_id = None
        # 音频相关
        del self.audio_buffer
        self.audio_buffer = np.array([], dtype=np.int16)
        self.audio_start_time = 0  # 当前音频流的开始时间（毫秒）
        self.audio_position = 0    # 当前音频位置（毫秒）
    
    # def _split_text_by_punctuation(self, text: str):
    #     """根据标点符号分割文本"""
    #     import re
    #     # 定义中文和英文的句末标点符号
    #     sentence_endings = r'[。！？.!?]'
    #     # 分割文本
    #     segments = re.split(sentence_endings, text)
    #     # 过滤空字符串并添加标点符号
    #     self.text_segments = []
    #     for i, segment in enumerate(segments):
    #         if segment.strip():
    #             # 找到对应的标点符号
    #             if i < len(segments) - 1:
    #                 # 查找下一个标点符号
    #                 match = re.search(sentence_endings, text[text.find(segment) + len(segment):])
    #                 if match:
    #                     self.text_segments.append(segment.strip() + match.group())
    #                 else:
    #                     self.text_segments.append(segment.strip())
    #             else:
    #                 self.text_segments.append(segment.strip())
    
    # def _get_current_text_segment(self) -> str:
    #     """获取当前文本段落"""
    #     if len(self.text_segments) > 0:
    #         return self.text_segments.pop(0)
    #     return "" 
