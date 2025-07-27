import uuid
import asyncio
from abc import ABC
from loguru import logger
from datetime import datetime
from .task_manager import TaskManager, TaskType
from agents.aura_memory.chat_stream import ChatStreamManager
from agents.aura_memory.message_store import MessageStore, Message
from utils.todo_mock_func import (
    _get_persona_text,
    _build_chat_history_str
)

class MessagePreAndPostProcessor(ABC):
    """MISC客户端包装器"""
    def __init__(self, input_queue, output_queue, is_process_running):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.is_process_running = is_process_running
        self.history_check_interval = 20000 #ms
        self.chat_id = None
        self.user_id = None
    
    @staticmethod
    def process_entry(input_queue, output_queue, is_process_running):
        asyncio.run(MessagePreAndPostProcessor.main(input_queue, output_queue, is_process_running))
    
    @staticmethod
    async def main(input_queue, output_queue, is_process_running):
        loop = asyncio.get_event_loop()
        client = MessagePreAndPostProcessor(
            input_queue=input_queue,
            output_queue=output_queue,
            is_process_running=is_process_running
        )
        while True:
            msg = await loop.run_in_executor(None, input_queue.get)
            if isinstance(msg, dict) and msg.get("type") == "start":
                client.chat_id = msg["data"]["chat_id"]
                client.user_id = msg["data"]["user_id"]
                client.is_process_running.value = True
                logger.bind(tag="BASE").info(f"预处理和后处理子进程启动")
            elif isinstance(msg, dict) and msg.get("type") == "stop":
                client.is_process_running.value = False
            elif isinstance(msg, dict) and msg.get("type") == "preprocess":
                if client.is_process_running.value:
                    logger.bind(tag="BASE").info(f"预处理用户输入: {msg['data']}")
                    await client.preprocess(msg["data"])
            elif isinstance(msg, dict) and msg.get("type") == "postprocess":
                if client.is_process_running.value:
                    await client.postprocess(msg["data"])
    
    async def preprocess(self, user_input: str) -> str:
        """预处理用户输入"""
        now_timestamp = int(datetime.now().timestamp() * 1000)
        history_messages = MessageStore.get_instance().get_messages_by_time_range(
            self.chat_id, 
            now_timestamp - self.history_check_interval, 
            now_timestamp
        )
        
        # 更新观察信息
        chat_history_str = _build_chat_history_str(history_messages)
        chat_history_str += f"{self.user_id}说: {user_input}\n"
        goals_str = ""
        knowledge_info_str = ""
        
        input_info = f"人设：{_get_persona_text()}。"
        if len(goals_str) > 0:
            input_info += f"当前对话目标：{goals_str}\n"
        if len(knowledge_info_str) > 0:
            input_info += f"供参考的相关知识和记忆：{knowledge_info_str}\n"
        input_info += f"最近的聊天记录：{chat_history_str}\n"
        
        self.output_queue.put({
            "type": "replying_input",
            "data": input_info
        })
        # 创建消息对象
        message = Message(
            msg_id=str(uuid.uuid4()),
            chat_id=self.chat_id,
            user_id=self.user_id,
            platform="default",
            m_type="text",
            content=user_input,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        )
        # 存储到消息存储
        MessageStore.get_instance().add_message(message)
    
    async def postprocess(self, bot_response: str) -> str:
        """后处理用户输入"""
                # 创建消息对象
        message = Message(
            msg_id=str(uuid.uuid4()),
            chat_id=self.chat_id,
            user_id="aura",
            platform="default",
            m_type="text",
            content=bot_response,
            data={},
            created_at=int(datetime.now().timestamp() * 1000)
        )
        # 存储到消息存储
        MessageStore.get_instance().add_message(message)
        ChatStreamManager.get_instance().update_chat_stream_checked_at(self.chat_id)
