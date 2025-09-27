import pykka
import asyncio
import re
from datetime import datetime
from loguru import logger
from typing import Optional, Callable, Dict, Any
from api_protocol.constant import *
from .message_processor_text import StreamingTagParser
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.configuration.config import ChatModel, EmbeddingModel
from utils.utils import safe_call
from agents.agent_memory.prompt_manager.utils import count_tokens_openai
from agents.agent_memory.message_store import MessageStore, MessageModel
import uuid

class LLMActionActor(pykka.ThreadingActor):
    """仅负责文本处理（LLM）的 Actor"""

    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.parser = StreamingTagParser(tag_callback=self.tag_callback)
        self.process_timer = 0
        self.final_response = ""
    
    def on_receive(self, message):
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
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

    def _start_process(self, data):
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            self.is_running = True
            logger.bind(tag="BASE").info(f"LLMActionActor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor启动失败: {e}")
            return {"success": False, "error": str(e)}

    def _stop_process(self):
        try:
            self.is_running = False
            logger.info("LLMActor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor停止失败: {e}")
            return {"success": False, "error": str(e)}

    def _run_llm(self, prompts):
        if not self.is_running:
            return {"success": False, "error": "LLMActor未运行"}
        try:
            if not prompts:
                return {"success": False, "error": "Empty prompts"}
            self._run_async(self.handle_message(prompts))
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor运行失败: {e}")
            return {"success": False, "error": str(e)}

    async def tag_callback(self, payload):
        if payload["tag"] == "action":
            if payload["status"] == "start":
                # self.action_content = payload['attributes']['attribute'] + ":"
                # self.user_info = UserInfoManager().get_user_info_by_user_id(self.user_id)
                char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(self.user_id, self.chat_id)
                current_scene_id = char_instance_info.current_scene_id if char_instance_info else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
                current_scene_id = current_scene_id if current_scene_id else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
                logger.bind(tag="BASE").info(f"current_scene_id: {current_scene_id}")
                # 用户可切换场景，这里以用户当前场景为准
                # current_scene_id = self.user_info.current_scene_id if self.user_info and getattr(self.user_info, "current_scene_id", None) else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
                pattern = r'(\w+)\(([^)]+)\)'
                matches = re.findall(pattern, payload['attributes']['attribute'])
                result = {
                    "func": "idle",
                    "target": "idle"
                }
                if len(matches) > 0:
                    result = {
                        "func": matches[0][0] if matches[0][0] else "idle",
                        "target": matches[0][1] if matches[0][1] else "null"
                    }
                    logger.bind(tag="BASE").info(f"action result: {result}")
                    if result["func"] not in ["idle", "turn"]:
                        # if result["func"] not in ["sit", "stand", "idle", "take", "turn"]:
                        item = SceneItemEntryManager().get_scene_item_by_id(current_scene_id, result["target"])
                        if item:
                            logger.bind(tag="BASE").info(f"item: {item.item_type}")
                            if item.item_type != "":
                                result["position"] = item.get_world_pos().tolist()
                                result["position"][2] = 0.5
                            result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                            result["name"] = item.item_name
                            result["label"] = item.label_name
                            result["description"] = item.description
                        else:
                            embedding_model = EmbeddingModel(
                                model_name="doubao-embedding-large-text-250515",
                                api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                                api_base="https://ark.cn-beijing.volces.com/api/v3",
                            )
                            desc_vec = embedding_model.embed(result["target"])
                            items = SceneItemEntryManager().search_items_by_description_vector(current_scene_id, desc_vec, top_k=1)
                            if len(items) > 0:
                                result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
                                result["target"] = items[0]["item_id"]
                                result["name"] = items[0]["item_name"]
                                result["label"] = items[0]["label_name"]
                                result["description"] = items[0]["description"]
                                result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                            else:
                                items = SceneItemEntryManager().search_items_by_keywords(current_scene_id, result["target"], top_k=1)
                                if len(items) > 0:
                                    result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
                                    result["target"] = items[0]["item_id"]
                                    result["name"] = items[0]["item_name"]
                                    result["label"] = items[0]["label_name"]
                                    result["description"] = items[0]["description"]
                                    result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                        # else:
                        #     item = SceneItemEntryManager().get_scene_item_by_id(current_scene_id, result["target"])
                        #     if item:
                        #         logger.bind(tag="BASE").info(f"item type: {item.item_type}")
                        #         if item.item_type != "":
                        #             result["func"] = "stand"
                        #             result["position"] = item.get_world_pos().tolist()
                        #             result["position"][2] = 0.5
                        #             result["name"] = item.item_name
                        #             result["label"] = item.label_name
                        #     else:
                        #         item = SceneItemEntryManager().get_scene_item_by_action(current_scene_id, result["func"])
                        #         if item:
                        #             logger.bind(tag="BASE").info(f"item: {item.item_type}")
                        #             result["target"] = item.item_id
                        #             result["name"] = item.item_name
                        #             result["label"] = item.label_name
                        #         else:
                        #             result["func"] = "idle"
                    char_status = {"action": {"current": result["func"], "target": result["target"]}}
                    view_matrix = char_instance_info.view_matrix if char_instance_info else None
                    projection_matrix = char_instance_info.projection_matrix if char_instance_info else None
                    scene_id = char_instance_info.current_scene_id if char_instance_info else None
                    CharInstanceInfoManager().upsert_char_instance_info(self.user_id, self.chat_id, char_status=char_status, view_matrix=view_matrix, projection_matrix=projection_matrix, current_scene_id=scene_id)
                logger.bind(tag="BASE").info(f"action result: {result}")
                if self.output_callback:
                    await safe_call(self.output_callback, {
                        "event": ServerEvent.ChatActionParams,
                        "payload_msg": {
                            "params": {
                                "attribute": result
                            }
                        }
                    })
            elif payload["status"] == "streaming":
                # self.action_content = self.action_content + payload['content']
                if self.output_callback:
                    await safe_call(self.output_callback, {
                        "event": ServerEvent.ChatAction,
                        "payload_msg": {
                            "content": payload["content"]
                        }
                    })
            elif payload["status"] == "end":
                # actions = self.action_content.split(":")
                # res = handle_position(self.user_id, self.chat_id, self.action_content)
                if self.output_callback:
                    # await self.websocket_send_callback({
                    #     "event": ServerEvent.ChatActionParams,
                    #     "payload_msg": {
                    #         "params": {
                    #             "attribute": {
                    #                 "action": actions[0],
                    #                 "start": res[0].tolist(),
                    #                 "direction": res[1].tolist()
                    #             }
                    #         }
                    #     }
                    # })
                    # await self.websocket_send_callback({
                    #     "event": ServerEvent.ChatAction,
                    #     "payload_msg": {
                    #         "content": actions[1]
                    #     }
                    # })
                    await safe_call(self.output_callback,{
                        "event": ServerEvent.ChatActionEnd,
                        "payload_msg": {
                            "content": self.final_response
                        }
                    })
    
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
        
    async def handle_message(self, prompts: list[dict]) -> Dict[str, Any]:
        try:
            for prompt in prompts:
                logger.bind(tag="BASE").info(f"{prompt['role']}: {prompt['content']}")
            chat_model = get_chat_model_by_type("focus_working_memory")
            self.final_response = ""
            logger.bind(tag="DELAY").info(f"start llm response delay: {int((datetime.now().timestamp() - self.process_timer) * 1000)}ms")
            async for chunk in chat_model.astream(prompts, extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    self.final_response += chunk.content
                    await self.parser.feed(chunk.content)
            await self.parser.end()
            logger.bind(tag="TASK").info(f"final_response: {self.final_response}")
        except asyncio.CancelledError:
            logger.bind(tag="BASE").info(f"回复任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.bind(tag="BASE").info(f"生成动作回复时出错: {str(e)}")
