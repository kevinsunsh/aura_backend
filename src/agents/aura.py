import json
import uuid
import logging
import requests
from pydantic import BaseModel
from typing import Optional, Callable, Any

# 配置相关
from config import settings

# 记忆相关
from store.message_store import MessageStore

from agents.graphs.main_graph import builder

# LangGraph checkpoint 相关
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
# 配置LangChain日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("langchain")
logger.setLevel(logging.DEBUG)

class ChatRequest(BaseModel):
    """
    聊天请求模型
    """
    user_id: str

class AuraAgent:
    _instance = None
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.graph = None
        self.thread = None
        self.message_store = None
        self.knowledge_graph = None
        self.short_term_memory = None
        self.checkpointer = None

    @classmethod
    def get_instance(cls) -> 'AuraAgent':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def _initialize(self, user_id: str):
        try:
            # 延迟导入以避免循环导入
            
            self.message_store = MessageStore()
            self.thread = {
                "configurable": {
                    "user_id": user_id,
                    "thread_id": str(uuid.uuid4()),
                    "knowledge_graph": self.knowledge_graph,
                    "message_store": self.message_store
                }
            }
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL connection: {str(e)}")
            raise

    async def _cleanup(self):
        """清理资源"""
        if self.checkpointer:
            try:
                self.checkpointer.__exit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing checkpointer: {str(e)}")
            finally:
                self.checkpointer = None

    @staticmethod
    async def chat(chat_request: ChatRequest):
        """聊天方法，流式返回响应内容"""
        agent = AuraAgent.get_instance()
        await agent._initialize(chat_request.user_id)
        
        try:
            input_data = {
                "user_id": chat_request.user_id
            }

            conn_string = f"postgres://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}?sslmode=disable"
            async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
                agent.graph = builder.compile(checkpointer=checkpointer)
                async for event in agent.graph.astream(input_data, agent.thread, stream_mode=["updates", "messages"]):
                    try:
                        # 解析messages事件中的AIMessageChunk内容
                        if "messages" in event:
                            type, message_tuple = event
                            if isinstance(message_tuple, tuple) and len(message_tuple) >= 2:
                                # 第一个元素是消息类型，第二个元素是消息对象
                                message_obj, chat_stream_info = message_tuple
                                if hasattr(message_obj, 'content'):
                                    yield {
                                        "user_id": chat_request.user_id,
                                        "content": str(message_obj.content),
                                        "status": "streaming"
                                    }
                                elif isinstance(message_obj, dict) and 'content' in message_obj:
                                    yield {
                                        "user_id": chat_request.user_id,
                                        "content": str(message_obj['content']),
                                        "status": "streaming"
                                    }
                        
                        # 提取响应内容（保留原有逻辑作为备用）
                        if "main_entry" in event and "nova_response" in event["main_entry"]:
                            yield {
                                "user_id": chat_request.user_id,
                                "content": event["main_entry"]["nova_response"],
                                "status": "streaming"
                            }
                    except Exception as e:
                        logger.error(f"处理事件失败: {str(e)}")
                        yield {
                            "user_id": chat_request.user_id,
                            "content": f"处理失败: {str(e)}",
                            "status": "error"
                        }
                        continue
            
            # 发送完成信号
            yield {
                "user_id": chat_request.user_id,
                "content": "",
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"Error in chat processing: {str(e)}")
            yield {
                "user_id": chat_request.user_id,
                "content": f"处理失败: {str(e)}",
                "status": "error"
            }
        finally:
            await agent._cleanup()
