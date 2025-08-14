import uuid
import json
import asyncio
from abc import ABC
from loguru import logger
from datetime import datetime
import xml.etree.ElementTree as ET
from agents.agent_memory.task.task_manager import TaskManager, TaskStateType
from agents.agent_memory.chat_stream import ChatStreamManager
from agents.agent_memory.message_store import MessageStore, MessageModel
from utils.todo_mock_func import (
    _build_chat_history_str
)
from agents.agent_memory.task.task_prompt import TASK_PARAMS_PROMPT
from configuration import get_chat_model_by_type
from langchain_core.messages import SystemMessage
from utils.utils import ActiveClientType
from agents.prompt_manager.prompt_manager import PromptManager
from agents.prompt_manager.character.manager import DBManager as CharacterManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from agents.prompt_manager.system_preset.manager import DBManager as SystemPresetManager
from agents.prompt_manager.utils import count_tokens_openai

class MessagePreAndPostProcessor(ABC):
    """MISC客户端包装器"""
    def __init__(self, input_queue, llm_input_queues, asr_result, is_process_running, process_timer):
        self.input_queue = input_queue
        self.llm_input_queues = llm_input_queues
        self.asr_result = asr_result
        self.is_process_running = is_process_running
        self.process_timer = process_timer
        self.history_check_interval = 20000 #ms
        self.chat_id = None
        self.user_id = None
        self.session_prompt = ""
        self.bot_name = "Seraphina"
        self.character = CharacterManager().get_character_by_name(self.bot_name)
        # self.system_preset = SystemPresetManager().get_system_preset_by_name("deepseek-R1 北棱预设v1.2 test(角色扮演特化)")
        self.system_preset = SystemPresetManager().get_system_preset_by_name("Default")
        self.generator = PromptManager(
            chat_id="test_user_123444",
            user_id="test_user_123444",
            system_preset=self.system_preset,
            character=self.character,
            world_info_scanner=WorldInfoScanner()
        )
    
    @staticmethod
    def process_entry(input_queue, llm_input_queues, asr_result, is_process_running, process_timer):
        asyncio.run(MessagePreAndPostProcessor.main(input_queue, llm_input_queues, asr_result, is_process_running, process_timer))
    
    @staticmethod
    async def main(input_queue, llm_input_queues, asr_result, is_process_running, process_timer):
        loop = asyncio.get_event_loop()
        client = MessagePreAndPostProcessor(
            input_queue=input_queue,
            llm_input_queues=llm_input_queues,
            asr_result=asr_result,
            is_process_running=is_process_running,
            process_timer=process_timer
        )
        TaskManager.get_instance().initialize()
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                client.chat_id = msg["data"]["chat_id"]
                client.user_id = msg["data"]["user_id"]
                client.session_prompt = msg["data"]["session_prompt"]
                client.is_process_running.value = True
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "preprocess":
                if client.is_process_running.value:
                    logger.bind(tag="BASE").info("预处理用户输入")
                    await client.preprocess()
            elif isinstance(msg, dict) and msg.get("type") == "postprocess":
                if client.is_process_running.value:
                    await client.postprocess(msg["data"])
    
    async def preprocess(self) -> str:
        """预处理用户输入"""
        # now_timestamp = int(datetime.now().timestamp() * 1000)
        # history_messages = MessageStore.get_instance().get_messages_by_time_range(
        #     self.chat_id, 
        #     now_timestamp - self.history_check_interval, 
        #     now_timestamp
        # )
        # logger.bind(tag="DELAY").info(f"history_messages delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
        # 更新观察信息
        # chat_history_str = _build_chat_history_str(history_messages)
        # chat_history_str += f"{self.user_id}说:"
        # chat_history_str += """ {user_input}\n"""
        # goals_str = ""
        # knowledge_info_str = ""        
        # input_template = f"人设：{self.session_prompt}\n"
        # input_template += f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        # input_template += f"当前地点：上海\n"
        # if len(goals_str) > 0:
        #     input_template += f"当前对话目标：{goals_str}\n"
        # if len(knowledge_info_str) > 0:
        #     input_template += f"供参考的相关知识和记忆：{knowledge_info_str}\n"
        # input_template += TaskManager.get_instance().get_all_tasks_status_prompt_for_llm(self.user_id).replace('{', '').replace('}', '').replace('"', '')
        # logger.bind(tag="DELAY").info(f"Task status delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
        # input_template += TaskManager.get_instance().get_task_prompt_for_llm_by_type("search_info")
        # logger.bind(tag="DELAY").info(f"search_info task delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
        # input_template += f"最近的聊天记录：{chat_history_str}\n"
        
        # logger.bind(tag="TASK").info(f"input_template: {input_template}")
        prompts, token_usage = await self.generator.generate(GenerationType.NORMAL, GenerationOptions())
        logger.bind(tag="DELAY").info(f"Preprocess delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
        self.llm_input_queues.put({
            "type": "run",
            "data": prompts
        })
        await asyncio.sleep(0.5)
        
        # 创建消息对象
        tokens = count_tokens_openai(self.asr_result.value.decode("utf-8"))
        message = MessageModel(
            msg_id=str(uuid.uuid4()),
            chat_id=self.chat_id,
            user_id=self.user_id,
            platform="default",
            role="user",
            m_type="text",
            content=self.asr_result.value.decode("utf-8"),
            tokens=tokens,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        )
        # 存储到消息存储
        MessageStore.get_instance().add_message(message)
    
    async def postprocess(self, bot_response: dict) -> str:
        """后处理用户输入"""
        tokens = count_tokens_openai(bot_response.get("content", ""))
        message = MessageModel(
            msg_id=str(uuid.uuid4()),
            chat_id=self.chat_id,
            user_id=self.bot_name,
            platform="default",
            role="assistant",
            m_type="text",
            content=bot_response.get("content", ""),
            tokens=tokens,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        )
        # 存储到消息存储
        MessageStore.get_instance().add_message(message)
        ChatStreamManager.get_instance().update_chat_stream_checked_at(self.chat_id)

        request_tasks = bot_response.get("request_tasks", "")
        # 解析task标签，例如 <task name="web_search" params="天气查询"/>
        logger.bind(tag="TASK").info(f"request_tasks: {request_tasks}")
        
        if request_tasks and len(request_tasks.strip()) > 0:
            try:
                # 包装成根元素，因为request_tasks只包含多个task标签
                request_tasks = f"<tasks>{request_tasks}</tasks>"
                
                root = ET.fromstring(request_tasks)
                
                # 调试：显示XML结构
                logger.bind(tag="TASK").info(f"XML结构: {ET.tostring(root, encoding='unicode')}")
                
                # 查找所有task元素
                task_elements = root.findall('task')
                
                logger.bind(tag="TASK").info(f"找到 {len(task_elements)} 个task元素")
                
                for task_elem in task_elements:
                    task_name = task_elem.get('name')
                    task_params = task_elem.get('params', '')  # params可能不存在
                    if task_name:
                        logger.bind(tag="TASK").info(f"解析到任务: name={task_name}, params={task_params}")
                        task_info = TaskManager.get_instance().get_task_by_name(task_name)
                        if task_info:
                            task_params_schema = task_info.task_request_params_schema
                        else:
                            continue
                        chat_model = get_chat_model_by_type("planner")
                        prompt = TASK_PARAMS_PROMPT.format(
                            params_input=task_params,
                            params_schema=task_params_schema
                        )
                        task_params_str = await chat_model.ainvoke([
                            SystemMessage(content=prompt)
                        ])
                        # 调度任务
                        task_instance_id = TaskManager.get_instance().schedule_task_instance(self.user_id, task_name, json.loads(task_params_str.content))
                        if task_instance_id:
                            logger.bind(tag="TASK").info(f"成功调度任务: {task_instance_id}")
                        else:
                            logger.bind(tag="TASK").warning(f"调度任务失败: {task_name}")
            except ET.ParseError as e:
                logger.bind(tag="TASK").warning(f"request_tasks XML解析失败: {e}")
            except Exception as e:
                logger.bind(tag="TASK").error(f"request_tasks 任务解析异常: {e}")
        
        # 处理dismiss_tasks
        dismiss_tasks = bot_response.get("dismiss_tasks", "")
        if dismiss_tasks and len(dismiss_tasks.strip()) > 0:
            try:
                # 包装成根元素，因为dismiss_tasks只包含多个task标签
                dismiss_tasks = f"<tasks>{dismiss_tasks}</tasks>"
                logger.bind(tag="TASK").info(f"dismiss_tasks: {dismiss_tasks}")
                
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
        
        # 处理异常未调度的started任务
        started_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.STARTED)
        if started_tasks:
            try:
                for task in started_tasks:
                    if task.created_at < int(datetime.now().timestamp() * 1000) - 60 * 1000:
                        TaskManager.get_instance().call_task_executor(task.task_instance_id, task.task_params)
            except Exception as e:
                logger.bind(tag="TASK").error(f"started_tasks 任务解析异常: {e}")

        # 处理time_out_running_tasks
        running_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.RUNNING)
        if running_tasks:
            try:
                for task in running_tasks:
                    if task.updated_at < int(datetime.now().timestamp() * 1000) - 60 * 1000:
                        TaskManager.get_instance().dismiss_task_instance(self.user_id, task.task_instance_id, TaskStateType.RUNNING)
                        logger.bind(tag="TASK").info(f"忽略超时任务: {task.task_instance_id}")
            except ET.ParseError as e:
                logger.bind(tag="TASK").warning(f"time_out_running_tasks XML解析失败: {e}")
            except Exception as e:
                logger.bind(tag="TASK").error(f"time_out_running_tasks 任务解析异常: {e}")
        
        # 处理time_out_finished_tasks
        finished_tasks = TaskManager.get_instance().get_task_instances_by_state(self.user_id, TaskStateType.FINISHED)
        if finished_tasks:
            try:
                for task in finished_tasks:
                    if task.updated_at < int(datetime.now().timestamp() * 1000) - 120 * 1000:
                        TaskManager.get_instance().dismiss_task_instance(self.user_id, task.task_instance_id, TaskStateType.FINISHED)
                        logger.bind(tag="TASK").info(f"忽略超时任务: {task.task_instance_id}")
            except ET.ParseError as e:
                logger.bind(tag="TASK").warning(f"time_out_finished_tasks XML解析失败: {e}")
            except Exception as e:
                logger.bind(tag="TASK").error(f"time_out_finished_tasks 任务解析异常: {e}")
