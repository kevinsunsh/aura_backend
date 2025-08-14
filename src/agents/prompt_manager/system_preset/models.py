from typing import Dict, Any
from sqlalchemy.dialects.postgresql import JSONB
from agents.agent_memory.database.database import Base
from sqlalchemy import Column, String, Integer, Boolean, Text, Float, DateTime, BigInteger, Index, JSON, PrimaryKeyConstraint, ForeignKey
from sqlalchemy.orm import relationship

class InjectionPosition:
    RELATIVE = 0
    ABSOLUTE = 1

class PromptModel(Base):
    """提示"""
    __tablename__ = 'prompts'
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    system_preset_id = Column(String, ForeignKey("system_presets.id"), nullable=False)  # 系统预设ID
    identifier = Column(String, nullable=False)  # 标识符
    name = Column(String, nullable=False)  # 名称
    role = Column(String, nullable=False)  # 角色
    system_prompt = Column(Boolean, default=False)  # 系统提示
    enabled = Column(Boolean, default=True)  # 启用
    position = Column(Integer, default=0)  # 位置
    marker = Column(Boolean, default=False)  # 标记
    content = Column(Text, nullable=False)  # 内容
    injection_depth = Column(Integer, default=4)  # 注入深度
    injection_order = Column(Integer, default=100)  # 注入顺序
    injection_trigger = Column(JSON, default=[])  # 注入触发
    injection_position = Column(Integer, default=InjectionPosition.RELATIVE)  # 注入位置
    extension = Column(Boolean, default=False)  # 扩展
    forbid_overrides = Column(Boolean, default=False)  # 禁止覆盖
    # 关联关系
    system_preset = relationship("SystemPresetModel", back_populates="prompts")  # 系统预设
    # 索引
    __table_args__ = (
        Index('idx_prompts_system_preset_id', 'system_preset_id'),
        Index('idx_prompts_enabled', 'enabled'),
        Index('idx_prompts_marker', 'marker'),
        Index('idx_prompts_injection_position', 'injection_position'),
        Index('idx_prompts_injection_depth', 'injection_depth'),
        Index('idx_prompts_forbid_overrides', 'forbid_overrides'),
    )
    
    def __init__(self, **kwargs):
        """初始化提示模型，使用与数据库字段相同的默认值"""
        # 设置默认值，与数据库字段的默认值保持一致
        defaults = {
            'system_prompt': True,
            'enabled': True,
            'position': 0,
            'marker': False,
            'injection_depth': 4,
            'injection_order': 100,
            'injection_trigger': [],
            'injection_position': InjectionPosition.RELATIVE,
            'extension': False,
            'forbid_overrides': False,
            'role': 'system'
        }
        
        # 应用默认值
        for key, default_value in defaults.items():
            if key not in kwargs:
                kwargs[key] = default_value
        
        # 调用父类的初始化方法
        super().__init__(**kwargs)

class PromptOrderModel(Base):
    """提示顺序"""
    __tablename__ = 'prompt_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    system_preset_id = Column(String, ForeignKey("system_presets.id"), nullable=False)  # 系统预设ID
    character_id = Column(Integer, nullable=False)  # 角色ID
    order = Column(JSONB, nullable=False)  # 顺序
    # 关联关系
    system_preset = relationship("SystemPresetModel", back_populates="prompt_orders")  # 系统预设
    # 索引
    __table_args__ = (
        Index('idx_prompt_orders_system_preset_id', 'system_preset_id'),
        Index('idx_prompt_orders_character_id', 'character_id'),
    )

