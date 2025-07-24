import multiprocessing
import asyncio
import logging
import json
import time
import queue
from typing import Dict, Any, Callable, Optional
from enum import Enum
from abc import ABC, abstractmethod

from .doubao_client.dialog_session import DialogSession
from .aura_client.vad_client import VADClient
from .aura_client.asr_client import ASRClient
# from .doubao_client.asr_client import AsrClient
# from .doubao_client.asr_client_new import AsrClient
from .doubao_client.tts_client import TtsClient
from .message_processor_text import MessageProcessorText
from utils.utils import start_performance_point, end_performance_point, safe_call
from muttering_data.mutter_index import get_muttering_file_path, MutteringType
from api_protocol.constant import *
from agents.aura_memory.message_store import MessageStore, Message
from agents.prompts.check_response_prompt import CHECK_RESPONSE_PROMPT
from configuration.config import get_chat_model_by_type
from langchain_core.messages import SystemMessage
from .task_manager import TaskManager, TaskType, TaskStateType

logger = logging.getLogger(__name__)

class DialogSessionType(Enum):
    """音频客户端类型枚举"""
    E2E_SESSION = "e2e_session"  # 端到端语音对话
    ALT_SESSION = "alt_session"  # 集联语音对话

SESSION_TYPES = [DialogSessionType.E2E_SESSION, DialogSessionType.ALT_SESSION]
# SESSION_TYPES = [DialogSessionType.E2E_SESSION]
# SESSION_TYPES = [DialogSessionType.ALT_SESSION]

class LLMClient(ABC):
    """LLM客户端包装器"""
    def __init__(self, 
                 input_queue,
                 output_queue,
                 is_process_running):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
        self.text_processor = MessageProcessorText(
            websocket_send_callback=self._text_processor_callback
        )
        
    @staticmethod
    def process_entry(input_queue, output_queue, is_process_running):
        asyncio.run(LLMClient.main(input_queue, output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = LLMClient(
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                await client.text_processor.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.text_processor.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "interruption":
                if client.is_process_running.value:
                    await client.text_processor.user_input_interruption()
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    await client.text_processor.handle_text_message({"message": msg["data"]})
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应"""
        self.output_queue.put(message)

class TTSClient(ABC):
    """TTS客户端包装器"""
    def __init__(self, 
                 input_queue,
                 output_queue,
                 is_process_running):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
        self.tts_client = TtsClient(
            tts_sentence_start_callback=self._llm_on_tts_sentence_start,
            tts_response_callback=self._llm_on_tts_response,
            tts_sentence_end_callback=self._llm_on_tts_sentence_end,
            tts_ended_callback=self._llm_on_tts_ended
        )
        self.is_llm_tts_running = True
    
    @staticmethod
    def process_entry(input_queue, output_queue, is_process_running):
        asyncio.run(TTSClient.main(input_queue, output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = TTSClient(
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                await client.tts_client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.tts_client.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input_start":
                if client.is_process_running.value:
                    await client.tts_client.send_text_chunk(msg["data"], start=True, end=False)
            elif isinstance(msg, dict) and msg.get("type") == "input_chunk":
                if client.is_process_running.value:
                    await client.tts_client.send_text_chunk(msg["data"])
            elif isinstance(msg, dict) and msg.get("type") == "input_end":
                if client.is_process_running.value:
                    await client.tts_client.send_text_chunk(msg["data"], start=False, end=True)
            elif isinstance(msg, dict) and msg.get("type") == "interruption":
                if client.is_process_running.value:
                    await client.tts_client.user_input_interruption()
    
    # TTS类事件回调方法
    async def _llm_on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.debug(f"LLM TTS句子开始: {text}")
        self.is_llm_tts_running = True
        self.output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
    
    async def _llm_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.debug("LLM TTS句子结束")
        self.output_queue.put({"event": ServerEvent.TTSSentenceEnd})
    
    async def _llm_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        self.output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload})
    
    async def _llm_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.debug("LLM TTS合成结束")
        self.is_llm_tts_running = False
        self.output_queue.put({"event": ServerEvent.TTSEnded})

class LLM_TTSClient(ABC):
    """TTS客户端包装器"""
    def __init__(self, 
                 input_queue,
                 output_queue,
                 is_process_running):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
        self.text_processor = MessageProcessorText(
            websocket_send_callback=self._text_processor_callback
        )
        self.tts_client = TtsClient(
            tts_sentence_start_callback=self._llm_on_tts_sentence_start,
            tts_response_callback=self._llm_on_tts_response,
            tts_sentence_end_callback=self._llm_on_tts_sentence_end,
            tts_ended_callback=self._llm_on_tts_ended
        )
        self.is_llm_tts_running = True
        self.llm_is_chat_started = False
        self.timestamp = 0
    
    @staticmethod
    def process_entry(input_queue, output_queue, is_process_running):
        asyncio.run(LLM_TTSClient.main(input_queue, output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = LLM_TTSClient(
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                await client.text_processor.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                await client.tts_client.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.tts_client.cleanup()
                await client.text_processor.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "interruption":
                if client.is_process_running.value:
                    await client.text_processor.user_input_interruption()
                    await client.tts_client.user_input_interruption()
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    client.timestamp = int(time.time() * 1000)
                    logger.debug(f"input: {msg['data']} at {client.timestamp}ms")
                    await client.text_processor.handle_text_message({"message": msg["data"]})
                    logger.info(f"handle_text_message: {msg['data']}")
                    logger.debug(f"handle_text_message delay: {int(time.time() * 1000) - client.timestamp}ms")
    
    # TTS类事件回调方法
    async def _llm_on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.debug(f"LLM TTS句子开始: {text}")
        self.is_llm_tts_running = True
        self.output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
        logger.debug(f"LLM TTS delay: {int(time.time() * 1000) - self.timestamp}ms")
    
    async def _llm_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.debug("LLM TTS句子结束")
        self.output_queue.put({"event": ServerEvent.TTSSentenceEnd})
    
    async def _llm_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        self.output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload})
    
    async def _llm_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.debug("LLM TTS合成结束")
        self.is_llm_tts_running = False
        self.output_queue.put({"event": ServerEvent.TTSEnded})
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应"""
        if message.get("event") == ServerEvent.ChatResponse:
            if self.llm_is_chat_started:
                await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""))
            else:
                self.llm_is_chat_started = True
                logger.debug(f"LLM delay: {int(time.time() * 1000) - self.timestamp}ms")
                await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""), start=True, end=False)
        elif message.get("event") == ServerEvent.ChatEnded:
            self.llm_is_chat_started = False
            await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""), start=False, end=True)
        self.output_queue.put(message)

