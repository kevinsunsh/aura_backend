import pykka
from loguru import logger
from typing import Optional, Callable
from api_protocol.constant import *
from .doubao_client.tts_client import TtsClient


class TTSActor(pykka.ThreadingActor):
    """仅负责TTS（含内部长期事件循环）的 Actor"""

    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.chat_id = None
        self.user_id = None
        self.tts_client: TtsClient | None = None
        self.llm_is_chat_started = False

    def on_receive(self, message):
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "send_text_chunk":
                return self._send_text_chunk(message.get("text", ""), message.get("start", False), message.get("end", False))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
        except Exception as e:
            logger.error(f"TTSActor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start_process(self, data):
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            self.tts_client = TtsClient(
                tts_sentence_start_callback=self._on_tts_sentence_start,
                tts_response_callback=self._on_tts_response,
                tts_sentence_end_callback=self._on_tts_sentence_end,
                tts_ended_callback=self._on_tts_ended,
            )
            self.tts_client.start_background(self.chat_id, self.user_id)
            logger.info(f"TTSActor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"TTSActor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop_process(self):
        try:
            if self.tts_client:
                self.tts_client.cleanup_background()
            logger.info("TTSActor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"TTSActor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _send_text_chunk(self, text: str, start: bool, end: bool):
        try:
            if not self.tts_client:
                return {"success": False, "error": "TTS未启动"}
            # 交给内部事件循环
            import asyncio
            asyncio.run(self.tts_client.send_text_chunk(text, start=start, end=end))
            return {"success": True}
        except Exception as e:
            logger.error(f"发送TTS文本失败: {e}")
            return {"success": False, "error": str(e)}

    # 回调透传
    def _on_tts_sentence_start(self, payload, session_id):
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceStart,
                "payload_msg": payload,
                "session_id": session_id,
            })

    def _on_tts_response(self, payload, session_id):
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSResponse,
                "payload_msg": payload,
                "session_id": session_id,
            })

    def _on_tts_sentence_end(self, session_id):
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceEnd,
                "session_id": session_id,
            })

    def _on_tts_ended(self, session_id):
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSEnded,
                "session_id": session_id,
            })


