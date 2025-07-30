import time
import asyncio
import multiprocessing
from loguru import logger
from typing import Any
from api_protocol.constant import *
from utils.utils import atomic_compare_and_set
from .vad_engine import VADEngine

class VADLocal:
    """VAD客户端"""
    def __init__(self, input_queue: multiprocessing.Queue, llm_input_queue: multiprocessing.Queue, asr_is_started: Any, asr_lock: Any, output_client_queue: multiprocessing.Queue, is_process_running: Any, process_timer: Any):
        self.input_queue = input_queue
        self.llm_input_queue = llm_input_queue
        self.asr_is_started = asr_is_started
        self.asr_lock = asr_lock
        self.output_client_queue = output_client_queue
        self.is_process_running = is_process_running
        self.process_timer = process_timer
        self.vad_engine = VADEngine()
    
    @staticmethod
    def process_entry(input_queue, llm_input_queue, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        asyncio.run(VADLocal.main(input_queue, llm_input_queue, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, llm_input_queue, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = VADLocal(
            input_queue=input_queue,
            llm_input_queue=llm_input_queue,
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
                    result = client.vad_engine.process_audio_chunk(msg["data"])
                    if result is not None:
                        if result[0][0][0] == -1:
                            if atomic_compare_and_set(client.asr_is_started, client.asr_lock, True, False):
                                client.output_client_queue.put({"event": ServerEvent.ASREnded})
                                client.llm_input_queue.put({"type": "run"})
                                client.process_timer.value = time.time()
                                logger.bind(tag="DELAY").info("VAD识别结束")
                            else:
                                logger.bind(tag="DELAY").warning("VAD识别结束，但ASR未开始")
    
    async def start(self, chat_id: str, user_id: str) -> bool:
        self.vad_engine.start()
        return True
    
    async def cleanup(self) -> None:
        """清理资源"""
        self.vad_engine.cleanup()
