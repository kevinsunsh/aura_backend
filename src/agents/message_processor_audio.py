import multiprocessing
import ctypes
import asyncio
from loguru import logger
import json
import time
import queue
from typing import Dict, Any, Callable
from enum import Enum
from abc import ABC

from .doubao_client.dialog_session import DialogSession
# from .aura_client.vad_client import VADClient
# from .aura_client.vad_split_client import VADSplitClient
# from .aura_client.asr_client import ASRClient
from .aura_tool.vad_client import VADLocal
from .aura_tool.vad_split_client import VADSplitLocal
# from .doubao_client.asr_client import AsrClient
# from .doubao_client.asr_client import AsrClient
from .doubao_client.tts_client import TtsClient
from .doubao_client.doubao_config import speaker_config
from .message_processor_text import MessageProcessorText
from .msg_preandpost_processor import MessagePreAndPostProcessor
from utils.utils import start_performance_point, end_performance_point, safe_call, atomic_compare_and_set
from muttering_data.mutter_index import get_muttering_file_path, MutteringType
from api_protocol.constant import *

# class ASRClient(ABC):
#     """ASR客户端包装器"""
#     def __init__(self, 
#             input_queue,
#             prepost_input_queues,
#             llm_input_queues,
#             asr_result,
#             asr_is_started,
#             asr_lock,
#             output_client_queue,
#             is_process_running,
#             process_timer):
#         self.input_queue = input_queue
#         self.prepost_input_queues = prepost_input_queues
#         self.llm_input_queues = llm_input_queues
#         self.asr_result = asr_result
#         self.asr_is_started = asr_is_started
#         self.asr_lock = asr_lock
#         self.output_client_queue = output_client_queue
#         self.is_process_running = is_process_running
#         self.process_timer = process_timer
#         self.asr_client = AsrClient(
#             on_asr_info=self._on_asr_info,
#             on_asr_response=self._on_asr_response,
#             on_asr_ended=self._on_asr_ended
#         )
    
#     @staticmethod
#     def process_entry(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
#         asyncio.run(ASRClient.main(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer))
    
#     @staticmethod
#     async def main(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
#         loop = asyncio.get_event_loop()
#         client = ASRClient(
#             input_queue=input_queue,
#             prepost_input_queues=prepost_input_queues,
#             llm_input_queues=llm_input_queues,
#             asr_result=asr_result,
#             asr_is_started=asr_is_started,
#             asr_lock=asr_lock,
#             output_client_queue=output_client_queue,
#             is_process_running=is_process_running,
#             process_timer=process_timer
#         )
#         while True:
#             msg = await loop.run_in_executor(None, input_queue.get)
#             if isinstance(msg, dict) and msg.get("type") == "start":
#                 await client.asr_client.start()
#                 client.is_process_running.value = True
#             elif isinstance(msg, dict) and msg.get("type") == "stop":
#                 await client.asr_client.cleanup()
#                 client.is_process_running.value = False
#             elif isinstance(msg, dict) and msg.get("type") == "input":
#                 if client.is_process_running.value:
#                     await client.asr_client.process_audio_chunk(msg["data"])
#             elif isinstance(msg, dict) and msg.get("type") == "speak_ended":
#                 if client.is_process_running.value:
#                     logger.bind(tag="DELAY").info(f"ASR发送Speak end delay: {int((time.time() - client.process_timer.value) * 1000)}ms")
#                     await client.asr_client.on_speak_ended()
#             elif isinstance(msg, dict) and msg.get("type") == "speak_started":
#                 if client.is_process_running.value:
#                     await client.asr_client.on_speak_started()
    
#     # ASR类事件回调方法
#     async def _on_asr_info(self) -> None:
#         """ASR信息事件回调 - 识别出首字"""
#         logger.bind(tag="DELAY").info(f"识别ASRInfo")
#         self.output_client_queue.put({"event": ServerEvent.ASRInfo})
#         self.llm_input_queues.put({"type": "interruption"})
    
#     async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
#         """ASR响应事件回调 - 识别出文本内容"""
#         self.asr_result.value = payload.get("results", [{}])[0].get("text", "").encode("utf-8")
#         # logger.bind(tag="BASE").info(f"ASR响应: {payload}")
#         if self.asr_is_started.value:
#             self.output_client_queue.put({
#                     "event": ServerEvent.ASRResponse,
#                     "payload_msg": payload})
    
