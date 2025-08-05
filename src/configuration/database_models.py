from typing import Dict, Any
from sqlalchemy.dialects.postgresql import JSONB
from agents.agent_memory.database.database import Base
from sqlalchemy import Column, String, Integer, Boolean, Text, Float, DateTime, BigInteger, Index, JSON, PrimaryKeyConstraint

class ConfigurationModel(Base):
    """配置数据库模型"""
    __tablename__ = 'configurations'
    
    # 复合主键：(id, environment)
    id = Column(String, nullable=False)  # 配置ID，例如 "global", "chat_config", "memory_config"
    environment = Column(String, nullable=False, default="production")  # 环境：development, production, test
    
    # 配置基本信息
    name = Column(String, nullable=False)  # 配置名称
    description = Column(Text, nullable=True)  # 配置描述
    category = Column(String, nullable=False)  # 配置分类，例如 "chat", "memory", "model"
    
    # 配置内容
    config_data = Column(JSONB, nullable=False)  # 配置数据（JSON格式）
    config_schema = Column(JSONB, nullable=True)  # 配置模式（用于验证）
    
    # 版本控制
    version = Column(String, nullable=False, default="1.0.0")  # 配置版本
    is_active = Column(Boolean, nullable=False, default=True)  # 是否激活
    is_default = Column(Boolean, nullable=False, default=False)  # 是否为默认配置
    
    # 时间戳
    created_at = Column(BigInteger, nullable=False)  # 创建时间
    updated_at = Column(BigInteger, nullable=False)  # 更新时间
    last_used_at = Column(BigInteger, nullable=True)  # 最后使用时间
    
    # 复合主键约束
    __table_args__ = (
        PrimaryKeyConstraint('id', 'environment'),
        Index('idx_configurations_category', 'category'),
        Index('idx_configurations_environment', 'environment'),
        Index('idx_configurations_is_active', 'is_active'),
        Index('idx_configurations_created_at', 'created_at'),
        Index('idx_configurations_updated_at', 'updated_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'config_data': self.config_data,
            'config_schema': self.config_schema,
            'version': self.version,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'environment': self.environment,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_used_at': self.last_used_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigurationModel':
        """从字典创建实例"""
        return cls(
            id=data['id'],
            name=data['name'],
            description=data.get('description'),
            category=data['category'],
            config_data=data['config_data'],
            config_schema=data.get('config_schema'),
            version=data.get('version', '1.0.0'),
            is_active=data.get('is_active', True),
            is_default=data.get('is_default', False),
            environment=data.get('environment', 'production'),
            created_at=data['created_at'],
            updated_at=data['updated_at'],
            last_used_at=data.get('last_used_at'),
        )

class ConfigurationHistoryModel(Base):
    """配置历史记录模型"""
    __tablename__ = 'configuration_history'
    
    # 主键
    id = Column(String, primary_key=True)  # 历史记录ID
    config_id = Column(String, nullable=False)  # 关联的配置ID
    
    # 配置内容
    config_data = Column(JSONB, nullable=False)  # 历史配置数据
    config_schema = Column(JSONB, nullable=True)  # 历史配置模式
    
    # 版本信息
    version = Column(String, nullable=False)  # 版本号
    change_description = Column(Text, nullable=True)  # 变更描述
    
    # 操作信息
    operation = Column(String, nullable=False)  # 操作类型：create, update, delete
    operator = Column(String, nullable=True)  # 操作者
    
    # 时间戳
    created_at = Column(BigInteger, nullable=False)  # 创建时间
    
    # 索引
    __table_args__ = (
        Index('idx_configuration_history_config_id', 'config_id'),
        Index('idx_configuration_history_version', 'version'),
        Index('idx_configuration_history_created_at', 'created_at'),
    )

class ConfigurationTemplateModel(Base):
    """配置模板模型"""
    __tablename__ = 'configuration_templates'
    
    # 主键
    id = Column(String, primary_key=True)  # 模板ID
    
    # 模板信息
    name = Column(String, nullable=False)  # 模板名称
    description = Column(Text, nullable=True)  # 模板描述
    category = Column(String, nullable=False)  # 模板分类
    
    # 模板内容
    template_data = Column(JSONB, nullable=False)  # 模板数据
    template_schema = Column(JSONB, nullable=True)  # 模板模式
    
    # 模板属性
    is_public = Column(Boolean, nullable=False, default=True)  # 是否公开
    tags = Column(JSONB, nullable=True)  # 标签
    
    # 时间戳
    created_at = Column(BigInteger, nullable=False)  # 创建时间
    updated_at = Column(BigInteger, nullable=False)  # 更新时间
    
    # 索引
    __table_args__ = (
        Index('idx_configuration_templates_category', 'category'),
        Index('idx_configuration_templates_is_public', 'is_public'),
        Index('idx_configuration_templates_created_at', 'created_at'),
    ) 