from typing import Dict, Any
from sqlalchemy.dialects.postgresql import JSONB
from agents.agent_memory.database.database import Base
from sqlalchemy import Column, String, Integer, Boolean, Text, Float, DateTime, BigInteger, Index, JSON, PrimaryKeyConstraint, ForeignKey
from sqlalchemy.orm import relationship

class WorldInfoEntry(Base):
    """世界书条目"""
    __tablename__ = 'world_info_entries'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    world_info_book_id = Column(String, ForeignKey('world_info_books.id'), nullable=False)  # 关联世界书ID
    uid = Column(String, nullable=False)  # 关联角色书ID
    keys = Column(JSONB, nullable=False, default=[])  # 关键词列表
    keysecondary = Column(JSONB, nullable=False, default=[])  # 次级关键词列表
    comment = Column(String, default="")  # 注释
    content = Column(Text, nullable=False)  # 条目内容
    constant = Column(Boolean, default=False)  # 是否常驻
    selective = Column(Boolean, default=True)  # 是否选择性触发
    order = Column(Integer, default=100)  # 插入顺序
    position = Column(String, default="before_char")  # 位置
    disable = Column(Boolean, default=False)  # 是否启用
    display_index = Column(Integer, default=0)  # 显示索引
    addMemo = Column(Boolean, default=True)  # 是否添加注释
    group = Column(String, default="")  # 组
    groupOverride = Column(Boolean, default=False)  # 组覆盖
    groupWeight = Column(Integer, default=100)  # 组权重
    sticky = Column(Integer, default=0)  # 粘性
    cooldown = Column(Integer, default=0)  # 冷却时间
    delay = Column(Integer, default=0)  # 延迟
    probability = Column(Integer, default=100)  # 概率
    depth = Column(Integer, default=4)  # 深度
    useProbability = Column(Boolean, default=True)  # 使用概率
    role = Column(Integer, default=0)  # 角色
    vectorized = Column(Boolean, default=False)  # 向量化
    excludeRecursion = Column(Boolean, default=False)  # 排除递归
    preventRecursion = Column(Boolean, default=False)  # 防止递归
    delayUntilRecursion = Column(Boolean, default=False)  # 延迟直到递归
    scanDepth = Column(Integer, nullable=True)  # 扫描深度
    caseSensitive = Column(Boolean, nullable=True)  # 大小写敏感
    matchWholeWords = Column(Boolean, nullable=True)  # 匹配整个单词
    useGroupScoring = Column(Boolean, nullable=True)  # 使用组评分
    automationId = Column(String, default="")  # 自动化ID
    selectiveLogic = Column(Integer, default=0)  # 选择性逻辑
    matchPersonaDescription = Column(Boolean, default=False)  # 匹配角色描述
    matchCharacterDescription = Column(Boolean, default=False)  # 匹配角色描述
    matchCharacterPersonality = Column(Boolean, default=False)  # 匹配角色性格
    matchCharacterDepthPrompt = Column(Boolean, default=False)  # 匹配角色深度提示词
    matchScenario = Column(Boolean, default=False)  # 匹配场景
    matchCreatorNotes = Column(Boolean, default=False)  # 匹配创建者注释
    triggers = Column(JSONB, default=[])  # 触发器
    characterFilter = Column(JSONB, default={})  # 角色过滤
    # 关联关系
    world_info_book = relationship("WorldInfoBook", back_populates="entries")  # 条目
    # 索引
    __table_args__ = (
        Index('idx_world_info_entries_world_info_book_id', 'world_info_book_id'),
        Index('idx_world_info_entries_disable', 'disable'),
        Index('idx_world_info_entries_position', 'position'),
    )

class WorldInfoBook(Base):
    """世界书"""
    __tablename__ = 'world_info_books'
    id = Column(String, primary_key=True)  # 主键
    name = Column(String, unique=True, nullable=False)  # 名称，唯一
    # 关联关系
    entries = relationship("WorldInfoEntry", back_populates="world_info_book")  # 条目
    # 索引
    __table_args__ = (
        Index('idx_world_info_books_name', 'name'),
    )
