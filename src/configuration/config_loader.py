from loguru import logger
from typing import Dict, Any, Optional, Type, TypeVar
from dataclasses import dataclass, field
from .config_manager import ConfigManager
from .config_base import ConfigBase
from .official_configs import (
    MemoryConfig, ChatConfig, BotConfig, PersonalityConfig, IdentityConfig,
    RelationshipConfig, MessageReceiveConfig, NormalChatConfig, FocusChatConfig,
    EmojiConfig, ExpressionConfig, MoodConfig, KeywordReactionConfig,
    ChineseTypoConfig, ResponsePostProcessConfig, ResponseSplitterConfig,
    TelemetryConfig, ExperimentalConfig, ModelConfig, MaimMessageConfig,
    LPMMKnowledgeConfig, ToolConfig, DebugConfig
)

T = TypeVar('T', bound=ConfigBase)

# 硬编码的版本信息
MMC_VERSION = "0.8.2-snapshot.1"

@dataclass
class Config(ConfigBase):
    """总配置类"""
    
    MMC_VERSION: str = field(default=MMC_VERSION, repr=False, init=False)  # 硬编码的版本信息
    
    # 配置字段
    memory: MemoryConfig = None
    chat: ChatConfig = None
    bot: BotConfig = None
    personality: PersonalityConfig = None
    identity: IdentityConfig = None
    relationship: RelationshipConfig = None
    message_receive: MessageReceiveConfig = None
    normal_chat: NormalChatConfig = None
    focus_chat: FocusChatConfig = None
    emoji: EmojiConfig = None
    expression: ExpressionConfig = None
    mood: MoodConfig = None
    keyword_reaction: KeywordReactionConfig = None
    chinese_typo: ChineseTypoConfig = None
    response_post_process: ResponsePostProcessConfig = None
    response_splitter: ResponseSplitterConfig = None
    telemetry: TelemetryConfig = None
    experimental: ExperimentalConfig = None
    model: ModelConfig = None
    maim_message: MaimMessageConfig = None
    lpmm_knowledge: LPMMKnowledgeConfig = None
    tool: ToolConfig = None
    debug: DebugConfig = None

