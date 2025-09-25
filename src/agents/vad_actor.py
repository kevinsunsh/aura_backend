import os
import time
import pykka
from loguru import logger
from typing import Any, Dict, Optional, Callable
from api_protocol.constant import *
from utils.utils import atomic_compare_and_set
from agents.aura_tool.vad_engine import VADEngine


class VADActor(pykka.ThreadingActor):
    """简化的VAD Actor - 直接使用，无需额外的管理器"""
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.session_id = None
        # VAD引擎
        self.vad_engine = None
        self.model_path = None
        
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "input":
                return self._process_input(message.get("data"))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
        except Exception as e:
            logger.error(f"VAD Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start_process(self, data):
        """启动VAD客户端"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            self.session_id = f"{self.chat_id}_{self.user_id}"
            
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            
            # 初始化VAD引擎路径
            self.model_path = os.path.join(os.path.dirname(__file__), "aura_tool/model/vad")
            if not os.path.exists(self.model_path):
                logger.warning(f"VAD模型路径不存在: {self.model_path}")
                self.model_path = None
                return {"success": False, "error": f"VAD模型路径不存在: {self.model_path}"}
            
            # 启动VAD引擎
            try:
                self.vad_engine = VADEngine()
                self.vad_engine.start(self.model_path)
                logger.info("VAD引擎启动成功")
            except Exception as e:
                logger.error(f"VAD引擎启动失败: {e}")
                return {"success": False, "error": f"VAD引擎启动失败: {e}"}
            
            self.is_running = True
            
            logger.info(f"VAD Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"VAD Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop_process(self):
        """停止VAD客户端"""
        try:
            self.is_running = False
            # 清理VAD引擎
            if self.vad_engine:
                self.vad_engine.cleanup()
                self.vad_engine = None
            logger.info("VAD Actor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"VAD Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _process_input(self, audio_data):
        """处理音频输入"""
        if not self.is_running:
            return {"success": False, "error": "VAD Actor未运行"}
        try:
            if not audio_data:
                return {"success": False, "error": "Empty audio data"}
            # 检查VAD引擎是否已启动
            if not self.vad_engine:
                return {"success": False, "error": "VAD引擎未启动"}
            # 处理音频数据
            result = self.vad_engine.process_audio_chunk(audio_data)
            if result is not None:
                # 处理VAD结果
                self._handle_vad_result(result)
            return {"success": True}
        except Exception as e:
            logger.error(f"VAD处理音频失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _handle_vad_result(self, result):
        """处理VAD检测结果"""
        try:
            # 解析VAD结果
            if len(result) > 0 and len(result[0]) > 0:
                vad_data = result[0][0]  # 取第一个检测结果
                if len(vad_data) >= 2:
                    start_frame = vad_data[0]
                    end_frame = vad_data[1]
                    # 检测到语音结束
                    if start_frame == -1 and end_frame != -1:
                        self._handle_speech_ended()
        except Exception as e:
            logger.error(f"处理VAD结果失败: {e}")
    
    def _handle_speech_ended(self):
        """处理语音结束事件"""
        try:
            # 发送ASR结束事件
            if self.output_callback:
                self.output_callback({
                    "event": ServerEvent.ASREnded,
                    "session_id": self.session_id
                })
        except Exception as e:
            logger.error(f"处理语音结束事件失败: {e}")