class E2EClient(ABC):
    """端到端语音对话客户端包装器"""
    
    def __init__(self, 
                 input_queue,
                 asr_output_queue,
                 llm_output_queue,
                 tts_output_queue,
                 is_process_running):
        self.input_queue = input_queue
        self.asr_output_queue = asr_output_queue
        self.llm_output_queue = llm_output_queue
        self.tts_output_queue = tts_output_queue
        self.is_process_running = is_process_running

        self.dialog_session = DialogSession(
            asr_start_callback=self._on_asr_info,
            asr_response_callback=self._on_asr_response,
            asr_end_callback=self._on_asr_ended,
            tts_sentence_start_callback=self._e2e_on_tts_sentence_start,
            tts_response_callback=self._e2e_on_tts_response,
            tts_sentence_end_callback=self._e2e_on_tts_sentence_end,
            tts_ended_callback=self._e2e_on_tts_ended,
            chat_response_callback=self._e2e_on_chat_response,
            chat_end_callback=self._e2e_on_chat_ended
        )
    
    @staticmethod
    def process_entry(input_queue, asr_output_queue, llm_output_queue, tts_output_queue, is_process_running):
        asyncio.run(E2EClient.main(input_queue, asr_output_queue, llm_output_queue, tts_output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, asr_output_queue, llm_output_queue, tts_output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = E2EClient(
            input_queue=input_queue,
            asr_output_queue=asr_output_queue,
            llm_output_queue=llm_output_queue,
            tts_output_queue=tts_output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                await client.dialog_session.start(msg["data"]["chat_id"], msg["data"]["user_id"])
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                await client.dialog_session.cleanup()
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "input":
                if client.is_process_running.value:
                    await client.dialog_session.process_audio_chunk(msg["data"])
            # elif isinstance(msg, dict) and msg.get("type") == "interruption":
            #     if client.is_process_running.value:
            #         await client.dialog_session.user_input_interruption()
    
    # TTS类事件回调方法
    async def _e2e_on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.debug(f"E2E TTS句子开始: {text}")
        self.tts_output_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}})
    
    async def _e2e_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.debug("E2E TTS句子结束")
        self.tts_output_queue.put({"event": ServerEvent.TTSSentenceEnd})
    
    async def _e2e_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        self.tts_output_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload})
    
    async def _e2e_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.debug("E2E TTS合成结束")
        self.tts_output_queue.put({"event": ServerEvent.TTSEnded})
    
    # ASR类事件回调方法
    async def _on_asr_info(self) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.debug("ASR识别出首字")
        self.asr_output_queue.put({"event": ServerEvent.ASRInfo})
    
    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        results = payload.get("results", [])
        if results:
            for result in results:
                text = result.get("text", "")
                is_interim = result.get("is_interim", False)
                logger.debug(f"ASR识别结果: {text} (临时: {is_interim})")
                self.asr_output_queue.put({
                    "event": ServerEvent.ASRResponse,
                    "payload_msg": {"results": [{"text": text, "is_interim": is_interim}]}
                })
    
    async def _on_asr_ended(self) -> None:
        """ASR结束事件回调"""
        self.asr_output_queue.put({"event": ServerEvent.ASREnded})
    
    # Chat类事件回调方法
    async def _e2e_on_chat_response(self, payload: Dict[str, Any]) -> None:
        """聊天响应事件回调"""
        content = payload.get("content", "")
        logger.debug(f"E2E收到聊天响应: {content[:10]}...")
        self.llm_output_queue.put({"event": ServerEvent.ChatResponse, "payload_msg": {"content": content}})
    
    async def _e2e_on_chat_ended(self) -> None:
        """聊天结束事件回调"""
        logger.debug("E2E聊天响应结束")
        self.llm_output_queue.put({"event": ServerEvent.ChatEnded})