#     async def _on_asr_ended(self) -> None:
#         """ASR结束事件回调"""
#         self.output_client_queue.put({"event": ServerEvent.ASREnded})
#         self.prepost_input_queues.put({"type": "preprocess"})
#         logger.bind(tag="DELAY").info(f"ASR ASREnded delay: {int((time.time() - self.process_timer.value) * 1000)}ms")

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
                    await client.text_processor.handle_message({"message": msg["data"]})
    
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
                    await client.tts_client.send_text_chunk(msg["data"].get("text", ""), start=True, end=False)
            elif isinstance(msg, dict) and msg.get("type") == "input_chunk":
                if client.is_process_running.value:
                    await client.tts_client.send_text_chunk(msg["data"].get("text", ""))
            elif isinstance(msg, dict) and msg.get("type") == "input_end":
                if client.is_process_running.value:
                    await client.tts_client.send_text_chunk(msg["data"].get("text", ""), start=False, end=True)
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
                 asr_result,
                 output_client_queue,
                 is_process_running,
                 session_id,
                 process_timer):
        self.input_queue = input_queue
        self.asr_result = asr_result
        self.output_client_queue = output_client_queue
        self.is_process_running = is_process_running
        self.session_id = session_id
        self.text_processor = MessageProcessorText(
            websocket_send_callback=self._text_processor_callback,
            process_timer=process_timer
        )
        self.tts_client = TtsClient(
            tts_sentence_start_callback=self._llm_on_tts_sentence_start,
            tts_response_callback=self._llm_on_tts_response,
            tts_sentence_end_callback=self._llm_on_tts_sentence_end,
            tts_ended_callback=self._llm_on_tts_ended,
            session_id=self.session_id
        )
        self.is_llm_tts_running = True
        self.llm_is_chat_started = False
        self.process_timer = process_timer
    
    @staticmethod
    def process_entry(input_queue, asr_result, output_client_queue, is_process_running, session_id, process_timer):
        asyncio.run(LLM_TTSClient.main(input_queue, asr_result, output_client_queue, is_process_running, session_id, process_timer))
    
    @staticmethod
    async def main(input_queue, asr_result, output_client_queue, is_process_running, session_id, process_timer):
        loop = asyncio.get_event_loop()
        client = LLM_TTSClient(
            input_queue=input_queue,
            asr_result=asr_result,
            output_client_queue=output_client_queue,
            is_process_running=is_process_running,
            session_id=session_id,
            process_timer=process_timer,
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
            elif isinstance(msg, dict) and msg.get("type") == "run":
                if client.is_process_running.value:
                    prompts = msg["data"]
                    logger.bind(tag="DELAY").info(f"LLM TTSClient run delay: {int((time.time() - client.process_timer.value) * 1000)}ms")
                    prompts.append({"role": "user", "content": client.asr_result.value.decode("utf-8")})
                    await client.text_processor.handle_message(prompts)
    
    # TTS类事件回调方法
    async def _llm_on_tts_sentence_start(self, payload: Dict[str, Any], session_id: str) -> None:
        """TTS句子开始事件回调"""
        text = payload.get("text", "")
        logger.debug(f"LLM TTS句子开始: {text}")
        self.is_llm_tts_running = True
        # self.vad_split_input_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}, "session_id": session_id})
        self.output_client_queue.put({"event": ServerEvent.TTSSentenceStart, "payload_msg": {"text": text}, "session_id": session_id})
        logger.bind(tag="DELAY").info(f"TTSSentenceStart delay: {int((time.time() - self.process_timer.value) * 1000)}ms")

    async def _llm_on_tts_sentence_end(self, session_id: str) -> None:
        """TTS句子结束事件回调"""
        logger.debug("LLM TTS句子结束")
        # 转发给VADSplitClient
        # self.vad_split_input_queue.put({"event": ServerEvent.TTSSentenceEnd, "session_id": session_id})
        self.output_client_queue.put({"event": ServerEvent.TTSSentenceEnd, "session_id": session_id})
        logger.bind(tag="DELAY").info(f"TTSSentenceEnd delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
    
    async def _llm_on_tts_response(self, payload: bytes, session_id: str) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        # 转发给VADSplitClient
        # self.vad_split_input_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload, "session_id": session_id})
        self.output_client_queue.put({"event": ServerEvent.TTSResponse, "payload_msg": payload, "session_id": session_id})
    
    async def _llm_on_tts_ended(self, session_id: str) -> None:
        """TTS结束事件回调"""
        logger.debug("LLM TTS合成结束")
        self.is_llm_tts_running = False
        # 转发给VADSplitClient
        # self.vad_split_input_queue.put({"event": ServerEvent.TTSEnded, "session_id": session_id})
        self.output_client_queue.put({"event": ServerEvent.TTSEnded, "session_id": session_id})
    
    async def _text_processor_callback(self, message: Dict[str, Any]):
        """文本处理器回调，用于处理聊天响应"""
        if message.get("event") == ServerEvent.ChatResponseParams:
            pass
            # params = message.get("payload_msg", {}).get("params", {})
            # mood_code = params.get("mood", "neutral")
            # # 获取心情等级，如果无法转换成数字则默认为3
            # try:
            #     mood_level = int(params.get("level", 3))
            # except (ValueError, TypeError):
            #     mood_level = 3
            # # 获取语速，如果无法转换成数字则默认为3
            # try:
            #     speech_rate = int(params.get("speed", 3))
            # except (ValueError, TypeError):
            #     speech_rate = 3
            # mood_code = mood_code if mood_code in speaker_config["female_1"]["mood_code"] else "neutral"
            # await self.tts_client.set_tts_params(mood_code=mood_code, mood_level=mood_level, speech_rate=speech_rate)
        elif message.get("event") == ServerEvent.ChatResponse:
            if self.llm_is_chat_started:
                await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""))
            else:
                self.llm_is_chat_started = True
                logger.bind(tag="DELAY").info(f"ChatResponse delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
                await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""), start=True, end=False)
        elif message.get("event") == ServerEvent.ChatResponseEnd:
            self.llm_is_chat_started = False
            logger.bind(tag="DELAY").info(f"ChatResponseEnd delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
            await self.tts_client.send_text_chunk("", start=False, end=True)
        self.output_client_queue.put(message)

class E2EClient(ABC):
    """端到端语音对话客户端包装器"""
    def __init__(self, 
                 input_queue,
                 prepost_input_queues,
                 llm_input_queues,
                 asr_result,
                 asr_is_started,
                 asr_lock,
                 output_client_queue,
                 is_process_running,
                 process_timer):
        self.input_queue = input_queue
        self.prepost_input_queues = prepost_input_queues
        self.llm_input_queues = llm_input_queues
        self.asr_result = asr_result
        self.asr_is_started = asr_is_started
        self.asr_lock = asr_lock
        self.output_client_queue = output_client_queue
        self.is_process_running = is_process_running
        self.process_timer = process_timer
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
    def process_entry(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        asyncio.run(E2EClient.main(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, prepost_input_queues, llm_input_queues, asr_result, asr_is_started, asr_lock, output_client_queue, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = E2EClient(
            input_queue=input_queue,
            prepost_input_queues=prepost_input_queues,
            llm_input_queues=llm_input_queues,
            asr_result=asr_result,
            asr_is_started=asr_is_started,
            asr_lock=asr_lock,
            output_client_queue=output_client_queue,
            is_process_running=is_process_running,
            process_timer=process_timer
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
    
    async def _e2e_on_tts_sentence_end(self) -> None:
        """TTS句子结束事件回调"""
        logger.debug("E2E TTS句子结束")
    
    async def _e2e_on_tts_response(self, payload: bytes) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        logger.debug(f"E2E TTS音频响应: {payload}")
    
    async def _e2e_on_tts_ended(self) -> None:
        """TTS结束事件回调"""
        logger.debug("E2E TTS合成结束")
    
    # ASR类事件回调方法
    async def _on_asr_info(self) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.bind(tag="DELAY").info("ASR识别出首字")
        self.output_client_queue.put({"event": ServerEvent.ASRInfo})
        self.llm_input_queues.put({"type": "interruption"})
        self.asr_is_started.value = True
    
    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        self.asr_result.value = payload.get("results", [{}])[0].get("text", "").encode("utf-8")
        if self.asr_is_started.value:
            self.output_client_queue.put({
                    "event": ServerEvent.ASRResponse,
                    "payload_msg": payload})
    
    async def _on_asr_ended(self) -> None:
        """ASR结束事件回调"""
        if atomic_compare_and_set(self.asr_is_started, self.asr_lock, True, False):
            self.output_client_queue.put({"event": ServerEvent.ASREnded})
            self.prepost_input_queues.put({"type": "preprocess"})
            self.process_timer.value = time.time()
            logger.bind(tag="DELAY").info(f"E2E ASREnded")
        else:
            logger.bind(tag="DELAY").info("E2E ASREnded，但ASR未开始")
    
    # Chat类事件回调方法
    async def _e2e_on_chat_response(self, payload: Dict[str, Any]) -> None:
        """聊天响应事件回调"""
        content = payload.get("content", "")
        logger.debug(f"E2E收到聊天响应: {content[:10]}...")

    async def _e2e_on_chat_ended(self) -> None:
        """聊天结束事件回调"""
        logger.debug("E2E聊天响应结束")

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
        self.sse_started = False
        # 启动消息处理任务
        logger.info("启动消息处理任务")
        self.message_tasks = asyncio.gather(
            self.send_message(),
            # self.send_vad_message(),
            # self.send_asr_message(),
            # self.send_e2e_asr_message(),
            # self.send_llm_message(),
            # self.send_tts_message(),
            # self.send_llm_tts_message()
        )
        try:
            self.output_client_queue = multiprocessing.Queue()
            # 中间结果
            self.asr_result = multiprocessing.Array(ctypes.c_char, 1024)
            self.asr_is_started = multiprocessing.Value('b', False)
            self.asr_lock = multiprocessing.Lock()
            self.process_timer = multiprocessing.Value('d', 0)
            # 启动TTSSPLIT子进程
            # self.vad_split_input_queues = multiprocessing.Queue()
            # self.vad_split_is_process_running = multiprocessing.Value('b', False)
            # logger.bind(tag="BASE").info("启动TTSSplit子进程")
            # self.vad_split_process = multiprocessing.Process(
            #     target=VADSplitLocal.process_entry,
            #     args=(self.vad_split_input_queues, self.output_client_queue, self.vad_split_is_process_running, self.process_timer)
            # )
            # self.vad_split_process.start()
            # 启动LLM_TTS子进程
            self.llm_tts_input_queues = multiprocessing.Queue()
            self.llm_tts_is_process_running = multiprocessing.Value('b', False)
            self.llm_tts_session_id = multiprocessing.Array(ctypes.c_char, 33)
            logger.bind(tag="BASE").info("启动LLM_TTS子进程")
            self.llm_tts_process = multiprocessing.Process(
                target=LLM_TTSClient.process_entry,
                args=(self.llm_tts_input_queues, self.asr_result, self.output_client_queue,
                    self.llm_tts_is_process_running, self.llm_tts_session_id, self.process_timer)
            )
            self.llm_tts_process.start()
            # 启动预处理和后处理子进程
            self.prepost_input_queues = multiprocessing.Queue()
            self.preprocess_is_process_running = multiprocessing.Value('b', False)
            logger.bind(tag="BASE").info("启动预处理子进程")
            self.preprocess_process = multiprocessing.Process(
                target=MessagePreAndPostProcessor.process_entry,
                args=(self.prepost_input_queues, self.llm_tts_input_queues,
                    self.asr_result, self.preprocess_is_process_running, self.process_timer)
            )
            self.preprocess_process.start()
            # 启动ASR子进程
            # self.asr_input_queues = multiprocessing.Queue()
            # self.asr_is_process_running = multiprocessing.Value('b', False)
            # logger.bind(tag="BASE").info("启动ASR子进程")
            # self.asr_process = multiprocessing.Process(
            #     target=ASRClient.process_entry,
            #     args=(self.asr_input_queues, self.prepost_input_queues, self.llm_tts_input_queues, 
            #         self.asr_result, self.asr_is_started, self.asr_lock,
            #         self.output_client_queue, self.asr_is_process_running, self.process_timer)
            # )
            # self.asr_process.start()
            # 启动VAD子进程
            self.vad_input_queues = multiprocessing.Queue()
            self.vad_is_process_running = multiprocessing.Value('b', False)
            logger.bind(tag="BASE").info("启动VAD子进程")
            self.vad_process = multiprocessing.Process(
                target=VADLocal.process_entry,
                args=(self.vad_input_queues, self.prepost_input_queues,
                    self.asr_is_started, self.asr_lock, self.output_client_queue,
                    self.vad_is_process_running, self.process_timer)
            )
            self.vad_process.start()
            # 启动E2E子进程
            self.e2e_input_queues = multiprocessing.Queue()
            self.e2e_llm_output_queue = multiprocessing.Queue()
            self.e2e_tts_output_queue = multiprocessing.Queue()
            self.e2e_is_process_running = multiprocessing.Value('b', False)
            logger.bind(tag="BASE").info("启动E2E子进程")
            self.e2e_process = multiprocessing.Process(
                target=E2EClient.process_entry,
                args=(self.e2e_input_queues, self.prepost_input_queues,
                    self.llm_tts_input_queues, self.asr_result, self.asr_is_started, self.asr_lock, self.output_client_queue,
                    self.e2e_is_process_running, self.process_timer)
            )
            self.e2e_process.start()
        except Exception as e:
            logger.bind(tag="BASE").error(f"启动子进程失败: {e}")
            raise e
        
        self.llm_is_chat_started = False
        self.llm_tts_msg_count = 0
        self.sleep_time = 0
    
    async def handle_message(self, message_data: Dict[str, Any]):
        """
        分发消息到两个 client 进程
        """
        if message_data.get("event") == ClientEvent.SayHello:
            self.prepost_input_queues.put({"type": "preprocess"})
            self.asr_result.value = message_data["payload_msg"].get("content", "").encode("utf-8")
            self.process_timer.value = time.time()
            logger.bind(tag="DELAY").info(f"SayHello")
        elif message_data.get("event") == ClientEvent.TaskRequest:
            if "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
            else:
                return {"success": False, "error": "payload_msg is required"}
            # asr_input_data = payload_msg
            # self.asr_input_queues.put({"type": "input", "data": asr_input_data})
            vad_input_data = payload_msg
            self.vad_input_queues.put({"type": "input", "data": vad_input_data})
            asr_input_data = payload_msg
            self.e2e_input_queues.put({"type": "input", "data": asr_input_data})
        elif message_data.get("event") == ClientEvent.SpeakEnded:
            # logger.bind(tag="DELAY").info(f"SpeakEnded，ASR结果: {self.asr_result}")
            if atomic_compare_and_set(self.asr_is_started, self.asr_lock, True, False):
                # 原子操作成功：从True设置为False
                # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
                self.output_client_queue.put({"event": ServerEvent.ASREnded})
                # self.asr_input_queues.put({"type": "speak_ended"})
                self.prepost_input_queues.put({"type": "preprocess"})
                self.process_timer.value = time.time()
                logger.bind(tag="DELAY").info(f"SpeakEnded")
            else:
                logger.bind(tag="DELAY").info("SpeakEnded，但ASR未开始")
        elif message_data.get("event") == ClientEvent.WorldInfoActivateKeys:
            self.prepost_input_queues.put({"type": "change_world_info_activate_keys", "data": message_data.get("payload_msg", {}).get("activate_keys", [])})
        elif message_data.get("event") == ClientEvent.ChangeBotID:
            self.prepost_input_queues.put({"type": "change_bot_name", "data": message_data.get("payload_msg", {}).get("bot_name", "")})
        elif message_data.get("event") == ClientEvent.ChangeSystemPreset:
            self.prepost_input_queues.put({"type": "change_system_preset", "data": message_data.get("payload_msg", {}).get("system_preset", "")})
        return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}
    
    # async def send_asr_message(self):
    #     """
    #     轮询ASR结束队列，有消息就发给 websocket
    #     """
    #     try:
    #         loop = asyncio.get_event_loop()
    #         while True:
    #             try:
    #                 msg = await loop.run_in_executor(None, self.asr_output_queue.get)
    #                 if msg.get("event") == ServerEvent.ASRInfo:
    #                     if not self.asr_is_started:
    #                         async with self.asr_lock:
    #                             self.asr_is_started = True
    #                         # self.llm_input_queues.put({"type": "interruption"})
    #                         # self.tts_input_queues.put({"type": "interruption"})
    #                         self.llm_tts_input_queues.put({"type": "interruption"})
    #                     else:
    #                         logger.debug("ASR识别出首字，但ASR已开始")
    #                         continue
    #                 elif msg.get("event") == ServerEvent.ASRResponse:
    #                     self.asr_result += msg.get("payload_msg", {}).get("results", [{}])[0].get("text", "")
    #                 elif msg.get("event") == ServerEvent.ASREnded:
    #                     if self.asr_is_started:
    #                         async with self.asr_lock:
    #                             self.asr_is_started = False
    #                         # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
    #                         self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
    #                     else:
    #                         logger.debug("ASR识别结束，但ASR未开始")
    #                         continue
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #             except asyncio.TimeoutError:
    #                 # 超时继续循环
    #                 continue
    #             except Exception as e:
    #                 logger.error(f"发送ASR消息失败: {e}")
    #                 # 短暂等待后继续
    #                 await asyncio.sleep(0.1)
    #     except asyncio.CancelledError:
    #         logger.info("ASR消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"ASR消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_llm_message(self):
    #     """
    #     轮询LLM输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         loop = asyncio.get_event_loop()
    #         while True:
    #             try:
    #                 msg = await loop.run_in_executor(None, self.llm_output_queue.get)
    #                 if msg.get("event") == ServerEvent.ChatResponse:
    #                     if self.llm_is_chat_started:
    #                         self.llm_input_queues.put({"type": "input_chunk", "data": msg.get("payload_msg", {}).get("content", "")})
    #                     else:
    #                         self.llm_is_chat_started = True
    #                         self.tts_input_queues.put({"type": "input_start", "data": msg.get("payload_msg", {}).get("content", "")})
    #                 elif msg.get("event") == ServerEvent.ChatEnded:
    #                     self.llm_is_chat_started = False
    #                     self.tts_input_queues.put({"type": "input_end", "data": msg.get("payload_msg", {}).get("content", "")})
    #                 logger.debug(f"收到LLM消息: {msg}")
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #                 await asyncio.sleep(0.01)
    #             except asyncio.TimeoutError:
    #                 # 超时继续循环
    #                 continue
    #             except Exception as e:
    #                 logger.error(f"发送LLM消息失败: {e}")
    #                 # 短暂等待后继续
    #                 await asyncio.sleep(0.1)
    #     except asyncio.CancelledError:
    #         logger.info("LLM消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"LLM消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_tts_message(self):
    #     """
    #     轮询TTS输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         loop = asyncio.get_event_loop()
    #         while True:
    #             try:
    #                 msg = await loop.run_in_executor(None, self.tts_output_queue.get)
    #                 logger.debug(f"收到TTS消息: {msg}")
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #                 await asyncio.sleep(0.01)
    #             except asyncio.TimeoutError:
    #                 # 超时继续循环
    #                 continue
    #             except Exception as e:
    #                 logger.error(f"发送TTS消息失败: {e}")
    #                 # 短暂等待后继续
    #                 await asyncio.sleep(0.1)
    #     except asyncio.CancelledError:
    #         logger.info("TTS消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"TTS消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_vad_message(self):
    #     """
    #     轮询VAD输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         while True:
    #             should_continue, msg = await self.send_vad_message_imp()
    #             if msg:
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         logger.info("VAD消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"VAD消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_vad_message_imp(self):
    #     """
    #     轮询VAD输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         try:
    #             msg = self.vad_output_queue.get_nowait()
    #         except queue.Empty:
    #             msg = None
    #         if msg:
    #             if msg.get("event") == ServerEvent.ASRInfo:
    #                 # if not self.asr_is_started:
    #                 #     async with self.asr_lock:
    #                 #         self.asr_is_started = True
    #                 #     # self.llm_input_queues.put({"type": "interruption"})
    #                 #     # self.tts_input_queues.put({"type": "interruption"})
    #                 #     self.llm_tts_input_queues.put({"type": "interruption"})
    #                 # else:
    #                 #     logger.debug("VAD识别出首字，但ASR已开始")
    #                 logger.bind(tag="DELAY").info("VAD识别出首字")
    #                 return True, None
    #             elif msg.get("event") == ServerEvent.ASREnded:
    #                 if self.asr_is_started:
    #                     if len(self.asr_result) == 0:
    #                         return True, None
    #                     if atomic_compare_and_set(self.asr_is_started, True, False):
    #                         # 原子操作成功：从True设置为False
    #                         # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
    #                         self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
    #                         logger.bind(tag="DELAY").info(f"VAD识别结束，ASR结果: {self.asr_result}")
    #                         self.process_timer.value = time.time()
    #                 else:
    #                     # logger.bind(tag="DELAY").info("VAD识别结束，但ASR未开始")
    #                     return True, None
    #             return True, msg
    #         return False, None
    #     except Exception as e:
    #         logger.error(f"发送VAD消息失败: {e}")
    #         return False, None
    
    # async def send_e2e_asr_message(self):
    #     """
    #     轮询E2E_ASR输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         while True:
    #             should_continue, msg = await self.send_e2e_asr_message_imp()
    #             if msg:
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         logger.info("E2E_ASR消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"E2E_ASR消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_e2e_asr_message_imp(self):
    #     """
    #     轮询E2E_ASR输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         try:
    #             msg = self.e2e_asr_output_queue.get_nowait()
    #         except queue.Empty:
    #             msg = None
    #         if msg:
    #             if msg.get("event") == ServerEvent.ASRInfo:
    #                 if atomic_compare_and_set(self.asr_is_started, False, True):
    #                     # 原子操作成功：从False设置为True
    #                     # self.llm_input_queues.put({"type": "interruption"})
    #                     # self.tts_input_queues.put({"type": "interruption"})
    #                     self.llm_tts_input_queues.put({"type": "interruption"})
    #                     logger.bind(tag="DELAY").info("E2E ASR识别出首字")
    #                 else:
    #                     logger.bind(tag="DELAY").info("E2E ASR识别出首字，但ASR已开始")
    #                     return True, None
    #             elif msg.get("event") == ServerEvent.ASRResponse:
    #                 if self.asr_is_started == False:
    #                     return True, None
    #                 self.asr_result = msg.get("payload_msg", {}).get("results", [{}])[0].get("text", "")
    #             elif msg.get("event") == ServerEvent.ASREnded:
    #                 if atomic_compare_and_set(self.asr_is_started, True, False):
    #                     # 原子操作成功：从True设置为False
    #                     # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
    #                     self.llm_tts_input_queues.put({"type": "input", "data": self.asr_result})
    #                     logger.bind(tag="DELAY").info(f"E2E ASR识别结束，ASR结果: {self.asr_result}")
    #                     self.process_timer.value = time.time()
    #                 else:
    #                     logger.bind(tag="DELAY").info("E2E ASR识别结束，但ASR未开始")
    #                     return True, None
    #             return True, msg
    #         return False, None
    #     except Exception as e:
    #         logger.error(f"发送ASR消息失败: {e}")
    #         return False, None
    
    # async def send_preprocess_message_imp(self):
    #     """
    #     轮询预处理输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         try:
    #             msg = self.preprocess_output_queue.get_nowait()
    #         except queue.Empty:
    #             msg = None
    #         if msg:
    #             # self.llm_input_queues.put({"type": "input", "data": self.asr_result})
    #             self.llm_tts_input_queues.put({"type": "input", "data": msg.get("data")})
    #     except Exception as e:
    #         logger.error(f"发送VAD消息失败: {e}")
    
    # async def send_llm_tts_message(self):
    #     """
    #     轮询TTS输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         while True:
    #             should_continue, msg = await self.send_llm_tts_message_imp()
    #             if msg:
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         logger.info("LLM_TTS消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"LLM_TTS消息处理任务异常: {e}")
    #         raise  # 重新抛出异常
    
    # async def send_llm_tts_message_imp(self):
    #     """
    #     轮询LLM_TTS输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         sleep_time = 0.01
    #         try:
    #             msg = self.llm_tts_output_queue.get_nowait()
    #         except queue.Empty:
    #             msg = None
    #         if msg:
    #             if msg.get('event') in [ServerEvent.TTSResponse, ServerEvent.TTSSentenceStart, ServerEvent.TTSSentenceEnd, ServerEvent.TTSEnded]:
    #                 self.llm_tts_msg_count += 1
    #                 if self.llm_tts_msg_count % 20 == 0:
    #                     logger.debug(f"收到LLM_TTS消息: {msg.get('event')}, session_id={msg.get('session_id')}, count={self.llm_tts_msg_count}")
    #                 if msg.get('session_id').encode('utf-8') != self.llm_tts_session_id.value:
    #                     if self.llm_tts_msg_count % 20 == 0:
    #                         logger.debug(f"LLM_TTS消息session_id不匹配: {msg.get('session_id')} != {self.llm_tts_session_id.value}")
    #                     return True, None, sleep_time
    #             send_msg = {}
    #             if msg.get('event') == ServerEvent.TTSSentenceStart:
    #                 send_msg = {
    #                     "event": ServerEvent.TTSSentenceStart,
    #                     "payload_msg": {
    #                         "text": msg.get("payload_msg").get("text"),
    #                         "session_id": msg.get("session_id")
    #                     }
    #                 }
    #             else:
    #                 if msg.get('event') == ServerEvent.TTSResponse:
    #                     if self.sse_started:
    #                         sleep_time = len(msg.get("payload_msg")) / 32000 * 0.1
    #                     else:
    #                         sleep_time = len(msg.get("payload_msg")) / 32000 * 0.6
    #                 send_msg = {
    #                     "event": msg.get('event'),
    #                     "payload_msg": msg.get("payload_msg")
    #                 }
    #             return True, send_msg, sleep_time
    #         return False, None, sleep_time
    #     except Exception as e:
    #         logger.error(f"发送LLM_TTS消息失败: {e}")
    #         # 短暂等待后继续
    #         return False, None, sleep_time
    
    async def send_sse_message(self):
        """
        轮询SSE输出队列，有消息就发给SSE
        """
        self.sse_started = True
        try:
            while True:
                should_continue, msg = await self.send_vad_message_imp()
                if msg:
                    yield f"data: {json.dumps(msg)}\n\n"
                if should_continue:
                    continue
                should_continue, msg = await self.send_e2e_asr_message_imp()
                if msg:
                    yield f"data: {json.dumps(msg)}\n\n"
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.sse_started = False
            logger.info("SSE消息处理任务已取消")
        except Exception as e:
            logger.error(f"消息处理任务异常: {e}")
            raise  # 重新抛出异常
    
    # async def send_message(self):
    #     """
    #     轮询VAD输出队列，有消息就发给 websocket
    #     """
    #     try:
    #         sleep_time = 0
    #         while True:
    #             if self.sse_started == False:
    #                 should_continue, msg = await self.send_vad_message_imp()
    #                 if msg:
    #                     if self.websocket_send_callback:
    #                         await self.websocket_send_callback(msg)
    #                 if should_continue:
    #                     continue
    #                 should_continue, msg = await self.send_e2e_asr_message_imp()
    #                 if msg:
    #                     if self.websocket_send_callback:
    #                         await self.websocket_send_callback(msg)
    #                 if should_continue:
    #                     continue
    #             await asyncio.sleep(sleep_time)
    #             should_continue, msg, sleep_time = await self.send_llm_tts_message_imp()
    #             if msg:
    #                 if self.websocket_send_callback:
    #                     await self.websocket_send_callback(msg)
    #     except asyncio.CancelledError:
    #         logger.info("消息处理任务已取消")
    #         raise  # 重新抛出CancelledError
    #     except Exception as e:
    #         logger.error(f"消息处理任务异常: {e}")
    #         raise  # 重新抛出异常

    async def send_message_imp(self):
        """
        轮询LLM_TTS输出队列，有消息就发给 websocket
        """
        try:
            sleep_time = 0
            try:
                msg = self.output_client_queue.get_nowait()
            except queue.Empty:
                msg = None
            if msg:
                if msg.get('event') in [ServerEvent.TTSResponse, ServerEvent.TTSSentenceStart, ServerEvent.TTSSentenceEnd, ServerEvent.TTSEnded]:
                    self.llm_tts_msg_count += 1
                    if self.llm_tts_msg_count % 20 == 0:
                        logger.bind(tag="BASE").debug(f"收到LLM_TTS消息: {msg.get('event')}, session_id={msg.get('session_id')}, count={self.llm_tts_msg_count}")
                    if msg.get('session_id').encode('utf-8') != self.llm_tts_session_id.value:
                        if self.llm_tts_msg_count % 20 == 0:
                            logger.bind(tag="BASE").debug(f"LLM_TTS消息session_id不匹配: {msg.get('session_id')} != {self.llm_tts_session_id.value}")
                        return None, sleep_time
                send_msg = {}
                if msg.get('event') == ServerEvent.TTSSentenceStart:
                    send_msg = {
                        "event": ServerEvent.TTSSentenceStart,
                        "payload_msg": {
                            "text": msg.get("payload_msg").get("text"),
                            "session_id": msg.get("session_id"),
                            "type": "int16"
                        }
                    }
                else:
                    if msg.get('event') == ServerEvent.TTSResponse:
                        self.sleep_time += len(msg.get("payload_msg")) / 32000
                    elif msg.get('event') == ServerEvent.ChatEnded:
                        self.prepost_input_queues.put({"type": "postprocess", "data": msg.get("payload_msg", {})})
                    send_msg = {
                        "event": msg.get('event'),
                        "payload_msg": msg.get("payload_msg")
                    }
                    if msg.get('event') == ServerEvent.TTSSentenceEnd:
                        if self.sse_started:
                            sleep_time = self.sleep_time * 0.1
                        else:
                            sleep_time = self.sleep_time * 0.6
                        self.sleep_time = 0
                        logger.bind(tag="DELAY").info(f"Send TTSSentenceEnd delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
                return send_msg, sleep_time
            return None, sleep_time
        except Exception as e:
            logger.error(f"发送LLM_TTS消息失败: {e}")
            # 短暂等待后继续
            return None, sleep_time

    async def send_message(self):
        """
        轮询VAD输出队列，有消息就发给 websocket
        """
        try:
            sleep_time = 0
            while True:
                await asyncio.sleep(sleep_time)
                msg, sleep_time = await self.send_message_imp()
                if msg:
                    if self.websocket_send_callback:
                        await self.websocket_send_callback(msg)
                        if msg.get('event') == ServerEvent.TTSSentenceStart:
                            logger.bind(tag="DELAY").info(f"SEND TTSSentenceStart delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
                        elif msg.get('event') == ServerEvent.ChatResponseEnd:
                            logger.bind(tag="DELAY").info(f"SEND ChatResponseEnd delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
                        elif msg.get('event') == ServerEvent.ChatEnded:
                            logger.bind(tag="DELAY").info(f"SEND ChatEnded delay: {int((time.time() - self.process_timer.value) * 1000)}ms")
        except asyncio.CancelledError:
            logger.info("消息处理任务已取消")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.error(f"消息处理任务异常: {e}")
            raise  # 重新抛出异常
    
    async def start(self, chat_id: str, user_id: str, websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.chat_id = chat_id
        self.user_id = user_id
        self.websocket_send_callback = websocket_send_callback
        logger.info(f"MessageProcessorAudio启动开始: chat_id={self.chat_id}")
        # self.asr_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.vad_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.e2e_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.prepost_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # self.llm_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # self.tts_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        self.llm_tts_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # self.vad_split_input_queues.put({"type": "start", "data": {"chat_id": chat_id, "user_id": user_id}})
        # with E2E
        timeout = 20  # 最多等待10秒
        start_time = time.time()
        while (not self.e2e_is_process_running.value or
               not self.llm_tts_is_process_running.value or
               not self.vad_is_process_running.value or
               not self.preprocess_is_process_running.value):
            if time.time() - start_time > timeout:
                logger.bind(tag="BASE").error("MessageProcessorAudio启动超时")
                self.e2e_is_process_running.value = True
                self.llm_tts_is_process_running.value = True
                self.vad_is_process_running.value = True
                self.preprocess_is_process_running.value = True
                # self.vad_split_is_process_running.value = True
                return False
            await asyncio.sleep(0.1)
        # with E2E and VAD and LLM and TTS
        # while not self.e2e_is_process_running.value or not self.vad_is_process_running.value or not self.llm_is_process_running.value or not self.tts_is_process_running.value:
        #     await asyncio.sleep(0.1)
        # with ASR
        # while not self.asr_is_process_running.value or not self.llm_tts_is_process_running.value or not self.vad_is_process_running.value:
        #     await asyncio.sleep(0.1)
        logger.info("MessageProcessorAudio启动完成")
        return True
    
    async def cleanup(self):
        logger.info(f"开始清理MessageProcessorAudio: chat_id={self.chat_id}")
        self.websocket_send_callback = None
        self.sse_started = False
        # self.asr_input_queues.put({"type": "stop"})
        self.vad_input_queues.put({"type": "stop"})
        self.e2e_input_queues.put({"type": "stop"})
        self.prepost_input_queues.put({"type": "stop"})
        # self.llm_input_queues.put({"type": "stop"})
        # self.tts_input_queues.put({"type": "stop"})
        self.llm_tts_input_queues.put({"type": "stop"})
        # self.vad_split_input_queues.put({"type": "stop"})
        # with E2E
        while (self.e2e_is_process_running.value or 
               self.llm_tts_is_process_running.value or 
               self.vad_is_process_running.value or 
               self.preprocess_is_process_running.value):
            await asyncio.sleep(0.1)
        # with E2E and VAD and LLM and TTS
        # while self.e2e_is_process_running.value or self.vad_is_process_running.value or self.llm_is_process_running.value or self.tts_is_process_running.value:
        #     await asyncio.sleep(0.1)
        # with ASR
        # while self.asr_is_process_running.value or self.llm_tts_is_process_running.value or self.vad_is_process_running.value:
        #     await asyncio.sleep(0.1)
        logger.info("MessageProcessorAudio清理完成")
