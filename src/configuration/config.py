import os
import asyncio
import aiohttp
import json
from enum import Enum
from dataclasses import dataclass, fields
from typing import Any, Optional, Dict, Literal, AsyncGenerator, List
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel
from agents.agent_memory.database.connection_config import DatabaseConfigManager
from .config_loader import load_config, load_specific_config, get_config_loader, Config

@dataclass(kw_only=True)
class GraphConfiguration:
	"""The configurable fields for the chatbot."""
	thread_id: str = "default" # Thread ID

	@classmethod
	def from_runnable_config(
		cls, config: Optional[RunnableConfig] = None
	) -> "GraphConfiguration":
		"""Create a Configuration instance from a RunnableConfig."""
		configurable = (
			config["configurable"] if config and "configurable" in config else {}
		)
		values: dict[str, Any] = {
			f.name: os.environ.get(f.name.upper(), configurable.get(f.name))
			for f in fields(cls)
			if f.init
		}
		return cls(**{k: v for k, v in values.items() if v})

LLMType = Literal["utils", 
                  "utils_small", 
                  "replyer_1", 
                  "replyer_2", 
                  "memory_summary", 
                  "vlm", 
                  "focus_working_memory", 
                  "tool_use", 
                  "planner", 
                  "relation", 
                  "embedding", 
                  "pfc_action_planner", 
                  "pfc_chat", 
                  "pfc_reply_checker"]

class ChatModel():
    def __init__(self, model_name: str, model_provider: str, api_key: str, api_base: str):
        self.model_name = model_name
        self.model_provider = model_provider
        self.api_key = api_key
        self.api_base = api_base
    
    async def astream(self, messages: List[Any], extra_body: Dict[str, Any] = None) -> AsyncGenerator[Any, None]:
        """
        基于ARK API的异步流式聊天方法，替代原有的chat_model.astream
        
        Args:
            messages: 消息列表
            extra_body: 额外参数（可选）
            
        Yields:
            包含内容的聊天块对象
        """
        # 构建请求数据
        payload = {
            "messages": [],
            "model": self.model_name,
            "stream": True
        }
        
        # 转换消息格式
        for message in messages:
            if message.get('role', None) and message.get('content', None):
                payload["messages"].append({
                    "role": message.get('role'),
                    "content": message.get('content')
                })
            elif isinstance(message, dict):
                payload["messages"].append(message)
        
        # 添加额外参数
        if extra_body:
            payload.update(extra_body)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"ARK API请求失败: {response.status} - {error_text}")
                    
                    # 处理流式响应
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if not line:
                            continue
                        
                        # 移除 "data: " 前缀
                        if line.startswith("data: "):
                            line = line[6:]
                        
                        # 检查是否是结束标记
                        if line == "[DONE]":
                            break
                        
                        try:
                            # 解析JSON数据
                            data = json.loads(line)
                            if "choices" in data and len(data["choices"]) > 0:
                                choice = data["choices"][0]
                                if "delta" in choice and "content" in choice["delta"]:
                                    content = choice["delta"]["content"]
                                    if content:
                                        # 创建一个简单的对象来模拟原有的chunk结构
                                        chunk = type('MockChunk', (), {'content': content})()
                                        yield chunk
                        except json.JSONDecodeError:
                            # 忽略无效的JSON行
                            continue
                            
        except Exception as e:
            print(f"ARK API流式请求出错: {str(e)}")
            # 返回一个错误消息块
            error_chunk = type('MockChunk', (), {'content': f"错误: {str(e)}"})()
            yield error_chunk

# 模型缓存
_model_cache: Dict[str, ChatModel] = {}