class MessageProcessorAudio:
    """
    多进程版音频消息处理器
    """
    instance = None
    @staticmethod
    def get_instance():
        if MessageProcessorAudio.instance is None:
            MessageProcessorAudio.instance = MessageProcessorAudio()
        return MessageProcessorAudio.instance
    
    def __init__(self):
        self.chat_id = None
        self.user_id = None
        self.websocket_send_callback = None
        # 启动消息处理任务
        logger.info("启动消息处理任务")
        self.message_tasks = asyncio.gather(
            self.send_vad_message(),
            # self.send_asr_message(),
            self.send_e2e_asr_message(),
            # self.send_llm_message(),
            # self.send_tts_message(),
            self.send_llm_tts_message()
        )

        # 启动ASR子进程
        # self.asr_input_queues = multiprocessing.Queue()
        # self.asr_output_queue = multiprocessing.Queue()
        # self.asr_is_process_running = multiprocessing.Value('b', False)
        # logger.info("启动ASR子进程")
        # self.asr_process = multiprocessing.Process(
        #     target=ASRClient.process_entry,
        #     args=(self.asr_input_queues, self.asr_output_queue, self.asr_is_process_running)
        # )
        # self.asr_process.start()

        self.vad_input_queues = multiprocessing.Queue()
        self.vad_output_queue = multiprocessing.Queue()
        self.vad_is_process_running = multiprocessing.Value('b', False)
        logger.info("启动VAD子进程")
        self.vad_process = multiprocessing.Process(
            target=VADClient.process_entry,
            args=(self.vad_input_queues, self.vad_output_queue, self.vad_is_process_running)
        )
        self.vad_process.start()

        # # 启动LLM子进程
        # self.llm_input_queues = multiprocessing.Queue()
        # self.llm_output_queue = multiprocessing.Queue()
        # self.llm_is_process_running = multiprocessing.Value('b', False)
        # logger.info("启动LLM子进程")
        # self.llm_process = multiprocessing.Process(
        #     target=LLMClient.process_entry,
        #     args=(self.llm_input_queues, self.llm_output_queue, self.llm_is_process_running)
        # )
        # self.llm_process.start()

        # # 启动TTS子进程
        # self.tts_input_queues = multiprocessing.Queue()
        # self.tts_output_queue = multiprocessing.Queue()
        # self.tts_is_process_running = multiprocessing.Value('b', False)
        # logger.info("启动TTS子进程")
        # self.tts_process = multiprocessing.Process(
        #     target=TTSClient.process_entry,
        #     args=(self.tts_input_queues, self.tts_output_queue, self.tts_is_process_running)
        # )
        # self.tts_process.start()

        # 启动LLM_TTS子进程
        self.llm_tts_input_queues = multiprocessing.Queue()
        self.llm_tts_output_queue = multiprocessing.Queue()
        self.llm_tts_is_process_running = multiprocessing.Value('b', False)
        logger.info("启动LLM_TTS子进程")
        self.llm_tts_process = multiprocessing.Process(
            target=LLM_TTSClient.process_entry,
            args=(self.llm_tts_input_queues, self.llm_tts_output_queue, self.llm_tts_is_process_running)
        )
        self.llm_tts_process.start()

        # 启动E2E子进程
        self.e2e_input_queues = multiprocessing.Queue()
        self.e2e_asr_output_queue = multiprocessing.Queue()
        self.e2e_llm_output_queue = multiprocessing.Queue()
        self.e2e_tts_output_queue = multiprocessing.Queue()
        self.e2e_is_process_running = multiprocessing.Value('b', False)
        logger.info("启动E2E子进程")
        self.e2e_process = multiprocessing.Process(
            target=E2EClient.process_entry,
            args=(self.e2e_input_queues, self.e2e_asr_output_queue, self.e2e_llm_output_queue, self.e2e_tts_output_queue, self.e2e_is_process_running)
        )
        self.e2e_process.start()

        # 中间结果
        self.asr_result = ""
        self.asr_is_started = False
        self.asr_lock = asyncio.Lock()

        self.llm_is_chat_started = False
        self.active_client = None
        self.message_tasks = None

    async def handle_message(self, message_data: Dict[str, Any]):
        """
        分发消息到两个 client 进程
        """
        if message_data.get("event") == ClientEvent.SayHello:
            pass
        elif message_data.get("event") == ClientEvent.TaskRequest:
            if "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
            else:
                return {"success": False, "error": "payload_msg is required"}
            # asr_input_data = payload_msg
            # self.asr_input_queues.put({"type": "input", "data": asr_input_data})
            vad_input_data = payload_msg
            self.vad_input_queues.put({"type": "input", "data": vad_input_data})
            e2e_input_data = payload_msg
            self.e2e_input_queues.put({"type": "input", "data": e2e_input_data})
        elif message_data.get("event") == ClientEvent.SpeakEnded:
            if self.asr_is_started:
                async with self.asr_lock:
                    self.asr_is_started = False
                # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
                self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
                if self.websocket_send_callback:
                    await self.websocket_send_callback({"event": ServerEvent.ASREnded})
            else:
                logger.debug("SpeakEnded，但ASR未开始")
        return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}
    
    async def send_vad_message(self):
        """
        轮询VAD输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.vad_output_queue.get)
                    if msg.get("event") == ServerEvent.ASRInfo:
                        if not self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = True
                            # self.llm_input_queues.put({"type": "interruption"})
                            # self.tts_input_queues.put({"type": "interruption"})
                            self.llm_tts_input_queues.put({"type": "interruption"})
                        else:
                            logger.debug("VAD识别出首字，但ASR已开始")
                            continue
                    elif msg.get("event") == ServerEvent.ASREnded:
                        if self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = False
                            # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
                            self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
                        else:
                            logger.debug("VAD识别结束，但ASR未开始")
                            continue
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送VAD消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("VAD消息处理任务已取消")
    
    async def send_e2e_asr_message(self):
        """
        轮询ASR输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.e2e_asr_output_queue.get)
                    if msg.get("event") == ServerEvent.ASRInfo:
                        if not self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = True
                            # self.llm_input_queues.put({"type": "interruption"})
                            # self.tts_input_queues.put({"type": "interruption"})
                            self.llm_tts_input_queues.put({"type": "interruption"})
                        else:
                            logger.debug("E2E ASR识别出首字，但ASR已开始")
                            continue
                    elif msg.get("event") == ServerEvent.ASRResponse:
                        if self.asr_is_started == False:
                            continue
                        self.asr_result = msg.get("payload_msg", {}).get("results", [{}])[0].get("text", "")
                    elif msg.get("event") == ServerEvent.ASREnded:
                        if self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = False
                            # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
                            self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
                        else:
                            logger.debug("E2E ASR识别结束，但ASR未开始")
                            continue
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送ASR消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("ASR消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"ASR消息处理任务异常: {e}")
            raise  # 重新抛出异常

    async def send_asr_message(self):
        """
        轮询ASR结束队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.asr_output_queue.get)
                    if msg.get("event") == ServerEvent.ASRInfo:
                        if not self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = True
                            # self.llm_input_queues.put({"type": "interruption"})
                            # self.tts_input_queues.put({"type": "interruption"})
                            self.llm_tts_input_queues.put({"type": "interruption"})
                        else:
                            logger.debug("ASR识别出首字，但ASR已开始")
                            continue
                    elif msg.get("event") == ServerEvent.ASRResponse:
                        self.asr_result += msg.get("payload_msg", {}).get("results", [{}])[0].get("text", "")
                    elif msg.get("event") == ServerEvent.ASREnded:
                        if self.asr_is_started:
                            async with self.asr_lock:
                                self.asr_is_started = False
                            # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
                            self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
                        else:
                            logger.debug("ASR识别结束，但ASR未开始")
                            continue
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送ASR消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("ASR消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"ASR消息处理任务异常: {e}")
            raise  # 重新抛出异常
    
    async def send_llm_message(self):
        """
        轮询LLM输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.llm_output_queue.get)
                    if msg.get("event") == ServerEvent.ChatResponse:
                        if self.llm_is_chat_started:
                            self.llm_input_queues.put({"type": "input_chunk", "data": msg.get("payload_msg", {}).get("content", "")})
                        else:
                            self.llm_is_chat_started = True
                            self.tts_input_queues.put({"type": "input_start", "data": msg.get("payload_msg", {}).get("content", "")})
                    elif msg.get("event") == ServerEvent.ChatEnded:
                        self.llm_is_chat_started = False
                        self.tts_input_queues.put({"type": "input_end", "data": msg.get("payload_msg", {}).get("content", "")})
                    logger.debug(f"收到LLM消息: {msg}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                    await asyncio.sleep(0.01)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送LLM消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("LLM消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"LLM消息处理任务异常: {e}")
            raise  # 重新抛出异常
    
    async def send_tts_message(self):
        """
        轮询TTS输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.tts_output_queue.get)
                    logger.debug(f"收到TTS消息: {msg}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                    await asyncio.sleep(0.01)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送TTS消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("TTS消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"TTS消息处理任务异常: {e}")
            raise  # 重新抛出异常
    
    async def send_llm_tts_message(self):
        """
        轮询TTS输出队列，有消息就发给 websocket
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    msg = await loop.run_in_executor(None, self.llm_tts_output_queue.get)
                    logger.debug(f"收到LLM_TTS消息: {msg.get('event')}")
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                    await asyncio.sleep(0.01)
                except asyncio.TimeoutError:
                    # 超时继续循环
                    continue
                except Exception as e:
                    logger.error(f"发送LLM_TTS消息失败: {e}")
                    # 短暂等待后继续
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("LLM_TTS消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"LLM_TTS消息处理任务异常: {e}")
            raise  # 重新抛出异常
    # async def send_e2e_message(self):
    #     """
    #     轮询E2E输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         loop = asyncio.get_event_loop()
    #         while True:
    #             msg = await loop.run_in_executor(None, self.e2e_output_queue.get)
    #             logger.debug(f"收到E2E消息: {msg}")
    #             if self.websocket_send_callback:
    #                 await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         pass
    #     except Exception as e:
    #         logger.error(f"发送E2E消息失败: {e}")
    
    async def start(self, chat_id: str, user_id: str, websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = chat_id
        self.user_id = user_id
        self.websocket_send_callback = websocket_send_callback
        logger.info(f"MessageProcessorAudio启动完成: chat_id={self.chat_id}")
        # self.asr_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.vad_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.e2e_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # self.llm_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # self.tts_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.llm_tts_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # with E2E
        while not self.e2e_is_process_running.value or not self.llm_tts_is_process_running.value or not self.vad_is_process_running.value:
            await asyncio.sleep(0.1)
        # with E2E and VAD and LLM and TTS
        # while not self.e2e_is_process_running.value or not self.vad_is_process_running.value or not self.llm_is_process_running.value or not self.tts_is_process_running.value:
        #     await asyncio.sleep(0.1)
        # with ASR
        # while not self.asr_is_process_running.value or not self.llm_tts_is_process_running.value or not self.vad_is_process_running.value:
        #     await asyncio.sleep(0.1)
        logger.info("MessageProcessorAudio启动完成")
    
    async def cleanup(self):
        logger.info(f"开始清理MessageProcessorAudio: chat_id={self.chat_id}")
        self.websocket_send_callback = None
        # self.asr_input_queues.put({"type": "stop"})
        self.vad_input_queues.put({"type": "stop"})
        self.e2e_input_queues.put({"type": "stop"})
        # self.llm_input_queues.put({"type": "stop"})
        # self.tts_input_queues.put({"type": "stop"})
        self.llm_tts_input_queues.put({"type": "stop"})
        # with E2E
        while self.e2e_is_process_running.value or self.llm_tts_is_process_running.value or self.vad_is_process_running.value:
            await asyncio.sleep(0.1)
        # with E2E and VAD and LLM and TTS
        # while self.e2e_is_process_running.value or self.vad_is_process_running.value or self.llm_is_process_running.value or self.tts_is_process_running.value:
        #     await asyncio.sleep(0.1)
        # with ASR
        # while self.asr_is_process_running.value or self.llm_tts_is_process_running.value or self.vad_is_process_running.value:
        #     await asyncio.sleep(0.1)
        logger.info("MessageProcessorAudio清理完成")
