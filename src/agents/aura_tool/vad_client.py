import os
import time
import asyncio
import multiprocessing
from loguru import logger
from typing import Any, Dict
from api_protocol.constant import *
from utils.utils import atomic_compare_and_set
from .vad_engine import VADEngine
from .base_client import BaseClient

class VADLocal(BaseClient):
    """VAD客户端"""
    def __init__(self, input_queue: multiprocessing.Queue, asr_input_queues: multiprocessing.Queue, asr_is_started: Any, asr_lock: Any, output_client_queue: multiprocessing.Queue, is_process_running: Any, process_timer: Any):
        super().__init__()
        self.input_queue = input_queue
        self.asr_input_queues = asr_input_queues
        self.asr_is_started = asr_is_started
        self.asr_lock = asr_lock
        self.output_client_queue = output_client_queue
        self.is_process_running = is_process_running
        self.process_timer = process_timer
    
    @staticmethod
    def process_entry(input_queue, asr_input_queues, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        asyncio.run(VADLocal.main(input_queue, asr_input_queues, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, asr_input_queues, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = VADLocal(
            input_queue=input_queue,
            asr_input_queues=asr_input_queues,
            asr_is_started=asr_is_started,
            asr_lock=asr_lock,
            output_client_queue=output_client_queue,
            is_process_running=is_process_running,
            process_timer=process_timer
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                client.is_process_running.value = await client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                logger.bind(tag="BASE").info("VAD客户端启动")
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.cleanup()
                client.is_process_running.value = False
                logger.bind(tag="BASE").info("VAD客户端停止")
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    client.internal_input_queue.put({"type": "input", "data": msg["data"]})
    
    async def _handle_server_response(self, response: Dict[str, Any]):
        if response[0][0][0] == -1:
            if atomic_compare_and_set(self.asr_is_started, self.asr_lock, True, False):
                self.asr_input_queues.put({"type": "speak_ended"})
                self.process_timer.value = time.time()
                logger.bind(tag="DELAY").info("VAD识别结束")
            else:
                logger.bind(tag="DELAY").warning("VAD识别结束，但ASR未开始")
        elif response[0][0][1] == -1:
            self.asr_is_started.value = True
            self.asr_input_queues.put({"type": "speak_started"})
    
    def consumer_worker(self, input_queue, output_queue, is_process_running):
        """常驻worker进程：负责音频处理"""
        engine = VADEngine()
        while True:
            msg = input_queue.get()
            if isinstance(msg, dict) and msg.get("type") == "start":
                engine.start(os.path.join(os.path.dirname(__file__), "model/vad"))
                is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                engine.cleanup()
                is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if is_process_running.value:
                    result = engine.process_audio_chunk(msg["data"])
                    if result is not None:
                        output_queue.put(result)
    
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

