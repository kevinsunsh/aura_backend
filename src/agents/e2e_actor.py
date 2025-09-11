import pykka
import asyncio
import threading
from loguru import logger
from typing import Any, Dict, Optional, Callable
from api_protocol.constant import *
from agents.doubao_client.dialog_session import DialogSession

class E2EActor(pykka.ThreadingActor):
    """E2E Actor - 端到端语音对话"""
    
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.session_id = None
        self.dialog_session = None
        self._loop = None
        self._loop_thread = None
        
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            
            if msg_type == "start":
                return self._start(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop()
            elif msg_type == "input":
                return self._process_input(message.get("data"))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
                
        except Exception as e:
            logger.error(f"E2E Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start(self, data):
        """启动E2E客户端"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            self.session_id = f"{self.chat_id}_{self.user_id}"
            
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            
            # 初始化事件循环（单独线程）
            self._ensure_loop()

            # 初始化DialogSession
            self.dialog_session = DialogSession(
                asr_start_callback=self._on_asr_info,
                asr_response_callback=self._on_asr_response,
                asr_end_callback=self._on_asr_ended,
                tts_sentence_start_callback=self._on_tts_sentence_start,
                tts_response_callback=self._on_tts_response,
                tts_sentence_end_callback=self._on_tts_sentence_end,
                tts_ended_callback=self._on_tts_ended,
                chat_response_callback=self._on_chat_response,
                chat_end_callback=self._on_chat_ended
            )
            # 启动会话（异步）
            fut = asyncio.run_coroutine_threadsafe(
                self.dialog_session.start(self.chat_id, self.user_id),
                self._loop
            )
            # 等待启动结果片刻以捕获立即错误
            try:
                fut.result(timeout=5)
            except Exception as e:
                logger.error(f"DialogSession 启动失败: {e}")
                return {"success": False, "error": str(e)}

            self.is_running = True
            
            logger.info(f"E2E Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"E2E Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop(self):
        """停止E2E客户端"""
        try:
            self.is_running = False
            
            # 清理DialogSession
            if self.dialog_session and self._loop:
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.dialog_session.cleanup(), self._loop
                    )
                    fut.result(timeout=10)
                except Exception as e:
                    logger.warning(f"DialogSession 清理异常: {e}")
                finally:
                    self.dialog_session = None

            # 停止事件循环线程
            if self._loop:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass
            if self._loop_thread and self._loop_thread.is_alive():
                try:
                    self._loop_thread.join(timeout=2)
                except Exception:
                    pass
            self._loop = None
            self._loop_thread = None
            
            logger.info("E2E Actor停止成功")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"E2E Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _process_input(self, audio_data):
        """处理音频输入"""
        if not self.is_running or not self.dialog_session:
            return {"success": False, "error": "E2E Actor未运行"}
        
        try:
            if not audio_data:
                return {"success": False, "error": "Empty audio data"}
            
            # 异步提交到事件循环
            logger.debug(f"E2E处理音频数据: {len(audio_data)} bytes")
            fut = asyncio.run_coroutine_threadsafe(
                self.dialog_session.process_audio_chunk(audio_data),
                self._loop
            )
            # 不阻塞等待音频发送完成，可选地短等待以抛出同步错误
            try:
                fut.result(timeout=2)
            except Exception as e:
                logger.error(f"发送音频失败: {e}")
                return {"success": False, "error": str(e)}

            return {"success": True}
            
        except Exception as e:
            logger.error(f"E2E处理音频失败: {e}")
            return {"success": False, "error": str(e)}
    
    # 回调方法
    def _on_asr_info(self):
        """ASR信息事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.ASRInfo,
                "session_id": self.session_id
            })
    
    def _on_asr_response(self, payload):
        """ASR响应事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.ASRResponse,
                "payload_msg": payload,
                "session_id": self.session_id
            })
    
    def _on_asr_ended(self):
        """ASR结束事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.ASREnded,
                "session_id": self.session_id
            })
    
    def _on_tts_sentence_start(self, payload):
        """TTS句子开始事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceStart,
                "payload_msg": payload,
                "session_id": self.session_id
            })
    
    def _on_tts_response(self, payload):
        """TTS音频响应事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSResponse,
                "payload_msg": payload,
                "session_id": self.session_id
            })
    
    def _on_tts_sentence_end(self):
        """TTS句子结束事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSSentenceEnd,
                "session_id": self.session_id
            })
    
    def _on_tts_ended(self):
        """TTS结束事件回调"""
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.TTSEnded,
                "session_id": self.session_id
            })
    
    def _on_chat_response(self, payload):
        """聊天响应事件回调"""
        logger.debug(f"E2E收到聊天响应: {payload.get('content', '')[:10]}...")
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.ChatResponse,
                "payload_msg": payload,
                "session_id": self.session_id
            })
    
    def _on_chat_ended(self):
        """聊天结束事件回调"""
        logger.debug("E2E聊天响应结束")
        if self.output_callback:
            self.output_callback({
                "event": ServerEvent.ChatEnded,
                "session_id": self.session_id
            })

    # 内部：事件循环管理
    def _run_loop(self):
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop=self._loop)
                for task in pending:
                    task.cancel()
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass

    def _ensure_loop(self):
        if self._loop is not None and self._loop_thread and self._loop_thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, name="E2EActorLoop", daemon=True)
        self._loop_thread.start()