class SystemPresetModel(Base):
    """系统预设"""
    __tablename__ = 'system_presets'
    id = Column(String, primary_key=True)  # 主键
    name = Column(String, unique=True, nullable=False)  # 名称，唯一
    chat_completion_source = Column(String, default="custom")  # 聊天完成源
    openai_model = Column(String, default="")  # OpenAI模型
    claude_model = Column(String, default="claude-3-sonnet-20240229")  # Claude模型
    windowai_model = Column(String, default="")  # WindowAI模型
    openrouter_model = Column(String, default="OR_Website")  # OpenRouter模型
    openrouter_use_fallback = Column(Boolean, default=False)  # OpenRouter使用回退
    openrouter_group_models = Column(Boolean, default=False)  # OpenRouter分组模型
    openrouter_sort_models = Column(String, default="alphabetically")  # OpenRouter排序模型
    openrouter_providers = Column(JSONB, default=[])  # OpenRouter提供者
    openrouter_allow_fallbacks = Column(Boolean, default=True)  # OpenRouter允许回退
    openrouter_middleout = Column(String, default="on")  # OpenRouter中间输出
    ai21_model = Column(String, default="jamba-1.5-large")  # AI21模型
    mistralai_model = Column(String, default="mistral-medium-latest")  # MistralAI模型
    cohere_model = Column(String, default="command-r-plus-08-2024")  # Cohere模型
    perplexity_model = Column(String, default="llama-3-70b-instruct")  # Perplexity模型
    groq_model = Column(String, default="llama3-70b-8192")  # Groq模型
    zerooneai_model = Column(String, default="yi-large")  # ZeroOneAI模型
    blockentropy_model = Column(String, default="be-70b-base-llama3.1")  # BlockEntropy模型
    custom_model = Column(String, default="deepseek-ai/DeepSeek-R1")  # 自定义模型
    custom_prompt_post_processing = Column(String, default="strict")  # 自定义提示后处理
    google_model = Column(String, default="gemini-1.5-pro-latest")  # Google模型
    temperature = Column(Float, default=0.01)  # 温度
    frequency_penalty = Column(Float, default=0.09)  # 频率惩罚
    presence_penalty = Column(Float, default=0.08)  # 存在惩罚
    top_p = Column(Float, default=0.93)  # Top-P
    top_k = Column(Integer, default=0)  # Top-K
    top_a = Column(Float, default=1)  # Top-A
    min_p = Column(Float, default=0)  # Min-P
    repetition_penalty = Column(Float, default=1)  # 重复惩罚
    openai_max_context = Column(Integer, default=963127)  # OpenAI最大上下文
    openai_max_tokens = Column(Integer, default=4000)  # OpenAI最大令牌
    wrap_in_quotes = Column(Boolean, default=False)  # 包裹在引号中
    names_behavior = Column(Integer, default=-1)  # 名称行为
    send_if_empty = Column(String, default="")  # 如果为空发送
    jailbreak_system = Column(Boolean, default=False)  # 越狱系统
    impersonation_prompt = Column(String, default="[Write your next reply from the point of view of {{user}}, using the chat history so far as a guideline for the writing style of {{user}}. Write 1 reply only in internet RP style. Don't write as {{char}} or system. Don't describe actions of {{char}}.]")  # 模仿提示
    new_chat_prompt = Column(String, default="")  # 新聊天提示
    new_group_chat_prompt = Column(String, default="")  # 新群聊天提示
    new_example_chat_prompt = Column(String, default="[Example Chat]")  # 新示例聊天提示
    continue_nudge_prompt = Column(String, default="[推进剧情，避免突发事件发生]")  # 继续推动提示
    bias_preset_selected = Column(String, default="反R1 filter")  # 偏见预设选择
    max_context_unlocked = Column(Boolean, default=True)  # 最大上下文解锁
    wi_format = Column(String, default="[data:\n{0}]\n")  # WI格式
    scenario_format = Column(String, default="[Circumstances and context of the dialogue: {{scenario}}]")  # 场景格式
    personality_format = Column(String, default="[{{char}}'s personality: {{personality}}]")  # 性格格式
    group_nudge_prompt = Column(String, default="[Write the next reply only as {{char}}].")  # 组推动提示
    stream_openai = Column(Boolean, default=True)  # 流式OpenAI
    api_url_scale = Column(String, default="")  # API URL Scale
    show_external_models = Column(Boolean, default=True)  # 显示外部模型
    assistant_prefill = Column(String, default="")  # 助手预填
    assistant_impersonation = Column(String, default="")  # 助手模仿
    claude_use_sysprompt = Column(Boolean, default=False)  # Claude使用系统提示
    use_makersuite_sysprompt = Column(Boolean, default=True)  # 使用MakerSuite系统提示
    use_alt_scale = Column(Boolean, default=False)  # 使用Alt Scale
    squash_system_messages = Column(Boolean, default=True)  # 压缩系统消息
    image_inlining = Column(Boolean, default=False)  # 图片内联
    inline_image_quality = Column(String, default="low")  # 内联图片质量
    bypass_status_check = Column(Boolean, default=False)  # 绕过状态检查
    continue_prefill = Column(Boolean, default=False)  # 继续预填
    continue_postfix = Column(String, default=" ")  # 继续后缀
    function_calling = Column(Boolean, default=False)  # 函数调用
    show_thoughts = Column(Boolean, default=False)  # 显示思考
    seed = Column(Integer, default=-1)  # 种子
    n = Column(Integer, default=1)  # 数量
    # 关联关系
    prompts = relationship("PromptModel", back_populates="system_preset")  # 提示
    prompt_orders = relationship("PromptOrderModel", back_populates="system_preset")  # 提示顺序
    # 索引
    __table_args__ = (
        Index('idx_system_presets_name', 'name'),
    )
