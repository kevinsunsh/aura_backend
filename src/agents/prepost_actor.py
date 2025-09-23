import pykka
import uuid
import json
import time
from datetime import datetime
import xml.etree.ElementTree as ET
from loguru import logger
from typing import Any, Dict, Optional, Callable
from api_protocol.constant import *
from .msg_preandpost_processor import MessagePreAndPostProcessor
from agents.agent_memory.user_info.manager import DBManager as UserInfoManager
from agents.agent_memory.prompt_manager.scene_info.manager import DBManager as SceneInfoManager
from agents.agent_memory.prompt_manager.character.manager import DBManager as CharacterManager
from agents.agent_memory.prompt_manager.system_preset.manager import DBManager as SystemPresetManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from agents.agent_memory.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from agents.agent_memory.prompt_manager.utils import count_tokens_openai
from agents.agent_memory.message_store import MessageStore, MessageModel
from agents.agent_memory.chat_stream import ChatStreamManager
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.task.task_manager import TaskManager, TaskStateType
from agents.agent_memory.task.task_prompt import TASK_PARAMS_PROMPT

class PrePostActor(pykka.ThreadingActor):
    """预处理和后处理 Actor"""
    
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.asr_result = ""
        self.process_timer = 0
        # 运行期上下文
        self.user_info = None
        self.current_scene_info = None
        self.character = None
        self.bot_name = None
        self.system_preset = None
        self.system_preset_prompts = None
        self.system_preset_prompt_order = None
        self.world_info_scanner = None
        
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            
            if msg_type == "start":
                return self._start(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop()
            elif msg_type == "preprocess":
                return self._preprocess()
            elif msg_type == "postprocess":
                return self._postprocess(message.get("data"))
            elif msg_type == "change_bot_name":
                return self._change_bot_name(message.get("data"))
            elif msg_type == "change_scene_name":
                return self._change_scene_name(message.get("data"))
            elif msg_type == "change_system_preset":
                return self._change_system_preset(message.get("data"))
            elif msg_type == "change_world_info_activate_keys":
                return self._change_world_info_keys(message.get("data"))
            elif msg_type == "char_status":
                CharInstanceInfoManager().upsert_char_instance_info(self.user_id, self.chat_id, message.get("data"))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            elif msg_type == "set_asr_result":
                self.asr_result = message.get("asr_result", "")
                return {"success": True}
            elif msg_type == "set_process_timer":
                self.process_timer = message.get("timer", 0)
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
                
        except Exception as e:
            logger.error(f"PrePost Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start(self, data):
        """启动预处理和后处理器"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            
            # 初始化运行期上下文（对齐 msg_preandpost_processor）
            self.user_info = UserInfoManager().get_user_info_by_user_id(self.user_id)
            # 用户可切换场景，这里以用户当前场景为准
            current_scene_id = self.user_info.current_scene_id if self.user_info and getattr(self.user_info, "current_scene_id", None) else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
            self.current_scene_info = SceneInfoManager().get_scene_info_by_scene_id(current_scene_id)
            self.character = CharacterManager().get_character_by_id(self.current_scene_info.activated_char_id)
            self.bot_name = self.character.name
            self.system_preset = SystemPresetManager().get_system_preset_by_id(self.current_scene_info.activated_system_preset_id)
            self.system_preset_prompts = self.system_preset["prompts"]
            self.system_preset_prompt_order = self.system_preset["prompt_order"]
            self.world_info_scanner = WorldInfoScanner(activate_world_book_ids=self.current_scene_info.activated_world_book_ids)
            # 激活世界书关键词
            self.world_info_scanner.set_activate_keys(self.current_scene_info.activated_world_book_keys)
            
            self.is_running = True
            
            logger.info(f"PrePost Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"PrePost Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop(self):
        """停止预处理和后处理器"""
        try:
            self.is_running = False
            
            logger.info("PrePost Actor停止成功")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"PrePost Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _preprocess(self):
        """执行预处理"""
        if not self.is_running:
            return {"success": False, "error": "PrePost Actor未运行"}
        
        try:
            logger.info("执行预处理")
            # 生成 prompts
            generator = PromptManager(
                chat_id=self.chat_id,
                user_info=self.user_info,
                scene_info=self.current_scene_info,
                system_preset=self.system_preset,
                system_preset_prompts=self.system_preset_prompts,
                system_preset_prompt_order=self.system_preset_prompt_order,
                character=self.character,
                world_info_scanner=self.world_info_scanner
            )
            prompts, token_usage = self._safe_async_generate(generator)
            # 延迟日志
            if self.process_timer:
                logger.bind(tag="DELAY").info(f"Preprocess delay: {int((time.time() - self.process_timer) * 1000)}ms")
            # 通过回调把 prompts 交给 LLM+TTS Actor
            if self.output_callback and prompts:
                self.output_callback({
                    "event": "LLMRun",
                    "prompts": prompts
                })
            # 写入用户消息
            if self.asr_result:
                tokens = count_tokens_openai(self.asr_result)
                message = MessageModel(
                    msg_id=str(uuid.uuid4()),
                    chat_id=self.chat_id,
                    user_id=self.user_id,
                    platform="default",
                    role="user",
                    m_type="text",
                    content=self.asr_result,
                    tokens=tokens,
                    data={},
                    created_at=int(datetime.now().timestamp() * 1000)
                )
                MessageStore.get_instance().add_message(message)
            return {"success": True, "prompts_count": len(prompts) if prompts else 0}
            
        except Exception as e:
            logger.error(f"预处理失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _postprocess(self, data):
        """执行后处理"""
        if not self.is_running:
            return {"success": False, "error": "PrePost Actor未运行"}
        
        try:
            logger.info("执行后处理")
            bot_response = data or {}
            content = bot_response.get("content", "")
            tokens = count_tokens_openai(content)
            message = MessageModel(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_id,
                user_id=self.bot_name or "assistant",
                platform="default",
                role="assistant",
                m_type="text",
                content=content,
                tokens=tokens,
                data={},
                created_at=int(datetime.now().timestamp() * 1000)
            )
            MessageStore.get_instance().add_message(message)
            # chat stream 心跳
            ChatStreamManager.get_instance().update_chat_stream_checked_at(self.chat_id)
            # 任务调度
            self._handle_tasks(bot_response)
            # build_summary_mem
            try:
                task_instance_id = TaskManager.get_instance().schedule_task_instance(self.user_id, "agent_memory", {"user_id": self.user_id, "char_id": self.character.name})
                if task_instance_id:
                    logger.bind(tag="TASK").info(f"成功调度任务: {task_instance_id}")
                else:
                    logger.bind(tag="TASK").warning("调度任务失败: agent_memory")
            except Exception as e:
                logger.bind(tag="TASK").error(f"agent_memory 任务调度异常: {e}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"后处理失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _change_bot_name(self, bot_name):
        """更改机器人名称"""
        try:
            logger.bind(tag="BASE").info(f"更改机器人名称为: {bot_name}")
            if bot_name:
                self.bot_name = bot_name
                # 同步角色信息（若存在同名角色）
                try:
                    self.character = CharacterManager().get_character_by_name(self.bot_name) or self.character
                except Exception:
                    pass
            return {"success": True}
            
        except Exception as e:
            logger.error(f"更改机器人名称失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _change_scene_name(self, scene_name):
        """更改场景名称"""
        try:
            logger.bind(tag="BASE").info(f"更改场景名称为: {scene_name}")
            if scene_name:
                scene_info = SceneInfoManager().get_scene_info_by_scene_name(scene_name)
                UserInfoManager().update_user_info(self.user_id, {"current_scene_id": scene_info.scene_id})
            return {"success": True}
        except Exception as e:
            logger.error(f"更改场景名称失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _change_system_preset(self, preset):
        """更改系统预设"""
        try:
            logger.info(f"更改系统预设为: {preset}")
            if isinstance(preset, str) and preset:
                sp = SystemPresetManager().get_system_preset_by_name(preset)
            elif isinstance(preset, dict) and preset.get("id"):
                sp = SystemPresetManager().get_system_preset_by_id(preset["id"])  
            else:
                sp = None
            if sp:
                self.system_preset = sp
                self.system_preset_prompts = sp["prompts"]
                self.system_preset_prompt_order = sp["prompt_order"]
            return {"success": True}
            
        except Exception as e:
            logger.error(f"更改系统预设失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _change_world_info_keys(self, keys):
        """更改世界信息激活键"""
        try:
            logger.info(f"更改世界信息激活键: {keys}")
            if not self.world_info_scanner:
                self.world_info_scanner = WorldInfoScanner(activate_world_book_ids=self.current_scene_info.activated_world_book_ids)
            if isinstance(keys, list):
                self.world_info_scanner.set_activate_keys(keys)
            elif isinstance(keys, dict) and keys.get("activate_keys"):
                self.world_info_scanner.set_activate_keys(keys.get("activate_keys"))
            return {"success": True}
            
        except Exception as e:
            logger.error(f"更改世界信息激活键失败: {e}")
            return {"success": False, "error": str(e)}

    def _safe_async_generate(self, generator: PromptManager):
        """在同步Actor中包装调用异步Prompt生成器"""
        try:
            # PromptManager.generate 是异步方法，这里用简单的事件循环桥接
            import asyncio
            async def _run():
                return await generator.generate(GenerationType.NORMAL, GenerationOptions())
            return asyncio.run(_run())
        except RuntimeError:
            # 已存在事件循环（例如在某些环境），退化为新循环
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(generator.generate(GenerationType.NORMAL, GenerationOptions()))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"生成prompts失败: {e}")
            return None, None

    def _handle_tasks(self, bot_response: dict):
        """解析并调度任务（与 msg_preandpost_processor 对齐）"""
        request_tasks = bot_response.get("request_tasks", "")
        logger.bind(tag="TASK").info(f"request_tasks: {request_tasks}")
        if request_tasks and len(request_tasks.strip()) > 0:
            try:
                request_tasks = f"<tasks>{request_tasks}</tasks>"
                root = ET.fromstring(request_tasks)
                task_elements = root.findall('task')
                for task_elem in task_elements:
                    task_name = task_elem.get('name')
                    task_params = task_elem.get('params', '')
                    if not task_name:
                        continue
                    task_info = TaskManager.get_instance().get_task_by_name(task_name)
                    if not task_info:
                        continue
                    task_params_schema = task_info.task_request_params_schema
                    chat_model = get_chat_model_by_type("planner")
                    prompt = TASK_PARAMS_PROMPT.format(
                        params_input=task_params,
                        params_schema=task_params_schema
                    )
                    task_params_str = chat_model.invoke([
                        {"role": "system",  "content": prompt}
                    ])
                    task_instance_id = TaskManager.get_instance().schedule_task_instance(self.user_id, task_name, json.loads(task_params_str.content))
                    if task_instance_id:
                        logger.bind(tag="TASK").info(f"成功调度任务: {task_instance_id}")
                    else:
                        logger.bind(tag="TASK").warning(f"调度任务失败: {task_name}")
            except ET.ParseError as e:
                logger.bind(tag="TASK").warning(f"request_tasks XML解析失败: {e}")
            except Exception as e:
                logger.bind(tag="TASK").error(f"request_tasks 任务解析异常: {e}")
        dismiss_tasks = bot_response.get("dismiss_tasks", "")
        if dismiss_tasks and len(dismiss_tasks.strip()) > 0:
            try:
                dismiss_tasks = f"<tasks>{dismiss_tasks}</tasks>"
                root = ET.fromstring(dismiss_tasks)
                task_elements = root.findall('task')
                for task_elem in task_elements:
                    task_instance_id = task_elem.get('id')
                    if task_instance_id:
                        TaskManager.get_instance().dismiss_task_instance(self.user_id, task_instance_id, TaskStateType.FINISHED)
                        logger.bind(tag="TASK").info(f"重置任务状态: {task_instance_id}")
            except ET.ParseError as e:
                logger.bind(tag="TASK").warning(f"dismiss_tasks XML解析失败: {e}")
            except Exception as e:
                logger.bind(tag="TASK").error(f"dismiss_tasks 任务解析异常: {e}")
        # 处理异常未调度的 started
        try:
            started_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.STARTED)
            if started_tasks:
                for task in started_tasks:
                    if task.created_at < int(datetime.now().timestamp() * 1000) - 60 * 1000:
                        TaskManager.get_instance().call_task_executor(task.task_instance_id, task.task_params)
        except Exception as e:
            logger.bind(tag="TASK").error(f"started_tasks 任务解析异常: {e}")
        # 处理 time_out_running_tasks
        try:
            running_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.RUNNING)
            if running_tasks:
                for task in running_tasks:
                    if task.updated_at < int(datetime.now().timestamp() * 1000) - 60 * 1000:
                        TaskManager.get_instance().dismiss_task_instance(self.user_id, task.task_instance_id, TaskStateType.RUNNING)
                        logger.bind(tag="TASK").info(f"忽略超时任务: {task.task_instance_id}")
        except Exception as e:
            logger.bind(tag="TASK").error(f"time_out_running_tasks 任务解析异常: {e}")
        # 处理 time_out_finished_tasks
        try:
            finished_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.FINISHED)
            if finished_tasks:
                for task in finished_tasks:
                    if task.updated_at < int(datetime.now().timestamp() * 1000) - 120 * 1000:
                        TaskManager.get_instance().dismiss_task_instance(self.user_id, task.task_instance_id, TaskStateType.FINISHED)
                        logger.bind(tag="TASK").info(f"忽略超时任务: {task.task_instance_id}")
        except Exception as e:
            logger.bind(tag="TASK").error(f"time_out_finished_tasks 任务解析异常: {e}")