def get_chat_model_by_type(
    llm_type: LLMType,
    environment: str = "test",
    use_cache: bool = True
) -> ChatModel:
    """
    Get LLM instance by type. Returns cached instance if available.
    
    Args:
        llm_type: 模型类型
        environment: 环境
        use_cache: 是否使用缓存
        
    Returns:
        ChatModel实例
    """
    
    # 检查缓存
    if use_cache:
        if llm_type in _model_cache:
            return _model_cache[llm_type]

    # 从数据库加载ModelConfig
    try:
        # model_config = load_specific_config_from_database("model", environment)
        # model_config = global_config.model
        if global_config.model is None:
            raise ValueError(f"ModelConfig not found in database for environment: {environment}")
        
        # 从ModelConfig获取配置
        configurable = getattr(global_config.model, llm_type, {})
        
        # 如果没有特定配置，使用默认配置
        if not configurable:
            configurable = {
                "model_name": "doubao-seed-1-6-flash-250615",
                "model_provider": "openai",
                "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                "api_base": "https://ark.cn-beijing.volces.com/api/v3"
            }
        
        # 创建ChatModel实例
        model_instance = ChatModel(
            model_name=configurable["model_name"],
            api_key=configurable["api_key"],
            api_base=configurable["api_base"],
            model_provider=configurable["model_provider"]
        )
        
        # 缓存模型实例
        if use_cache:
            _model_cache[llm_type] = model_instance
        
        return model_instance
        
    except Exception as e:
        print(f"Warning: Failed to load ModelConfig from database, using fallback: {e}")
        # 回退到硬编码配置
        return ChatModel(
            model_name="doubao-seed-1-6-flash-250615",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
            model_provider="openai"
        )

def load_config_from_database(environment: str = "production") -> Any:
    """
    从数据库加载配置
    
    Args:
        environment: 环境
        
    Returns:
        配置对象
    """
    db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
    return load_config(environment=environment, db_conn_string=db_conn_string)

def load_specific_config_from_database(config_name: str, environment: str = "production") -> Any:
    """
    从数据库加载特定配置
    
    Args:
        config_name: 配置名称
        environment: 环境
        
    Returns:
        配置对象
    """
    db_conn_string = get_db_conn_string()
    return load_specific_config(config_name, environment, db_conn_string)

def initialize_database_configs(environment: str = "production") -> bool:
    """
    初始化数据库配置
    
    Args:
        environment: 环境
        
    Returns:
        是否成功
    """
    db_conn_string = get_db_conn_string()
    config_loader = get_config_loader(db_conn_string)
    return config_loader.initialize_default_configs(environment)

def migrate_file_config_to_database(config_file_path: str, environment: str = "production") -> bool:
    """
    将文件配置迁移到数据库
    
    Args:
        config_file_path: 配置文件路径
        environment: 环境
        
    Returns:
        是否成功
    """
    db_conn_string = get_db_conn_string()
    config_loader = get_config_loader(db_conn_string)
    return config_loader.migrate_from_file_config(config_file_path, environment)

# 兼容性函数 - 保持向后兼容
def load_config_legacy(config_path: str) -> Any:
    """
    兼容性函数：从文件加载配置（已废弃，建议使用数据库配置）
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置对象
    """
    import warnings
    warnings.warn(
        "load_config_legacy is deprecated. Use load_config_from_database instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    # 尝试迁移到数据库
    if migrate_file_config_to_database(config_path):
        return load_config_from_database()
    else:
        # 如果迁移失败，返回数据库默认配置
        return load_config_from_database()

def get_config_dir() -> str:
    """
    获取配置目录（已废弃，现在使用数据库）
    
    Returns:
        配置目录路径
    """
    import warnings
    warnings.warn(
        "get_config_dir is deprecated. Configurations are now stored in database.",
        DeprecationWarning,
        stacklevel=2
    )
    return "database"

# 全局配置实例
try:
    global_config: Config = load_config_from_database()
except Exception as e:
    print(f"警告：无法从数据库加载配置，使用默认配置: {e}")
    # 如果数据库配置加载失败，创建一个空的配置对象
    from .config_loader import Config
    global_config: Config = Config()
