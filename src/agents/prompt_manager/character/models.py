from typing import Dict, Any
from sqlalchemy.dialects.postgresql import JSONB
from agents.agent_memory.database.database import Base
from sqlalchemy import Column, String, Integer, Boolean, Text, Float, DateTime, BigInteger, Index, JSON, PrimaryKeyConstraint, ForeignKey
from sqlalchemy.orm import relationship

class CharacterModel(Base):
    """角色主表"""
    __tablename__ = 'characters'
    
    # 主键
    id = Column(String, primary_key=True)  # 角色ID
    
    # 基本信息
    name = Column(String, nullable=False)  # 角色名称
    description = Column(Text, nullable=True)  # 角色描述
    description_tokens = Column(Integer, nullable=True)  # 角色描述的令牌数
    personality = Column(Text, nullable=True)  # 性格
    personality_tokens = Column(Integer, nullable=True)  # 性格的令牌数
    first_mes = Column(Text, nullable=True)  # 第一条消息
    first_mes_tokens = Column(Integer, nullable=True)  # 第一条消息的令牌数
    avatar = Column(String, nullable=True, default="none")  # 头像
    mes_example = Column(Text, nullable=True)  # 消息示例
    mes_example_tokens = Column(Integer, nullable=True)  # 消息示例的令牌数
    scenario = Column(Text, nullable=True)  # 场景
    scenario_tokens = Column(Integer, nullable=True)  # 场景的令牌数
    create_date = Column(String, nullable=True)  # 创建日期
    talkativeness = Column(String, nullable=True, default="0.5")  # 话痨程度
    fav = Column(Boolean, nullable=False, default=False)  # 是否收藏
    creator_notes = Column(Text, nullable=True)  # 创建者评论
    system_prompt = Column(Text, nullable=True)  # 系统提示词
    system_prompt_tokens = Column(Integer, nullable=True)  # 系统提示词的令牌数
    post_history_instructions = Column(Text, nullable=True)  # 历史后指令
    tags = Column(JSONB, nullable=True)  # 标签
    creator = Column(String, nullable=True)  # 创建者
    alternate_greetings = Column(JSONB, nullable=True)  # 替代问候语
    group_only_greetings = Column(JSONB, nullable=True)  # 群组专用问候语
    character_version = Column(String, nullable=True)  # 角色版本
    world = Column(String, nullable=True)  # 世界
    depth_prompt = Column(JSONB, nullable=True)  # 深度提示词
    spec = Column(String, nullable=True, default="chara_card_v3")  # 规格
    spec_version = Column(String, nullable=True, default="3.0")  # 规格版本
    # 关联关系
    character_book = relationship("CharacterBookModel", back_populates="character", uselist=False)
    
    # 索引
    __table_args__ = (
        Index('idx_characters_name', 'name'),
        Index('idx_characters_fav', 'fav'),
    )

class CharacterBookModel(Base):
    """角色书表"""
    __tablename__ = 'character_books'
    
    # 主键
    id = Column(String, primary_key=True)  # 角色书ID
    
    # 外键
    character_id = Column(String, ForeignKey('characters.id'), nullable=False)  # 关联角色ID
    
    # 角色书信息
    name = Column(String, nullable=True, default="")  # 角色书名称
    
    # 关联关系
    character = relationship("CharacterModel", back_populates="character_book", uselist=False)
    entries = relationship("CharacterBookEntryModel", back_populates="character_book")
    
    # 索引
    __table_args__ = (
        Index('idx_character_books_name', 'name'),
    )

class CharacterBookEntryModel(Base):
    """角色书条目表"""
    __tablename__ = 'character_book_entries'
    
    # 角色书条目表字段设计，参考给定JSON结构，extensions字段展开为独立字段
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    character_book_id = Column(String, ForeignKey('character_books.id'), nullable=False)  # 关联角色书ID
    keys = Column(JSONB, nullable=False, default=[])  # 关键词列表
    secondary_keys = Column(JSONB, nullable=False, default=[])  # 次级关键词列表
    comment = Column(String, default="")  # 注释
    content = Column(Text, nullable=False)  # 条目内容
    content_tokens = Column(Integer, nullable=True)  # 条目内容的令牌数
    constant = Column(Boolean, default=False)  # 是否常驻
    selective = Column(Boolean, default=True)  # 是否选择性触发
    insertion_order = Column(Integer, default=100)  # 插入顺序
    enabled = Column(Boolean, default=True)  # 是否启用
    position = Column(String, default="before_char")  # 位置
    use_regex = Column(Boolean, default=False)  # 是否使用正则
    # extensions 字段展开
    ext_position = Column(Integer, default=0)  # extensions.position
    ext_exclude_recursion = Column(Boolean, default=False)  # extensions.exclude_recursion
    ext_display_index = Column(Integer, default=0)  # extensions.display_index
    ext_probability = Column(Integer, default=100)  # extensions.probability
    ext_use_probability = Column(Boolean, default=True)  # extensions.useProbability
    ext_depth = Column(Integer, default=4)  # extensions.depth
    ext_selective_logic = Column(Integer, default=0)  # extensions.selectiveLogic
    ext_group = Column(String, default="")  # extensions.group
    ext_group_override = Column(Boolean, default=False)  # extensions.group_override
    ext_group_weight = Column(Integer, default=100)  # extensions.group_weight
    ext_prevent_recursion = Column(Boolean, default=False)  # extensions.prevent_recursion
    ext_delay_until_recursion = Column(Boolean, default=False)  # extensions.delay_until_recursion
    ext_scan_depth = Column(Integer, nullable=True)  # extensions.scan_depth
    ext_match_whole_words = Column(Boolean, nullable=True)  # extensions.match_whole_words
    ext_use_group_scoring = Column(Boolean, default=False)  # extensions.use_group_scoring
    ext_case_sensitive = Column(Boolean, nullable=True)  # extensions.case_sensitive
    ext_automation_id = Column(String, default="")  # extensions.automation_id
    ext_role = Column(Integer, default=0)  # extensions.role
    ext_vectorized = Column(Boolean, default=False)  # extensions.vectorized
    ext_sticky = Column(Integer, default=0)  # extensions.sticky
    ext_cooldown = Column(Integer, default=0)  # extensions.cooldown
    ext_delay = Column(Integer, default=0)  # extensions.delay
    ext_match_persona_description = Column(Boolean, default=False)  # extensions.match_persona_description
    ext_match_character_description = Column(Boolean, default=False)  # extensions.match_character_description
    ext_match_character_personality = Column(Boolean, default=False)  # extensions.match_character_personality
    ext_match_character_depth_prompt = Column(Boolean, default=False)  # extensions.match_character_depth_prompt
    ext_match_scenario = Column(Boolean, default=False)  # extensions.match_scenario
    ext_match_creator_notes = Column(Boolean, default=False)  # extensions.match_creator_notes
    ext_triggers = Column(JSONB, default=[])  # extensions.triggers
    # 关联关系
    character_book = relationship("CharacterBookModel", back_populates="entries")
    # 索引
    __table_args__ = (
        Index('idx_character_book_entries_character_book_id', 'character_book_id'),
        Index('idx_character_book_entries_enabled', 'enabled'),
        Index('idx_character_book_entries_position', 'position'),
    )
