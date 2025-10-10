import pykka
import asyncio
import time
import queue
from loguru import logger
from typing import Dict, Any, Callable, Optional
from enum import Enum
from abc import ABC

from .vad_actor import VADActor
from .e2e_actor import E2EActor
from .llm_chat_actor import LLMChatActor
from .llm_action_actor import LLMActionActor
from .tts_actor import TTSActor
from .prepost_actor import PrePostActor
from api_protocol.constant import *
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager
from agents.agent_memory.user_info.manager import DBManager as UserInfoManager
from agents.agent_memory.prompt_manager.scene_info.manager import DBManager as SceneInfoManager
from agents.agent_memory.prompt_manager.character.manager import DBManager as CharacterManager
from agents.agent_memory.prompt_manager.system_preset.manager import DBManager as SystemPresetManager
from agents.agent_memory.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager

class ActorMessageProcessor:
    """
    基于Pykka Actor的消息处理器
    """
    instance = None
    
    @staticmethod
    def get_instance():
        if ActorMessageProcessor.instance is None:
            ActorMessageProcessor.instance = ActorMessageProcessor()
        return ActorMessageProcessor.instance
    
    def __init__(self):
        self.chat_id = None
        self.user_id = None
        self.websocket_send_callback = None
        self.sse_started = False
        # Actor引用
        self.vad_actor = None
        self.e2e_actor = None
        self.llm_chat_actor = None
        self.llm_action_actor = None
        self.tts_actor = None
        self.prepost_actor = None
        # 共享状态
        self.asr_result = ""
        self.asr_is_started = False
        self.process_timer = 0
        self.prompt_manager = None
        # 启动所有Actor
        self._start_actors()
    
    def _start_actors(self):
        """启动所有Actor"""
        try:
            # 创建所有Actor实例
            self.vad_actor = VADActor.start()
            self.e2e_actor = E2EActor.start()
            # self.llm_actor = LLMActor.start()
            self.llm_chat_actor = LLMChatActor.start()
            self.llm_action_actor = LLMActionActor.start()
            self.tts_actor = TTSActor.start()
            self.prepost_actor = PrePostActor.start()
            # 设置输出回调
            self.vad_actor.tell({"type": "set_callback", "callback": self._handle_vad_output})
            self.e2e_actor.tell({"type": "set_callback", "callback": self._handle_e2e_output})
            # self.llm_actor.tell({"type": "set_callback", "callback": self._handle_llm_output})
            self.llm_chat_actor.tell({"type": "set_callback", "callback": self._handle_llm_chat_output})
            self.llm_action_actor.tell({"type": "set_callback", "callback": self._handle_llm_action_output})
            self.tts_actor.tell({"type": "set_callback", "callback": self._handle_tts_output})
            self.prepost_actor.tell({"type": "set_callback", "callback": self._handle_prepost_output})
            logger.info("所有Actor启动完成")
        except Exception as e:
            logger.error(f"启动Actor失败: {e}")
            raise e
    
    def _handle_vad_output(self, message):
        """处理VAD输出"""
        logger.info(f"收到VAD输出: {message}")
        # 处理VAD检测到的事件
        if message.get("event") == ServerEvent.ASRInfo:
            # VAD检测到语音开始
            if not self.asr_is_started:
                self.asr_is_started = True
                logger.info("VAD检测到语音开始")
                # 发送中断信号给其他Actor
                # LLM中断逻辑：目前仅透传（保留扩展点）
                # TTS中断：可在此扩展调用
                # 发送ASRInfo事件到WebSocket
                if self.websocket_send_callback:
                    self.websocket_send_callback(message)
            else:
                logger.debug("VAD检测到语音开始，但ASR已开始")
        elif message.get("event") == ServerEvent.ASREnded:
            # VAD检测到语音结束
            if self.asr_is_started:
                self.asr_is_started = False
                self.process_timer = time.time()
                logger.bind(tag="BASE").info("VAD检测到语音结束")
                self.prepost_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
                # 发送预处理信号
                self.prepost_actor.tell({"type": "preprocess"})
                # 发送ASREnded事件到WebSocket
                if self.websocket_send_callback:
                    self.websocket_send_callback(message)
            else:
                logger.warning("VAD检测到语音结束，但ASR未开始")
    
    def _handle_e2e_output(self, message):
        """处理E2E输出"""
        logger.debug(f"收到E2E输出: {message}")
        # 处理E2E检测到的事件
        if message.get("event") == ServerEvent.ASRInfo:
            # E2E检测到语音开始
            if not self.asr_is_started:
                self.asr_is_started = True
                logger.bind(tag="BASE").info("E2E检测到语音开始")
                # 发送中断信号给其他Actor
                # 同上
                # 发送ASRInfo事件到WebSocket
                if self.websocket_send_callback:
                    self.websocket_send_callback(message)
            else:
                logger.debug("E2E检测到语音开始，但ASR已开始")
        elif message.get("event") == ServerEvent.ASREnded:
            # E2E检测到语音结束
            if self.asr_is_started:
                self.asr_is_started = False
                self.process_timer = time.time()
                logger.bind(tag="BASE").info("E2E检测到语音结束")
                self.prepost_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
                # 发送预处理信号
                self.prepost_actor.tell({"type": "preprocess"})
                # 发送ASREnded事件到WebSocket
                if self.websocket_send_callback:
                    self.websocket_send_callback(message)
            else:
                logger.warning("E2E检测到语音结束，但ASR未开始")
        # 处理其他E2E输出消息
        elif message.get("event") == ServerEvent.ASRResponse:
            # 直接转发到WebSocket
            if self.websocket_send_callback:
                self.websocket_send_callback(message)
            # 同步ASR文本到PrePost
            try:
                payload = message.get("payload_msg", {})
                content = payload.get("results", [{}])[0].get("text", "") if isinstance(payload, dict) else ""
                if content:
                    self.asr_result = content
                    if self.prepost_actor:
                        self.prepost_actor.tell({"type": "set_asr_result", "asr_result": content})
            except Exception:
                pass
    
    def _handle_llm_chat_output(self, message):
        """处理Chat LLM输出，并将内容转发给TTSActor"""
        logger.bind(tag="BASE").info(f"收到Chat LLM输出: {message}")
        try:
            if message.get("event") == ServerEvent.ChatResponse:
                content = message.get("payload_msg", {}).get("content", "")
                if content:
                    self.tts_actor.tell({"type": "send_text_chunk", "text": content, "start": False, "end": False})
            elif message.get("event") == ServerEvent.ChatResponseEnd:
                # self.tts_actor.tell({"type": "send_text_chunk", "text": "", "start": False, "end": True})
                pass
            elif message.get("event") == ServerEvent.ChatEnded:
                self.tts_actor.tell({"type": "send_text_chunk", "text": "", "start": False, "end": True})
                self.prepost_actor.tell({"type": "postprocess", "data": message.get("payload_msg", {})})
            elif message.get("event") == ServerEvent.ChatActionGoal:
                self.llm_action_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
                self.llm_action_actor.tell({"type": "goal_input", "data": message.get("payload_msg", {})})
                return
            # 透传到前端
            if self.websocket_send_callback:
                self.websocket_send_callback(message)
        except Exception:
            logger.bind(tag="BASE").info(f"处理Chat LLM输出失败: {message}")
    
    def _handle_llm_action_output(self, message):
        """处理Action LLM输出：仅透传与记录，用于前端展示或日志"""
        logger.bind(tag="BASE").debug(f"收到Action LLM输出: {message}")
        try:
            if message.get("event") == ServerEvent.ChatActionResponse:
                self.llm_chat_actor.tell({"type": "response_action_message", "data": message.get("payload_msg", {})})
            if self.websocket_send_callback:
                self.websocket_send_callback(message)
        except Exception:
            logger.bind(tag="BASE").info(f"处理Action LLM输出失败: {message}")
    
    def _handle_tts_output(self, message):
        """处理TTS输出并透传到 websocket"""
        logger.debug(f"收到TTS输出: {message}")
        if message.get("event") == ServerEvent.TTSSentenceStart:
            send_msg = {
                "event": ServerEvent.TTSSentenceStart,
                "payload_msg": {
                    "text": message.get("payload_msg", {}).get("text", ""),
                    "session_id": message.get("session_id", ""),
                    "type": "int16"
                }
            }
            if self.websocket_send_callback:
                self.websocket_send_callback(send_msg)
            return
        if self.websocket_send_callback:
            self.websocket_send_callback(message)
    
    def _handle_prepost_output(self, message):
        """处理预处理/后处理输出"""
        logger.debug(f"收到PrePost输出: {message}")
        # 将PrePost生成的prompts转发给LLM+TTS
        if isinstance(message, dict) and message.get("event") == "ChatLLMRun":
            prompts = message.get("prompts")
            if prompts and self.llm_chat_actor:
                prompts.append({"role": "user", "content": self.asr_result})
                self.llm_chat_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
                self.llm_chat_actor.tell({"type": "run", "data": prompts})
        # elif isinstance(message, dict) and message.get("event") == "ActionLLMRun":
        #     # 先通过 Planning 生成执行计划，再交给 Action 执行
        #     if  self.llm_action_actor:
        #         # 将原 prompts 作为规划输入（包含场景/角色/世界信息）
        #         self.llm_action_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
        #         self.llm_action_actor.tell({"type": "user_input", "data": message.get("user_input")})
    
    def handle_message(self, message_data: Dict[str, Any]):
        """
        分发消息到各个Actor
        """
        if message_data.get("event") == ClientEvent.SayHello:
            # 同步输入与计时器
            self.asr_result = message_data["payload_msg"].get("content", "")
            self.process_timer = time.time()
            if self.prepost_actor:
                self.prepost_actor.tell({"type": "set_asr_result", "asr_result": self.asr_result})
                self.prepost_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
            # 触发预处理
            self.prepost_actor.tell({"type": "preprocess"})
            logger.bind(tag="BASE").info("处理SayHello消息")
        elif message_data.get("event") == ClientEvent.TaskRequest:
            if "payload_msg" in message_data and message_data["payload_msg"]:
                payload_msg = message_data["payload_msg"]
            else:
                return {"success": False, "error": "payload_msg is required"}
            # 发送到VAD Actor
            self.vad_actor.tell({"type": "input", "data": payload_msg})
            # 发送到E2E Actor
            self.e2e_actor.tell({"type": "input", "data": payload_msg})
        elif message_data.get("event") == ClientEvent.SpeakEnded:
            if self.asr_is_started:
                self.asr_is_started = False
                self.prepost_actor.tell({"type": "preprocess"})
                self.process_timer = time.time()
                self.prepost_actor.tell({"type": "set_process_timer", "timer": self.process_timer})
                logger.bind(tag="BASE").info("处理SpeakEnded消息")
            else:
                logger.bind(tag="BASE").info("SpeakEnded，但ASR未开始")
        elif message_data.get("event") == ClientEvent.WorldInfoActivateKeys:
            self.prepost_actor.tell({
                "type": "change_world_info_activate_keys",
                "data": message_data.get("payload_msg", {}).get("activate_keys", [])
            })
            if len(message_data.get("payload_msg", {}).get("activate_keys", [])) > 0:
                self.prepost_actor.tell({
                    "type": "change_world_info_activate_keys",
                    "data": message_data.get("payload_msg", {}).get("activate_keys", [])
                })
            if len(message_data.get("payload_msg", {}).get("scene_name", "")) > 0:
                self.prepost_actor.tell({
                    "type": "change_scene_name",
                    "data": message_data.get("payload_msg", {}).get("scene_name", "")
                })
        elif message_data.get("event") == ClientEvent.ChangeBotID:
            self.prepost_actor.tell({
                "type": "change_bot_name",
                "data": message_data.get("payload_msg", {}).get("bot_name", "")
            })
        elif message_data.get("event") == ClientEvent.ChangeSystemPreset:
            self.prepost_actor.tell({
                "type": "change_system_preset",
                "data": message_data.get("payload_msg", {}).get("system_preset", "")
            })
        elif message_data.get("event") == ClientEvent.CharStatus:
            self.prepost_actor.tell({
                "type": "char_status",
                "data": message_data.get("payload_msg", {}).get("char_status", "")
            })
            action = message_data.get("payload_msg", {}).get("char_status", "").get("action", None)
            if action:
                self.llm_action_actor.tell({"type": "action_step_finished", "data": action})
        return {"success": True, "action": "audio_task_started", "chat_id": self.chat_id}
    
    def start(self, chat_id: str, user_id: str, websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        """启动消息处理器"""
        self.chat_id = chat_id
        self.user_id = user_id
        self.websocket_send_callback = websocket_send_callback
        logger.info(f"ActorMessageProcessor启动开始: chat_id={self.chat_id}")
        prompt_manager = PromptManager.get_instance()
        # 初始化运行期上下文（对齐 msg_preandpost_processor）
        user_info = UserInfoManager().get_user_info_by_user_id(self.user_id)
        # 用户可切换场景，这里以用户当前场景为准
        char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(self.user_id, self.chat_id)
        current_scene_id = char_instance_info.current_scene_id if char_instance_info else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
        current_scene_info = SceneInfoManager().get_scene_info_by_scene_id(current_scene_id)
        character = CharacterManager().get_character_by_id(current_scene_info.activated_char_id)
        system_preset = SystemPresetManager().get_system_preset_by_id(current_scene_info.activated_system_preset_id)
        system_preset_prompts = system_preset["prompts"]
        system_preset_prompt_order = system_preset["prompt_order"]
        world_info_scanner = WorldInfoScanner(activate_world_book_ids=current_scene_info.activated_world_book_ids)
        # 激活世界书关键词
        world_info_scanner.set_activate_keys(current_scene_info.activated_world_book_keys)
        prompt_manager.update_instance(
            chat_id=self.chat_id,
            user_info=user_info,
            scene_info=current_scene_info,
            system_preset=system_preset,
            system_preset_prompts=system_preset_prompts,
            system_preset_prompt_order=system_preset_prompt_order,
            character=character,
            world_info_scanner=world_info_scanner
        )
        # 启动所有Actor
        start_data = {"chat_id": self.chat_id, "user_id": self.user_id}
        
        # 使用ask方法等待所有Actor启动完成
        vad_result = self.vad_actor.ask({"type": "start", "data": start_data}, timeout=5)
        e2e_result = self.e2e_actor.ask({"type": "start", "data": start_data}, timeout=5)
        # llm_result = self.llm_actor.ask({"type": "start", "data": start_data}, timeout=5)
        llm_chat_result = self.llm_chat_actor.ask({"type": "start", "data": start_data}, timeout=5)
        llm_action_result = self.llm_action_actor.ask({"type": "start", "data": start_data}, timeout=5)
        tts_result = self.tts_actor.ask({"type": "start", "data": start_data}, timeout=5)
        prepost_result = self.prepost_actor.ask({"type": "start", "data": start_data}, timeout=60)
        
        # 检查启动结果
        if (vad_result.get("success") and e2e_result.get("success") and 
            llm_chat_result.get("success") and llm_action_result.get("success") and tts_result.get("success") and prepost_result.get("success")):
            logger.bind(tag="BASE").info("ActorMessageProcessor启动完成")
            return True
        else:
            logger.bind(tag="BASE").error("ActorMessageProcessor启动失败")
            return False
    
    def cleanup(self):
        """清理资源"""
        logger.info(f"开始清理ActorMessageProcessor: chat_id={self.chat_id}")
        
        self.websocket_send_callback = None
        self.sse_started = False
        
        # 停止所有Actor
        if self.vad_actor:
            self.vad_actor.tell({"type": "stop"})
        if self.e2e_actor:
            self.e2e_actor.tell({"type": "stop"})
        if self.llm_chat_actor:
            self.llm_chat_actor.tell({"type": "stop"})
        if self.llm_action_actor:
            self.llm_action_actor.tell({"type": "stop"})
        if self.tts_actor:
            self.tts_actor.tell({"type": "stop"})
        if self.prepost_actor:
            self.prepost_actor.tell({"type": "stop"})
        logger.info("ActorMessageProcessor清理完成")
        return {"success": True}
