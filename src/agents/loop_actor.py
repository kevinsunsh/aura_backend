import pykka
import asyncio
from loguru import logger
from api_protocol.constant import *
from utils.utils import safe_call
from typing import Any, Dict, Optional, Callable
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager

class LoopActor(pykka.ThreadingActor):
    """Loop Actor - 事件循环"""
    
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.last_timestamp = 0
    
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "input":
                return self._update()
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
        except Exception as e:
            logger.error(f"Loop Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start_process(self, data):
        """启动Loop客户端"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            self.is_running = True
            logger.info(f"Loop Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop_process(self):
        """停止Loop客户端"""
        try:
            self.is_running = False
            logger.info("Loop Actor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
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
    
    def _update(self):
        """处理音频输入"""
        if not self.is_running:
            return {"success": False, "error": "Loop Actor未运行"}
        char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(self.user_id, self.chat_id)
        current_scene_id = char_instance_info.current_scene_id if char_instance_info else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
        result = SceneItemEntryManager().get_scene_items_by_timestamp(self.last_timestamp, current_scene_id)
        self.last_timestamp = result["latest_timestamp"]
        items = result["items"]
        try:
            self._run_async(safe_call(self.output_callback,{
                    "event": ServerEvent.EnvStatus,
                    "payload_msg": {
                        "items": [{"item_id": item.item_id, "description": item.description, "bbox": [item.world_bb_x, item.world_bb_y, item.world_bb_z, item.world_bb_w, item.world_bb_h, item.world_bb_d]} for item in items]
                    }
                }))
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop处理音频失败: {e}")
            return {"success": False, "error": str(e)}
