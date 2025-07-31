import time
import asyncio
import multiprocessing
from loguru import logger
from typing import Dict, Any
import numpy as np
from api_protocol.constant import *
from utils.utils import atomic_compare_and_set
from .vad_engine import VADEngine
from multiprocessing import Process, Queue
from .base_client import BaseClient

class VADSplitLocal(BaseClient):
    """
    VAD Split客户端，用于处理TTS音频的智能断句
    接收TTS音频数据，发送给VAD服务进行时间戳检测，然后插入TTSSentenceStart和TTSSentenceEnd事件
    """
    def __init__(self, input_queue: multiprocessing.Queue, output_client_queue: multiprocessing.Queue, is_process_running: Any, process_timer: Any):
        self.audio_sample_rate = 24 # 24000Hz
        super().__init__()
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
        self.audio_buffer_lock = asyncio.Lock()
        self.audio_start_sample = 0  # 当前音频流的开始时间（毫秒）
        self.audio_position = 0    # 当前音频位置（毫秒）
        self.audio_position_lock = asyncio.Lock()
        self.audio_min_offset = 120 # 音频最小偏移量 = 50ms
    
    @staticmethod
    def process_entry(input_queue, output_client_queue, is_process_running, process_timer):
        asyncio.run(VADSplitLocal.main(input_queue, output_client_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, output_client_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = VADSplitLocal(
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
        logger.bind(tag="DELAY").info(f"VADSplit收到TTS音频响应: {len(audio_array)} samples")
        async with self.audio_buffer_lock:
            self.audio_buffer = np.concatenate([self.audio_buffer, audio_array])
        logger.bind(tag="DELAY").info(f"VADSplit audio buffer size: {len(self.audio_buffer)} samples")
        # 发送给VAD进行断句检测
        await self._send_audio_to_vad(payload)
    
    async def _handle_tts_sentence_start(self, payload: Dict[str, Any], session_id: str = None):
        """处理TTS句子开始事件"""
        text = payload.get("text", "")
        logger.bind(tag="DELAY").info(f"VADSplit收到TTS句子开始: {text} delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
        self.current_session_id = session_id
        async with self.audio_position_lock:
            self.audio_position = 0
        async with self.audio_buffer_lock:
            del self.audio_buffer
            self.audio_buffer = np.array([], dtype=np.int16)
        # self._split_text_by_punctuation(text)
        self.is_tts_started = True
        await self._output_tts_sentence_start(text, self.current_session_id)
    
    async def _handle_tts_sentence_end(self, session_id: str = None):
        """处理TTS句子结束事件"""
        logger.bind(tag="DELAY").info("VADSplit收到TTS句子结束")
        self.is_tts_started = False
        async with self.audio_position_lock:
            last_position = self.audio_position
            self.audio_position = len(self.audio_buffer)
        # 直接输出剩余的音频数据
        logger.bind(tag="DELAY").info(f"total size {len(self.audio_buffer)}, delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
        if last_position < len(self.audio_buffer):
            async with self.audio_buffer_lock:
                audio_buffer = self.audio_buffer[last_position:]
            logger.bind(tag="DELAY").info(f"VADSplit输出音频数据块 in handle_tts_sentence_end: {last_position} - {self.audio_position}, delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
            if not self.is_tts_start_sent:
                await self._output_tts_sentence_start("", self.current_session_id)
            await self._output_audio_chunk(audio_buffer.tobytes(), self.current_session_id)
            await self._output_tts_sentence_end(self.current_session_id)
        self.audio_start_sample += len(self.audio_buffer)
    
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
    
    def consumer_worker(self, input_queue, output_queue, is_process_running):
        """常驻worker进程：负责音频处理"""
        engine = VADEngine(input_sample_rate=self.audio_sample_rate * 1000)
        while True:
            msg = input_queue.get()
            if isinstance(msg, dict) and msg.get("type") == "start":
                engine.start()
                is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                engine.cleanup()
                is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if is_process_running.value:
                    result = engine.process_audio_chunk(msg["data"])
                    if result is not None:
                        output_queue.put(result)
    
    async def _send_audio_to_vad(self, audio_data: bytes):
        """发送音频数据给VAD进行断句检测"""
        try:
            self.internal_input_queue.put({"type": "input", "data": audio_data})
        except Exception as e:
            logger.error(f"VADSplit发送音频数据给VAD失败: {e}")
    
    async def _handle_server_response(self, response: Dict[str, Any]):
        """处理VAD响应，根据时间戳插入断句事件"""
        try:
            if not self.is_tts_started:
                return
            logger.bind(tag="DELAY").info(f"VADSplit收到VAD响应: {response}")
            # 解析VAD时间戳数据
            timestamps = response[0][0]
            if not self.is_vad_started:
                self.is_vad_started = True
                logger.bind(tag="DELAY").info(f"VADSplit vad started: {timestamps}")
                if timestamps[0] == -1:
                    self.audio_start_sample = 0
                else:
                    self.audio_start_sample = timestamps[0] * self.audio_sample_rate
            logger.bind(tag="DELAY").info(f"VADSplit audio start sample: {self.audio_start_sample}")
            if timestamps[0] == -1:
                end_position = timestamps[1] * self.audio_sample_rate
            else:
                end_position = timestamps[0] * self.audio_sample_rate
            if end_position < self.audio_start_sample:
                logger.bind(tag="BASE").info(f"VADSplit收到VAD响应，但音频开始时间小于VAD开始时间: {end_position} < {self.audio_start_sample}")
                return
            offset_position = end_position - self.audio_start_sample
            async with self.audio_position_lock:
                if offset_position < self.audio_position:
                    logger.bind(tag="BASE").info(f"VADSplit收到VAD响应，但音频位置小于VAD开始时间: {offset_position} < {self.audio_position}")
                    return
                if offset_position - 120 < self.audio_position:
                    logger.bind(tag="BASE").info(f"VADSplit收到VAD响应，但音频位置与VAD开始时间约等于相同: {self.audio_position} == {offset_position}")
                    return
                last_position = self.audio_position
                self.audio_position = offset_position
            if not self.is_tts_start_sent:
                await self._output_tts_sentence_start("", self.current_session_id)
            async with self.audio_buffer_lock:
                audio_buffer = self.audio_buffer[last_position:offset_position]
            await self._output_audio_chunk(audio_buffer.tobytes(), self.current_session_id)
            await self._output_tts_sentence_end(self.current_session_id)
            logger.bind(tag="DELAY").info(f"VADSplit输出音频数据块 in handle_server_response: {last_position} - {offset_position} size: {len(audio_buffer)}, delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
        except Exception as e:
            logger.bind(tag="BASE").error(f"VADSplit处理VAD响应失败: {e}")
    
    async def start(self, chat_id: str, user_id: str) -> bool:
        is_success = await super().start(chat_id, user_id)
        if not is_success:
            return False
        self.internal_input_queue.put({"type": "start"})
        while not self.internal_is_process_running.value:
            await asyncio.sleep(0.1)
        return True
    
    async def cleanup(self) -> None:
        """清理资源"""
        await super().cleanup()
        self.internal_input_queue.put({"type": "stop"})
        while self.internal_is_process_running.value:
            await asyncio.sleep(0.1)
        self.is_tts_started = False
        self.is_vad_started = False
        self.is_tts_start_sent = False
        self.current_session_id = None
        # 音频相关
        async with self.audio_buffer_lock:
            del self.audio_buffer
            self.audio_buffer = np.array([], dtype=np.int16)
        self.audio_start_sample = 0  # 当前音频流的开始时间（毫秒）
        self.audio_position = 0    # 当前音频位置（毫秒）
