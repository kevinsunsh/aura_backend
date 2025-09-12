import pykka
import asyncio
import time
from loguru import logger
from typing import Optional, Callable
from api_protocol.constant import *
from .message_processor_text import MessageProcessorText

class LLMActor(pykka.ThreadingActor):
    """仅负责文本处理（LLM）的 Actor"""

    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.process_timer = time.time()
        self.text_processor: MessageProcessorText | None = None

    def on_receive(self, message):
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop()
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
            logger.error(f"LLMActor处理消息失败: {e}")
            return {"success": False, "error": str(e)}

    def _start(self, data):
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            self.text_processor = MessageProcessorText(
                websocket_send_callback=self._text_processor_callback,
                process_timer=self.process_timer,
            )
            self._run_async(self.text_processor.start(self.chat_id, self.user_id))
            self.is_running = True
            logger.info(f"LLMActor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor启动失败: {e}")
            return {"success": False, "error": str(e)}

    def _stop(self):
        try:
            self.is_running = False
            if self.text_processor:
                self._run_async(self.text_processor.cleanup())
            logger.info("LLMActor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor停止失败: {e}")
            return {"success": False, "error": str(e)}

    def _run_llm(self, prompts):
        if not self.is_running or not self.text_processor:
            return {"success": False, "error": "LLMActor未运行"}
        try:
            if not prompts:
                return {"success": False, "error": "Empty prompts"}
            self._run_async(self.text_processor.handle_message(prompts))
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor运行失败: {e}")
            return {"success": False, "error": str(e)}

    async def _text_processor_callback(self, message):
        try:
            if self.output_callback:
                await self.output_callback(message)
        except Exception as e:
            logger.error(f"LLMActor回调失败: {e}")

    def _run_async(self, coro):
        try:
            asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            finally:
                loop.close()
