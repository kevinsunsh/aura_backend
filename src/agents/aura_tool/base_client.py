import ssl
from abc import ABC, abstractmethod
import asyncio
from loguru import logger
import threading
import websockets
from typing import Dict, Any
from api_protocol.constant import *
import multiprocessing
from multiprocessing import Process

class BaseClient(ABC):
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self):
        self.logid = ""
        self.chat_id = None
        self.user_id = None
        self.session_id = None
        self.message_loop = None
        self.internal_input_queue = multiprocessing.Queue()
        self.internal_output_queue = multiprocessing.Queue()
        self.internal_is_process_running = multiprocessing.Value('b', False)
        self.worker = Process(target=self.consumer_worker, args=(self.internal_input_queue, self.internal_output_queue, self.internal_is_process_running))
        self.worker.start()
    
    @abstractmethod
    def consumer_worker(self, input_queue, output_queue, is_process_running):
        """常驻worker进程：负责音频处理"""
        pass
    
    async def message_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while True:
                # 尝试从客户端接收响应
                try:
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(None, self.internal_output_queue.get)
                    await self._handle_server_response(response)
                    # logger.bind(tag="BASE").info(f"收到服务器响应: {response}")
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"消息接收循环异常: {e}")
    
    @abstractmethod
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
        pass

    @abstractmethod
    async def start(self, chat_id: str, user_id: str) -> bool:
        try:
            self.session_id = chat_id
            self.user_id = user_id
            self.chat_id = chat_id
            self.message_loop = asyncio.create_task(self.message_receive_loop())
            logger.bind(tag="BASE").info(f"启动客户端成功")
            return True
        except Exception as e:
            return False
    
    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源"""
        try:
            if self.message_loop:
                self.message_loop.cancel()
                await self.message_loop
        except Exception as e:
            logger.error(f"清理资源失败: {e}")