class ConfigLoader:
    """数据库配置加载器"""
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化配置加载器
        
        Args:
            db_conn_string: 数据库连接字符串
        """
        self.db_conn_string = db_conn_string
        self.config_manager = ConfigManager(db_conn_string)
        
        # 配置映射
        self._config_mapping = {
            'memory': MemoryConfig,
            'chat': ChatConfig,
            'bot': BotConfig,
            'personality': PersonalityConfig,
            'identity': IdentityConfig,
            'relationship': RelationshipConfig,
            'message_receive': MessageReceiveConfig,
            'normal_chat': NormalChatConfig,
            'focus_chat': FocusChatConfig,
            'emoji': EmojiConfig,
            'expression': ExpressionConfig,
            'mood': MoodConfig,
            'keyword_reaction': KeywordReactionConfig,
            'chinese_typo': ChineseTypoConfig,
            'response_post_process': ResponsePostProcessConfig,
            'response_splitter': ResponseSplitterConfig,
            'telemetry': TelemetryConfig,
            'experimental': ExperimentalConfig,
            'model': ModelConfig,
            'maim_message': MaimMessageConfig,
            'lpmm_knowledge': LPMMKnowledgeConfig,
            'tool': ToolConfig,
            'debug': DebugConfig,
        }
    
    def load_config(self, environment: str = "production") -> Config:
        """
        加载完整配置
        
        Args:
            environment: 环境
            
        Returns:
            Config对象
        """
        logger.info(f"开始从数据库加载配置 (环境: {environment})")
        
        config_data = {}
        
        # 加载各个配置模块
        for config_name, config_class in self._config_mapping.items():
            config_id = f"{config_name}_config"
            config_obj = self.config_manager.get_config(
                config_id=config_id,
                config_class=config_class,
                environment=environment
            )
            
            if config_obj:
                config_data[config_name] = config_obj
                logger.debug(f"加载配置成功: {config_name}")
            else:
                logger.warning(f"配置不存在，使用默认值: {config_name}")
                # 使用默认配置
                config_data[config_name] = self._get_default_config(config_class)
        
        # 创建总配置对象
        try:
            config = Config(**config_data)
            logger.info("配置加载完成")
            return config
        except Exception as e:
            logger.error(f"创建配置对象失败: {e}")
            raise
    
    def load_specific_config(self, config_name: str, environment: str = "production") -> Optional[Any]:
        """
        加载特定配置
        
        Args:
            config_name: 配置名称
            environment: 环境
            
        Returns:
            配置对象
        """
        config_class = self._config_mapping.get(config_name)
        if not config_class:
            logger.error(f"未知的配置类型: {config_name}")
            return None
        
        config_id = f"{config_name}_config"
        config_obj = self.config_manager.get_config(
            config_id=config_id,
            config_class=config_class,
            environment=environment
        )
        
        if config_obj:
            logger.debug(f"加载特定配置成功: {config_name}")
            return config_obj
        else:
            logger.warning(f"特定配置不存在，使用默认值: {config_name}")
            return self._get_default_config(config_class)
    
    def _convert_sets_to_lists(self, data):
        """
        递归转换字典中的set类型为list类型，以便JSON序列化
        
        Args:
            data: 要转换的数据
            
        Returns:
            转换后的数据
        """
        if isinstance(data, dict):
            return {key: self._convert_sets_to_lists(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._convert_sets_to_lists(item) for item in data]
        elif isinstance(data, set):
            return list(data)
        else:
            return data

    def _get_default_config(self, config_class: Type[T]) -> T:
        """
        获取默认配置
        
        Args:
            config_class: 配置类
            
        Returns:
            默认配置对象
        """
        try:
            # 为特定配置类提供默认值
            if config_class.__name__ == "PersonalityConfig":
                return config_class(
                    personality_core="我是一个友好的AI助手，喜欢与人交流，会尽力帮助用户解决问题。"
                )
            elif config_class.__name__ == "IdentityConfig":
                return config_class(
                    identity_detail=["AI助手", "智能对话机器人", "知识问答助手"]
                )
            elif config_class.__name__ == "KeywordReactionConfig":
                return config_class(
                    keyword_rules=[],
                    regex_rules=[]
                )
            elif config_class.__name__ == "MessageReceiveConfig":
                return config_class(
                    ban_words=set(),
                    ban_msgs_regex=set()
                )
            elif config_class.__name__ == "ExpressionConfig":
                return config_class(
                    enable_expression=True,
                    expression_style="",
                    learning_interval=300,
                    enable_expression_learning=True,
                    expression_groups=[]
                )
            elif config_class.__name__ == "EmojiConfig":
                return config_class(
                    emoji_chance=0.6,
                    emoji_activate_type="random",
                    max_reg_num=200,
                    do_replace=True,
                    check_interval=120,
                    steal_emoji=True,
                    content_filtration=False,
                    filtration_prompt="符合公序良俗"
                )
            elif config_class.__name__ == "MemoryConfig":
                return config_class(
                    enable_memory=True,
                    memory_build_interval=600,
                    memory_build_distribution=(6.0, 3.0, 0.6, 32.0, 12.0, 0.4),
                    memory_build_sample_num=8,
                    memory_build_sample_length=40,
                    memory_compress_rate=0.1,
                    forget_memory_interval=1000,
                    memory_forget_time=24,
                    memory_forget_percentage=0.01,
                    consolidate_memory_interval=1000,
                    consolidation_similarity_threshold=0.7,
                    consolidate_memory_percentage=0.01,
                    memory_ban_words=["表情包", "图片", "回复", "聊天记录"]
                )
            elif config_class.__name__ == "MoodConfig":
                return config_class(
                    enable_mood=False,
                    mood_update_interval=1,
                    mood_decay_rate=0.95,
                    mood_intensity_factor=0.7
                )
            elif config_class.__name__ == "ResponsePostProcessConfig":
                return config_class(
                    enable_response_post_process=True
                )
            elif config_class.__name__ == "ChineseTypoConfig":
                return config_class(
                    enable=True,
                    error_rate=0.01,
                    min_freq=9,
                    tone_error_rate=0.1,
                    word_replace_rate=0.006
                )
            elif config_class.__name__ == "ResponseSplitterConfig":
                return config_class(
                    enable=True,
                    max_length=256,
                    max_sentence_num=3,
                    enable_kaomoji_protection=False
                )
            elif config_class.__name__ == "TelemetryConfig":
                return config_class(
                    enable=True
                )
            elif config_class.__name__ == "DebugConfig":
                return config_class(
                    debug_show_chat_mode=False,
                    show_prompt=False
                )
            elif config_class.__name__ == "ExperimentalConfig":
                return config_class(
                    enable_friend_chat=False,
                    pfc_chatting=False
                )
            elif config_class.__name__ == "MaimMessageConfig":
                return config_class(
                    use_custom=False,
                    host="127.0.0.1",
                    port=8090,
                    mode="ws",
                    use_wss=False,
                    cert_file="",
                    key_file="",
                    auth_token=[]
                )
            elif config_class.__name__ == "LPMMKnowledgeConfig":
                return config_class(
                    enable=True,
                    rag_synonym_search_top_k=10,
                    rag_synonym_threshold=0.8,
                    info_extraction_workers=3,
                    qa_relation_search_top_k=10,
                    qa_relation_threshold=0.75,
                    qa_paragraph_search_top_k=1000,
                    qa_paragraph_node_weight=0.05,
                    qa_ent_filter_top_k=10,
                    qa_ppr_damping=0.8,
                    qa_res_top_k=10
                )
            elif config_class.__name__ == "ModelConfig":
                return config_class(
                    model_max_output_length=800,
                    utils={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    utils_small={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    replyer_1={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    replyer_2={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    memory_summary={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    vlm={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    focus_working_memory={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    tool_use={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    planner={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    relation={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    embedding={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    pfc_action_planner={
                        "model": "deepseek-r1",
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    pfc_chat={
                        "model": "deepseek-v3-250324",
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    },
                    pfc_reply_checker={
                        "api_key": "dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3"
                    }
                )
            else:
                # 对于其他配置类，尝试使用默认构造函数
                return config_class()
                
        except Exception as e:
            logger.error(f"创建默认配置失败: {config_class.__name__}, 错误: {e}")
            raise
    
    def save_config(self, config_name: str, config_data: Dict[str, Any], 
                   environment: str = "production", description: str = None,
                   is_default: bool = False) -> bool:
        """
        保存配置
        
        Args:
            config_name: 配置名称
            config_data: 配置数据
            environment: 环境
            description: 配置描述
            is_default: 是否为默认配置
            
        Returns:
            是否成功
        """
        config_id = f"{config_name}_config"
        name = f"{config_name} Configuration"
        
        return self.config_manager.save_config(
            config_id=config_id,
            config_data=config_data,
            name=name,
            category=config_name,
            description=description,
            environment=environment,
            is_default=is_default
        )
    
    def delete_config(self, config_name: str, environment: str = "production") -> bool:
        """
        删除配置
        
        Args:
            config_name: 配置名称
            environment: 环境
            
        Returns:
            是否成功
        """
        config_id = f"{config_name}_config"
        return self.config_manager.delete_config(config_id, environment)
    
    def get_config_list(self, category: str = None, environment: str = "production") -> list:
        """
        获取配置列表
        
        Args:
            category: 配置分类
            environment: 环境
            
        Returns:
            配置列表
        """
        if category:
            return self.config_manager.get_config_by_category(category, environment)
        else:
            # 获取所有分类的配置
            all_configs = []
            for config_name in self._config_mapping.keys():
                configs = self.config_manager.get_config_by_category(config_name, environment)
                all_configs.extend(configs)
            return all_configs
    
    def initialize_default_configs(self, environment: str = "production") -> bool:
        """
        初始化默认配置
        
        Args:
            environment: 环境
            
        Returns:
            是否成功
        """
        logger.info(f"开始初始化默认配置 (环境: {environment})")
        
        try:
            for config_name, config_class in self._config_mapping.items():
                # 检查是否已存在默认配置
                config_id = f"{config_name}_config"
                existing_config = self.config_manager.get_config(
                    config_id=config_id,
                    environment=environment
                )
                
                if not existing_config:
                    # 创建默认配置
                    default_config = self._get_default_config(config_class)
                    
                    # 转换为字典
                    if hasattr(default_config, '__dict__'):
                        config_data = default_config.__dict__
                    else:
                        config_data = {}
                    
                    # 处理set类型，转换为list以便JSON序列化
                    config_data = self._convert_sets_to_lists(config_data)
                    
                    # 保存默认配置
                    success = self.save_config(
                        config_name=config_name,
                        config_data=config_data,
                        environment=environment,
                        description=f"默认 {config_name} 配置",
                        is_default=True
                    )
                    
                    if success:
                        logger.info(f"创建默认配置成功: {config_name}")
                    else:
                        logger.error(f"创建默认配置失败: {config_name}")
                        return False
            
            logger.info("默认配置初始化完成")
            return True
            
        except Exception as e:
            logger.error(f"初始化默认配置失败: {e}")
            return False
    
    def migrate_from_file_config(self, config_file_path: str, environment: str = "production") -> bool:
        """
        从文件配置迁移到数据库配置
        
        Args:
            config_file_path: 配置文件路径
            environment: 环境
            
        Returns:
            是否成功
        """
        logger.info(f"开始从文件配置迁移到数据库 (文件: {config_file_path}, 环境: {environment})")
        
        try:
            # 读取文件配置
            import tomlkit
            with open(config_file_path, "r", encoding="utf-8") as f:
                file_config_data = tomlkit.load(f)
            
            # 迁移各个配置模块
            for config_name in self._config_mapping.keys():
                if config_name in file_config_data:
                    config_data = file_config_data[config_name]
                    
                    success = self.save_config(
                        config_name=config_name,
                        config_data=config_data,
                        environment=environment,
                        description=f"从文件迁移的 {config_name} 配置",
                        is_default=True
                    )
                    
                    if success:
                        logger.info(f"迁移配置成功: {config_name}")
                    else:
                        logger.error(f"迁移配置失败: {config_name}")
                        return False
            
            logger.info("文件配置迁移完成")
            return True
            
        except Exception as e:
            logger.error(f"文件配置迁移失败: {e}")
            return False

# 全局配置加载器实例
_global_config_loader = None

def get_config_loader(db_conn_string: str = None) -> ConfigLoader:
    """
    获取全局配置加载器实例
    
    Args:
        db_conn_string: 数据库连接字符串
        
    Returns:
        配置加载器实例
    """
    global _global_config_loader
    
    if _global_config_loader is None:
        _global_config_loader = ConfigLoader(db_conn_string)
    
    return _global_config_loader

def load_config(environment: str = "production", db_conn_string: str = None) -> Config:
    """
    加载配置的便捷函数
    
    Args:
        environment: 环境
        db_conn_string: 数据库连接字符串
        
    Returns:
        Config对象
    """
    config_loader = get_config_loader(db_conn_string)
    return config_loader.load_config(environment)

def load_specific_config(config_name: str, environment: str = "production", 
                        db_conn_string: str = None) -> Optional[Any]:
    """
    加载特定配置的便捷函数
    
    Args:
        config_name: 配置名称
        environment: 环境
        db_conn_string: 数据库连接字符串
        
    Returns:
        配置对象
    """
    config_loader = get_config_loader(db_conn_string)
    return config_loader.load_specific_config(config_name, environment) 