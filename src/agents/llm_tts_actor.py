import pykka
import time
import asyncio
from loguru import logger
from typing import Any, Dict, Optional, Callable
from api_protocol.constant import *
from .message_processor_text import MessageProcessorText
from .doubao_client.tts_client import TtsClient

class LLMTTSActor(pykka.ThreadingActor):
    """LLM+TTS Actor - 大语言模型和文本转语音组合"""
    
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.session_id = None
        self.text_processor = None
        self.tts_client = None
        self.process_timer = time.time()
        self.llm_is_chat_started = False
        
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            
            if msg_type == "start":
                return self._start(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop()
            elif msg_type == "interruption":
                return self._handle_interruption()
            elif msg_type == "run":
                return self._run_llm(message.get("data"))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            elif msg_type == "set_process_timer":
                self.process_timer = message.get("timer", 0)
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
                
        except Exception as e:
            logger.error(f"LLM+TTS Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start(self, data):
        """启动LLM+TTS客户端"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            self.session_id = f"{self.chat_id}_{self.user_id}"
            
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            
            # 初始化文本处理器
            self.text_processor = MessageProcessorText(
                websocket_send_callback=self._text_processor_callback,
                process_timer=self.process_timer
            )
            # 启动文本处理器会话
            self._run_async(self.text_processor.start(self.chat_id, self.user_id))
            
            # 初始化TTS客户端
            self.tts_client = TtsClient(
                tts_sentence_start_callback=self._on_tts_sentence_start,
                tts_response_callback=self._on_tts_response,
                tts_sentence_end_callback=self._on_tts_sentence_end,
                tts_ended_callback=self._on_tts_ended,
                session_id=self.session_id
            )
            
            self.is_running = True
            
            logger.info(f"LLM+TTS Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"LLM+TTS Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop(self):
        """停止LLM+TTS客户端"""
        try:
            self.is_running = False
            
            # 清理TTS客户端
            if self.tts_client:
                # 这里应该调用cleanup，但TtsClient可能没有cleanup方法
                # 我们可以在TtsClient中添加cleanup方法
                pass
            
            # 清理文本处理器
            if self.text_processor:
                # 这里应该调用cleanup，但MessageProcessorText可能没有cleanup方法
                # 我们可以在MessageProcessorText中添加cleanup方法
                pass
            
            logger.info("LLM+TTS Actor停止成功")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"LLM+TTS Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _handle_interruption(self):
        """处理用户输入中断"""
        if not self.is_running:
            return {"success": False, "error": "LLM+TTS Actor未运行"}
        
        try:
            # 处理文本处理器中断
            if self.text_processor:
                logger.debug("处理文本处理器中断")
                self._run_async(self.text_processor.user_input_interruption())
            
            # 处理TTS客户端中断
            if self.tts_client:
                # 这里应该调用user_input_interruption
                # 由于TtsClient可能是异步的，我们需要适配
                logger.debug("处理TTS客户端中断")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"处理中断失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _run_llm(self, prompts):
        """运行LLM处理"""
        if not self.is_running or not self.text_processor:
            return {"success": False, "error": "LLM+TTS Actor未运行"}
        
        try:
            if not prompts:
                return {"success": False, "error": "Empty prompts"}
            
            logger.debug(f"LLM处理提示: {len(prompts)} 条")
            # 调用实际文本处理
            self._run_async(self.text_processor.handle_message(prompts))
            return {"success": True}
            
        except Exception as e:
            logger.error(f"LLM处理失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _text_processor_callback(self, message):
        """文本处理器回调（异步），透传到上层回调"""
        try:
            if message.get("event") == ServerEvent.ChatResponse:
                if self.llm_is_chat_started:
                    await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""))
                else:
                    self.llm_is_chat_started = True
                    await self.tts_client.send_text_chunk(message.get("payload_msg", {}).get("content", ""), start=True, end=False)
            elif message.get("event") == ServerEvent.ChatResponseEnd:
                self.llm_is_chat_started = False
                await self.tts_client.send_text_chunk("", start=False, end=True)
            if self.output_callback:
                await self.output_callback(message)
        except Exception as e:
            logger.error(f"文本处理器回调失败: {e}")

    def _run_async(self, coro):
        """在同步Actor中运行异步任务的工具方法"""
        try:
            asyncio.run(coro)
        except RuntimeError:
            # 已存在事件循环时，创建新的事件循环
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            finally:
                loop.close()
    
    # TTS回调方法
    def _on_tts_sentence_start(self, payload, session_id):
        """TTS句子开始事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceStart,
                "payload_msg": payload,
                "session_id": session_id
            })
    
    def _on_tts_response(self, payload, session_id):
        """TTS音频响应事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSResponse,
                "payload_msg": payload,
                "session_id": session_id
            })
    
    def _on_tts_sentence_end(self, session_id):
        """TTS句子结束事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceEnd,
                "session_id": session_id
            })
    
    def _on_tts_ended(self, session_id):
        """TTS结束事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSEnded,
                "session_id": session_id
            })
