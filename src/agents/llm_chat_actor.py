import pykka
import asyncio
import time
from datetime import datetime
from loguru import logger
from typing import Optional, Callable, Dict, Any
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager, GenerationType
from api_protocol.constant import *
from .message_processor_text import StreamingTagParser
from agents.agent_memory.configuration import get_chat_model_by_type
from utils.utils import safe_call
from agents.agent_memory.prompt_manager.system_prompt.default import ACTION_RESPONSE_FORMAT_PROMPT

class LLMChatActor(pykka.ThreadingActor):
    """仅负责文本处理（LLM）的 Actor"""

    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.parser = StreamingTagParser(tag_callback=self.tag_callback)
        self.process_timer = 0
        self.is_interruption = False
        self.action_content = ""
        self.action_tag_start = False
    
    def on_receive(self, message):
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "run":
                return self._run_llm(message.get("data"))
            elif msg_type == "response_action_message":
                return self._run_action_llm(message.get("data"))
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
            logger.bind(tag="BASE").info(f"LLMChatActor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
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
    
    def _run_action_llm(self, data):
        try:
            action_reasoning = data.get("params", {}).get("attribute", {}).get("content", "")
            self._run_async(self.handle_action_message(action_reasoning))
            return {"success": True}
        except Exception as e:
            logger.error(f"LLMActor运行Action LLM失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def tag_callback(self, payload):
        if payload["tag"] == "speak":
            if payload["status"] == "start":
                if self.output_callback:
                    await safe_call(self.output_callback, {
                        "event": ServerEvent.ChatResponseParams,
                        "payload_msg": {
                            "params": payload["attributes"]
                        }
                    })
            elif payload["status"] == "streaming":
                if self.output_callback:
                    content = payload["content"].replace('\n', '').replace('\r', '')
                    await safe_call(self.output_callback, {
                        "event": ServerEvent.ChatResponse,
                        "payload_msg": {
                            "content": content
                        }
                    })
            elif payload["status"] == "end":
                if self.output_callback:
                    await safe_call(self.output_callback, {
                        "event": ServerEvent.ChatResponseEnd,
                    })
        elif payload["tag"] == "action":
            logger.bind(tag="BASE").info(f"action payload: {payload}")
            if payload["status"] == "start":
                self.action_tag_start = True
                self.action_content = ""
            elif payload["status"] == "streaming":
                self.action_content += payload["content"]
            elif payload["status"] == "end":
                logger.bind(tag="BASE").info(f"end with action_content: {self.action_content}")
                if self.output_callback:
                    if self.action_tag_start:
                        self.action_tag_start = False
                        await safe_call(self.output_callback, {
                            "event": ServerEvent.ChatActionGoal,
                            "payload_msg": {
                                "content": self.action_content
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
            # for prompt in prompts:
            #     logger.bind(tag="BASE").info(f"{prompt['role']}: {prompt['content']}")
            chat_model = get_chat_model_by_type("pfc_action_planner")
            final_response = ""
            first_chunk = True
            logger.bind(tag="DELAY").info(f"start llm response delay: {int((datetime.now().timestamp() - self.process_timer) * 1000)}ms")
            async for chunk in chat_model.astream(prompts, extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    # logger.bind(tag="BASE").info(f"chunk: {chunk.content}")
                    if self.is_interruption:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    final_response += chunk.content
                    if first_chunk:
                        first_chunk = False
                        logger.bind(tag="TTS").info(f"start streaming response delay: {int((datetime.now().timestamp() - self.process_timer) * 1000)}ms")
                    await self.parser.feed(chunk.content)
            await self.parser.end()
            if self.output_callback:
                await safe_call(self.output_callback, {
                    "event": ServerEvent.ChatEnded,
                    "payload_msg": {
                        "content": final_response
                    }
                })
            logger.bind(tag="TASK").info(f"final_response: {final_response}")
        except asyncio.CancelledError:
            logger.bind(tag="BASE").info(f"回复任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.bind(tag="BASE").info(f"生成被动回复时出错: {str(e)}")
    
    async def handle_action_message(self, action_message: str) -> Dict[str, Any]:
        try:
            prompts, token_usage = await PromptManager.get_instance().generate(GenerationType.ACTION_RESPONSE)
            action_response_format_prompt = ACTION_RESPONSE_FORMAT_PROMPT.format(action_message=action_message)
            prompts.append({"role": "system", "content": action_response_format_prompt})
            for prompt in prompts:
                logger.bind(tag="BASE").info(f"{prompt['role']}: {prompt['content']}")
            chat_model = get_chat_model_by_type("vlm")
            final_response = ""
            first_chunk = True
            logger.bind(tag="DELAY").info(f"start llm response delay: {int((datetime.now().timestamp() - self.process_timer) * 1000)}ms")
            async for chunk in chat_model.astream(prompts, extra_body={"thinking": {"type": "disabled"}}):
                if hasattr(chunk, 'content'):
                    # logger.bind(tag="BASE").info(f"chunk: {chunk.content}")
                    if self.is_interruption:
                        logger.bind(tag="TTS").info(f"打断流式响应，继续倾听")
                        break
                    final_response += chunk.content
                    if first_chunk:
                        first_chunk = False
                        logger.bind(tag="TTS").info(f"start streaming response delay: {int((datetime.now().timestamp() - self.process_timer) * 1000)}ms")
                    await self.parser.feed(chunk.content)
            await self.parser.end()
            if self.output_callback:
                await safe_call(self.output_callback, {
                    "event": ServerEvent.ChatEnded,
                    "payload_msg": {
                        "content": final_response
                    }
                })
            logger.bind(tag="TASK").info(f"final_response: {final_response}")
        except asyncio.CancelledError:
            logger.bind(tag="BASE").info(f"回复任务被取消: chat_id={self.chat_id}")
        except Exception as e:
            logger.bind(tag="BASE").info(f"生成被动回复时出错: {str(e)}")
