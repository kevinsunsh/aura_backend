import json
import uuid
import pykka
import asyncio
from datetime import datetime
from loguru import logger
from typing import Optional, Callable, Dict, Any
from api_protocol.constant import *
from .message_processor_text import StreamingTagParser
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.database.connection_config import DatabaseConfigManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.configuration.config import ChatModel, EmbeddingModel
from agents.agent_memory.prompt_manager.utils import count_tokens_openai
from agents.agent_memory.message_store import MessageStore, MessageModel
from utils.utils import safe_call
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
# 移除 agent_flow_manager 依赖
from agents.agent_memory.message_store import MessageStore
from agents.graphs.agent_flow_graph import (
    builder
)
from langgraph.types import Command, Interrupt
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from langgraph.graph import START, END, StateGraph

class LLMActionActor(pykka.ThreadingActor):
    """仅负责文本处理（LLM）的 Actor"""
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.process_timer = 0
        self.final_response = ""
        # Agent 流程相关
        self.agent_flow_state = None  # 存储当前流程状态
        self.pending_user_input = None  # 待处理的用户输入
        self.last_planning_time = None  # 上次规划时间
        self.planning_interval = 30  # 规划间隔（秒）
        self.is_planning = False  # 是否正在规划中
        self.bot_name = None
        self.start_action = False
        self.current_action = ""
    
    def on_receive(self, message):
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            elif msg_type == "set_process_timer":
                self.process_timer = message.get("timer", 0)
                return {"success": True}
            elif msg_type == "action_step_finished":
                return self._action_step_finished(message.get("data", {}))
            elif msg_type == "goal_input":
                return self._handle_goal_input(message.get("data", {}).get("content", ""))
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
            self.thread = {
                "configurable": {
                    "thread_id": self.chat_id
                }
            }
            db_conn_string = DatabaseConfigManager.get_config_by_environment().get_checkpointer_connection_string()
            pool = ConnectionPool(conninfo=db_conn_string)
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()
            self.graph = builder.compile(checkpointer=checkpointer)
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
    
    # async def tag_callback(self, payload):
    #     if payload["tag"] == "action":
    #         if payload["status"] == "start":
    #             # self.action_content = payload['attributes']['attribute'] + ":"
    #             # self.user_info = UserInfoManager().get_user_info_by_user_id(self.user_id)
    #             char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(self.user_id, self.chat_id)
    #             current_scene_id = char_instance_info.current_scene_id if char_instance_info else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
    #             current_scene_id = current_scene_id if current_scene_id else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
    #             logger.bind(tag="BASE").info(f"current_scene_id: {current_scene_id}")
    #             # 用户可切换场景，这里以用户当前场景为准
    #             # current_scene_id = self.user_info.current_scene_id if self.user_info and getattr(self.user_info, "current_scene_id", None) else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
    #             pattern = r'(\w+)\(([^)]+)\)'
    #             matches = re.findall(pattern, payload['attributes']['attribute'])
    #             result = {
    #                 "func": "idle",
    #                 "target": "idle"
    #             }
    #             if len(matches) > 0:
    #                 result = {
    #                     "func": matches[0][0] if matches[0][0] else "idle",
    #                     "target": matches[0][1] if matches[0][1] else "null"
    #                 }
    #                 # if result["func"] not in ["sit", "stand", "idle", "take", "turn"]:
    #                 item = SceneItemEntryManager().get_scene_item_by_id(current_scene_id, result["target"])
    #                 if item:
    #                     logger.bind(tag="BASE").info(f"item: {item.item_type}")
    #                     if item.item_type != "":
    #                         result["position"] = item.get_world_pos().tolist()
    #                         result["position"][2] = 0.5
    #                     result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
    #                     result["name"] = item.item_name
    #                     result["label"] = item.label_name
    #                 else:
    #                     embedding_model = EmbeddingModel(
    #                         model_name="doubao-embedding-large-text-250515",
    #                         api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
    #                         api_base="https://ark.cn-beijing.volces.com/api/v3",
    #                     )
    #                     desc_vec = embedding_model.embed(result["target"])
    #                     items = SceneItemEntryManager().search_items_by_description_vector(current_scene_id, desc_vec, top_k=1)
    #                     if len(items) > 0:
    #                         result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
    #                         result["target"] = items[0]["item_id"]
    #                         result["name"] = items[0]["item_name"]
    #                         result["label"] = items[0]["label_name"]
    #                         result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
    #                     else:
    #                         items = SceneItemEntryManager().search_items_by_keywords(current_scene_id, result["target"], top_k=1)
    #                         if len(items) > 0:
    #                             result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
    #                             result["target"] = items[0]["item_id"]
    #                             result["name"] = items[0]["item_name"]
    #                             result["label"] = items[0]["label_name"]
    #                             result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
    #                 # else:
    #                 #     item = SceneItemEntryManager().get_scene_item_by_id(current_scene_id, result["target"])
    #                 #     if item:
    #                 #         logger.bind(tag="BASE").info(f"item type: {item.item_type}")
    #                 #         if item.item_type != "":
    #                 #             result["func"] = "stand"
    #                 #             result["position"] = item.get_world_pos().tolist()
    #                 #             result["position"][2] = 0.5
    #                 #             result["name"] = item.item_name
    #                 #             result["label"] = item.label_name
    #                 #     else:
    #                 #         item = SceneItemEntryManager().get_scene_item_by_action(current_scene_id, result["func"])
    #                 #         if item:
    #                 #             logger.bind(tag="BASE").info(f"item: {item.item_type}")
    #                 #             result["target"] = item.item_id
    #                 #             result["name"] = item.item_name
    #                 #             result["label"] = item.label_name
    #                 #         else:
    #                 #             result["func"] = "idle"
    #                 char_status = {"action": {"current": result["func"], "target": result["target"]}}
    #                 view_matrix = char_instance_info.view_matrix if char_instance_info else None
    #                 projection_matrix = char_instance_info.projection_matrix if char_instance_info else None
    #                 scene_id = char_instance_info.current_scene_id if char_instance_info else None
    #                 CharInstanceInfoManager().upsert_char_instance_info(self.user_id, self.chat_id, char_status=char_status, view_matrix=view_matrix, projection_matrix=projection_matrix, current_scene_id=scene_id)
    #             logger.bind(tag="BASE").info(f"action result: {result}")
    #             if self.output_callback:
    #                 await safe_call(self.output_callback, {
    #                     "event": ServerEvent.ChatActionParams,
    #                     "payload_msg": {
    #                         "params": {
    #                             "attribute": result
    #                         }
    #                     }
    #                 })
    #         elif payload["status"] == "streaming":
    #             # self.action_content = self.action_content + payload['content']
    #             if self.output_callback:
    #                 await safe_call(self.output_callback, {
    #                     "event": ServerEvent.ChatAction,
    #                     "payload_msg": {
    #                         "content": payload["content"]
    #                     }
    #                 })
    #         elif payload["status"] == "end":
    #             # actions = self.action_content.split(":")
    #             # res = handle_position(self.user_id, self.chat_id, self.action_content)
    #             if self.output_callback:
    #                 # await self.websocket_send_callback({
    #                 #     "event": ServerEvent.ChatActionParams,
    #                 #     "payload_msg": {
    #                 #         "params": {
    #                 #             "attribute": {
    #                 #                 "action": actions[0],
    #                 #                 "start": res[0].tolist(),
    #                 #                 "direction": res[1].tolist()
    #                 #             }
    #                 #         }
    #                 #     }
    #                 # })
    #                 # await self.websocket_send_callback({
    #                 #     "event": ServerEvent.ChatAction,
    #                 #     "payload_msg": {
    #                 #         "content": actions[1]
    #                 #     }
    #                 # })
    #                 await safe_call(self.output_callback,{
    #                     "event": ServerEvent.ChatActionEnd,
    #                     "payload_msg": {
    #                         "content": self.final_response
    #                     }
    #                 })
    
    def _action_step_finished(self, execution_result: Dict[str, Any]):
        try:
            current_action = execution_result.get("current", "").strip()
            current_target = execution_result.get("target", "").strip()
            if not current_action or not current_target:
                return {"success": True}
            if self.start_action == False:
                logger.bind(tag="BASE").info(f"start_action is False, skip")
                return {"success": True}
            self.start_action = False
            input_data = {
                "current_action": self.current_action,
                "current_target": self.current_target
            }
            logger.bind(tag="BASE").info(f"input data: {input_data}")
            action_message = f"finished executing {self.current_action} with {self.current_target}."
            action_data = {'content': action_message, 'bot_name': self.bot_name}
            self._add_action_message(action_data, self.start_action)
            for event in self.graph.stream(Command(resume=True, update=input_data), self.thread, stream_mode="updates"):
                try:
                    self._publish_event(event)
                except Exception as e:
                    logger.bind(tag="BASE").info(f"Failed to publish event to Redis: {str(e)}")
                    continue
            return {"success": True}
        except Exception as e:
            logger.bind(tag="BASE").info(f"LLMActionActor 处理 action step finished 消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _handle_goal_input(self, goal_input: str):
        """处理用户输入，判断是否需要中断当前流程"""
        try:
            if not goal_input:
                return {"success": False, "error": "Empty goal input"}
            
            logger.bind(tag="BASE").info(f"收到目标输入: {goal_input}")
            input_data = {
                "chat_id": self.chat_id,
                "user_id": self.user_id,
                "action_goal": goal_input,
                "goal_timestamp": int(datetime.now().timestamp() * 1000)
            }
            for event in self.graph.stream(input_data, self.thread, stream_mode="updates"):
                try:
                    self._publish_event(event)
                except Exception as e:
                    logger.error(f"Failed to publish event to Redis: {str(e)}")
                    # 继续处理下一个事件，不中断流程
                    continue
            return {"success": True}
        except Exception as e:
            logger.error(f"处理目标输入失败: {e}")
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
    
    def _add_action_message(self, data, start_action: bool):
        """执行后处理"""
        logger.bind(tag="BASE").info(f"添加动作消息: {data}")
        # if not self.is_running:
        #     logger.bind(tag="BASE").info(f"PrePost Actor未运行")
        #     return {"success": False, "error": "PrePost Actor未运行"}
        try:
            bot_response = data or {}
            content = bot_response.get("content", "")
            bot_name = bot_response.get("bot_name", "")
            # tokens = count_tokens_openai(content)
            if start_action == False:
                if self.output_callback:
                    self._run_async(safe_call(self.output_callback, {
                        "event": ServerEvent.ChatActionResponse,
                        "payload_msg": {
                            "params": {
                                "attribute": {
                                    "content": content
                                }
                            }
                        }
                    }))
            message = MessageModel(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_id,
                user_id=bot_name or "assistant",
                platform="default",
                role="assistant",
                m_type="action",
                content=content,
                tokens=0,
                data={},
                created_at=int(datetime.now().timestamp() * 1000)
            )
            MessageStore.get_instance().add_message(message)
        except Exception as e:
            logger.error(f"添加动作消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _publish_event(self, event):
        try:
            if '__interrupt__' in event:
                action = json.loads(event['__interrupt__'][0].value)
                result = {
                    "func": action["cmd"],
                    "target": action["id"]
                }
                self.current_action = action["cmd"]
                self.current_target = action["id"]
                logger.bind(tag="BASE").info(f"output result: {result}")
                if action["id"] != "self":
                    item = SceneItemEntryManager().get_scene_item_by_id(action["scene_id"], result["target"])
                    if item:
                        logger.bind(tag="BASE").info(f"item: {item.item_type}")
                        if item.item_type != "":
                            result["position"] = item.get_world_pos().tolist()
                            result["position"][2] = 0.5
                        result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                        result["name"] = item.item_name
                        result["label"] = item.label_name
                    else:
                        embedding_model = EmbeddingModel(
                            model_name="doubao-embedding-large-text-250515",
                            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                            api_base="https://ark.cn-beijing.volces.com/api/v3",
                        )
                        desc_vec = embedding_model.embed(result["target"])
                        items = SceneItemEntryManager().search_items_by_description_vector(action["scene_id"], desc_vec, top_k=1)
                        if len(items) > 0:
                            result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
                            result["target"] = items[0]["item_id"]
                            result["name"] = items[0]["item_name"]
                            result["label"] = items[0]["label_name"]
                            result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                        else:
                            items = SceneItemEntryManager().search_items_by_keywords(action["scene_id"], result["target"], top_k=1)
                            if len(items) > 0:
                                result["position"] = [items[0]["world_pos_x"], items[0]["world_pos_y"], 0.5]
                                result["target"] = items[0]["item_id"]
                                result["name"] = items[0]["item_name"]
                                result["label"] = items[0]["label_name"]
                                result["func"] = result["func"] if result["func"] in ["sit", "stand"] else "stand"
                action_message = f'planned to {self.current_action} with {self.current_target}. reason: {action["reasoning"]}'
                self.bot_name = action["bot_name"]
                action_data = {'content': action_message, 'bot_name': self.bot_name}
                self.start_action = True
                self._add_action_message(action_data, self.start_action)
                logger.bind(tag="BASE").info(f"action result: {result}, start_action: {self.start_action}")
                if self.output_callback:
                    self._run_async(safe_call(self.output_callback, {
                        "event": ServerEvent.ChatActionParams,
                        "payload_msg": {
                            "params": {
                                "attribute": result
                            }
                        }
                    }))
                    self._run_async(safe_call(self.output_callback, {
                        "event": ServerEvent.ChatAction,
                        "payload_msg": {
                            "content": action["reasoning"]
                        }
                    }))
                    self._run_async(safe_call(self.output_callback,{
                            "event": ServerEvent.ChatActionEnd,
                            "payload_msg": {
                                "content": action_message
                            }
                        }))
                if action["cmd"] == "idle":
                    self.tell({"type": "action_step_finished", "data": {"current": "idle", "target": "self"}})
            elif 'execute_action' in event:
                data = event["execute_action"]
                if "current_result" in data:
                    if len(data["current_result"]) > 0:
                        logger.bind(tag="BASE").info(f"current_result: {data["current_result"]}")
                        action_message = f'finished the goal {data["action_goal"]} with {data["current_result"]}'
                        action_data = {'content': action_message, 'bot_name': self.bot_name}
                        self._add_action_message(action_data, False)
        except Exception as e:
            logger.error(f"Failed to publish event to Redis: {str(e)}")
            raise
