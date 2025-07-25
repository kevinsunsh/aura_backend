from loguru import logger
import time
import json
from typing import Dict, Any, Optional, List, Type, TypeVar
from dataclasses import dataclass, fields
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import threading
from datetime import datetime

from agents.aura_memory.database.database import Database
from agents.aura_memory.database.connection_config import DatabaseConfigManager
from .database_models import ConfigurationModel, ConfigurationHistoryModel, ConfigurationTemplateModel
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

@dataclass
class ConfigCache:
    """配置缓存"""
    data: Dict[str, Any]
    timestamp: float
    version: str
    environment: str

class DatabaseConfigManager:
    """数据库配置管理器"""
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化配置管理器
        
        Args:
            db_conn_string: 数据库连接字符串
        """
        self.db_conn_string = db_conn_string
        self.db = Database(db_conn_string)
        
        # 配置缓存
        self._cache: Dict[str, ConfigCache] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 300  # 缓存5分钟
        
        # 配置映射
        self._config_class_map = {
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
        
        # 初始化数据库表
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            self.db.create_all_tables()
            logger.info("配置数据库表初始化完成")
        except Exception as e:
            logger.error(f"配置数据库表初始化失败: {e}")
            raise
    
    def _get_cache_key(self, config_id: str, environment: str = "production") -> str:
        """获取缓存键"""
        return f"{config_id}:{environment}"
    
    def _is_cache_valid(self, cache: ConfigCache) -> bool:
        """检查缓存是否有效"""
        return time.time() - cache.timestamp < self._cache_ttl
    
    def _clear_expired_cache(self):
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = []
        
        for key, cache in self._cache.items():
            if current_time - cache.timestamp >= self._cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
    
    def get_config(self, config_id: str, config_class: Type[T] = None, 
                   environment: str = "production", use_cache: bool = True) -> Optional[T]:
        """
        获取配置
        
        Args:
            config_id: 配置ID
            config_class: 配置类
            environment: 环境
            use_cache: 是否使用缓存
            
        Returns:
            配置对象
        """
        cache_key = self._get_cache_key(config_id, environment)
        
        # 检查缓存
        if use_cache:
            with self._cache_lock:
                if cache_key in self._cache and self._is_cache_valid(self._cache[cache_key]):
                    cache = self._cache[cache_key]
                    logger.debug(f"从缓存获取配置: {config_id}")
                    return self._create_config_object(cache.data, config_class)
        
        # 从数据库获取
        try:
            with self.db.get_session() as session:
                config_model = session.query(ConfigurationModel).filter(
                    and_(
                        ConfigurationModel.id == config_id,
                        ConfigurationModel.environment == environment,
                        ConfigurationModel.is_active == True
                    )
                ).first()
                
                if not config_model:
                    logger.warning(f"配置不存在: {config_id} (环境: {environment})")
                    return None
                
                # 更新最后使用时间
                config_model.last_used_at = int(time.time() * 1000)
                session.commit()
                
                # 如果没有指定配置类，尝试从分类推断
                if not config_class and config_model.category:
                    config_class = self._config_class_map.get(config_model.category)
                
                # 缓存结果
                if use_cache:
                    with self._cache_lock:
                        self._cache[cache_key] = ConfigCache(
                            data=config_model.config_data,
                            timestamp=time.time(),
                            version=config_model.version,
                            environment=environment
                        )
                
                logger.debug(f"从数据库获取配置: {config_id}")
                return self._create_config_object(config_model.config_data, config_class)
                
        except Exception as e:
            logger.error(f"获取配置失败: {config_id}, 错误: {e}")
            return None
    
    def get_config_by_category(self, category: str, environment: str = "production") -> List[Dict[str, Any]]:
        """
        根据分类获取配置列表
        
        Args:
            category: 配置分类
            environment: 环境
            
        Returns:
            配置列表
        """
        try:
            with self.db.get_session() as session:
                configs = session.query(ConfigurationModel).filter(
                    and_(
                        ConfigurationModel.category == category,
                        ConfigurationModel.environment == environment,
                        ConfigurationModel.is_active == True
                    )
                ).all()
                
                return [config.to_dict() for config in configs]
                
        except Exception as e:
            logger.error(f"获取分类配置失败: {category}, 错误: {e}")
            return []
    
    def save_config(self, config_id: str, config_data: Dict[str, Any], 
                   name: str, category: str, description: str = None,
                   environment: str = "production", version: str = "1.0.0",
                   is_default: bool = False, operator: str = None) -> bool:
        """
        保存配置
        
        Args:
            config_id: 配置ID
            config_data: 配置数据
            name: 配置名称
            category: 配置分类
            description: 配置描述
            environment: 环境
            version: 版本
            is_default: 是否为默认配置
            operator: 操作者
            
        Returns:
            是否成功
        """
        try:
            current_time = int(time.time() * 1000)
            
            with self.db.get_session() as session:
                # 检查是否存在
                existing_config = session.query(ConfigurationModel).filter(
                    and_(
                        ConfigurationModel.id == config_id,
                        ConfigurationModel.environment == environment
                    )
                ).first()
                
                if existing_config:
                    # 保存历史记录
                    history = ConfigurationHistoryModel(
                        id=f"{config_id}_{current_time}",
                        config_id=config_id,
                        config_data=existing_config.config_data,
                        config_schema=existing_config.config_schema,
                        version=existing_config.version,
                        change_description=f"配置更新 by {operator or 'system'}",
                        operation="update",
                        operator=operator,
                        created_at=current_time
                    )
                    session.add(history)
                    
                    # 更新现有配置
                    existing_config.config_data = config_data
                    existing_config.name = name
                    existing_config.description = description
                    existing_config.category = category
                    existing_config.version = version
                    existing_config.is_default = is_default
                    existing_config.updated_at = current_time
                    
                else:
                    # 创建新配置
                    new_config = ConfigurationModel(
                        id=config_id,
                        name=name,
                        description=description,
                        category=category,
                        config_data=config_data,
                        version=version,
                        is_default=is_default,
                        environment=environment,
                        created_at=current_time,
                        updated_at=current_time
                    )
                    session.add(new_config)
                    
                    # 保存历史记录
                    history = ConfigurationHistoryModel(
                        id=f"{config_id}_{current_time}",
                        config_id=config_id,
                        config_data=config_data,
                        version=version,
                        change_description=f"配置创建 by {operator or 'system'}",
                        operation="create",
                        operator=operator,
                        created_at=current_time
                    )
                    session.add(history)
                
                session.commit()
                
                # 清除缓存
                cache_key = self._get_cache_key(config_id, environment)
                with self._cache_lock:
                    if cache_key in self._cache:
                        del self._cache[cache_key]
                
                logger.info(f"配置保存成功: {config_id}")
                return True
                
        except Exception as e:
            logger.error(f"保存配置失败: {config_id}, 错误: {e}")
            return False
    
    def delete_config(self, config_id: str, environment: str = "production", 
                     operator: str = None) -> bool:
        """
        删除配置
        
        Args:
            config_id: 配置ID
            environment: 环境
            operator: 操作者
            
        Returns:
            是否成功
        """
        try:
            current_time = int(time.time() * 1000)
            
            with self.db.get_session() as session:
                config = session.query(ConfigurationModel).filter(
                    and_(
                        ConfigurationModel.id == config_id,
                        ConfigurationModel.environment == environment
                    )
                ).first()
                
                if not config:
                    logger.warning(f"配置不存在: {config_id}")
                    return False
                
                # 保存历史记录
                history = ConfigurationHistoryModel(
                    id=f"{config_id}_{current_time}",
                    config_id=config_id,
                    config_data=config.config_data,
                    config_schema=config.config_schema,
                    version=config.version,
                    change_description=f"配置删除 by {operator or 'system'}",
                    operation="delete",
                    operator=operator,
                    created_at=current_time
                )
                session.add(history)
                
                # 软删除（标记为非激活）
                config.is_active = False
                config.updated_at = current_time
                
                session.commit()
                
                # 清除缓存
                cache_key = self._get_cache_key(config_id, environment)
                with self._cache_lock:
                    if cache_key in self._cache:
                        del self._cache[cache_key]
                
                logger.info(f"配置删除成功: {config_id}")
                return True
                
        except Exception as e:
            logger.error(f"删除配置失败: {config_id}, 错误: {e}")
            return False
    
    def _create_config_object(self, config_data: Dict[str, Any], config_class: Type[T] = None) -> Optional[T]:
        """
        创建配置对象
        
        Args:
            config_data: 配置数据
            config_class: 配置类
            
        Returns:
            配置对象
        """
        if not config_class:
            # 尝试从配置数据中推断配置类
            # 通过检查特定的字段来判断配置类型
            if 'enable_memory' in config_data:
                config_class = MemoryConfig
            elif 'chat_mode' in config_data:
                config_class = ChatConfig
            elif 'qq_account' in config_data:
                config_class = BotConfig
            elif 'personality_core' in config_data:
                config_class = PersonalityConfig
            elif 'identity_detail' in config_data:
                config_class = IdentityConfig
            elif 'enable_relationship' in config_data:
                config_class = RelationshipConfig
            elif 'ban_words' in config_data:
                config_class = MessageReceiveConfig
            elif 'willing_mode' in config_data:
                config_class = NormalChatConfig
            elif 'think_interval' in config_data:
                config_class = FocusChatConfig
            elif 'emoji_chance' in config_data:
                config_class = EmojiConfig
            elif 'enable_expression' in config_data:
                config_class = ExpressionConfig
            elif 'enable_mood' in config_data:
                config_class = MoodConfig
            elif 'keyword_rules' in config_data:
                config_class = KeywordReactionConfig
            elif 'enable' in config_data and 'error_rate' in config_data:
                config_class = ChineseTypoConfig
            elif 'enable_response_post_process' in config_data:
                config_class = ResponsePostProcessConfig
            elif 'enable' in config_data and 'max_length' in config_data:
                config_class = ResponseSplitterConfig
            elif 'enable' in config_data and len(config_data) == 1:
                config_class = TelemetryConfig
            elif 'enable_friend_chat' in config_data:
                config_class = ExperimentalConfig
            elif 'model_max_output_length' in config_data:
                config_class = ModelConfig
            elif 'use_custom' in config_data:
                config_class = MaimMessageConfig
            elif 'enable' in config_data and 'rag_synonym_search_top_k' in config_data:
                config_class = LPMMKnowledgeConfig
            elif 'enable_in_normal_chat' in config_data:
                config_class = ToolConfig
            elif 'debug_show_chat_mode' in config_data:
                config_class = DebugConfig
            else:
                logger.warning("无法推断配置类，返回原始数据")
                return config_data
        
        try:
            if issubclass(config_class, ConfigBase):
                return config_class.from_dict(config_data)
            else:
                return config_class(**config_data)
        except Exception as e:
            logger.error(f"创建配置对象失败: {e}")
            return None
    
    def get_default_configs(self, environment: str = "production") -> Dict[str, Any]:
        """
        获取默认配置
        
        Args:
            environment: 环境
            
        Returns:
            默认配置字典
        """
        try:
            with self.db.get_session() as session:
                default_configs = session.query(ConfigurationModel).filter(
                    and_(
                        ConfigurationModel.is_default == True,
                        ConfigurationModel.environment == environment,
                        ConfigurationModel.is_active == True
                    )
                ).all()
                
                result = {}
                for config in default_configs:
                    config_class = self._config_class_map.get(config.category)
                    if config_class:
                        config_obj = self._create_config_object(config.config_data, config_class)
                        if config_obj:
                            result[config.category] = config_obj
                
                return result
                
        except Exception as e:
            logger.error(f"获取默认配置失败: {e}")
            return {}
    
    def clear_cache(self):
        """清除所有缓存"""
        with self._cache_lock:
            self._cache.clear()
        logger.info("配置缓存已清除")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        with self._cache_lock:
            return {
                'cache_size': len(self._cache),
                'cache_keys': list(self._cache.keys()),
                'cache_ttl': self._cache_ttl
            } 