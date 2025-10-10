"""
Agent 流程配置
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ModelType(Enum):
    """模型类型"""
    GOAL_ANALYZER = "goal_analyzer"
    ACTION_PLANNER = "action_planner"
    RESULT_VALIDATOR = "result_validator"
    PLANNING_CONTROLLER = "planning_controller"


@dataclass
class AgentFlowConfig:
    """Agent 流程配置"""
    
    # 模型配置
    models: Dict[ModelType, str] = None
    
    # 超时配置
    execution_timeout: int = 300  # 5分钟
    validation_timeout: int = 60  # 1分钟
    max_iterations: int = 10  # 最大迭代次数
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0  # 秒
    
    # 日志配置
    log_level: str = "INFO"
    enable_performance_logging: bool = True
    
    # 中断配置
    enable_interruption: bool = True
    interruption_timeout: int = 600  # 10分钟
    
    def __post_init__(self):
        if self.models is None:
            self.models = {
                ModelType.GOAL_ANALYZER: "gpt-4",
                ModelType.ACTION_PLANNER: "gpt-4",
                ModelType.RESULT_VALIDATOR: "gpt-4",
                ModelType.PLANNING_CONTROLLER: "gpt-4"
            }


# 默认配置
DEFAULT_CONFIG = AgentFlowConfig()


def get_config() -> AgentFlowConfig:
    """获取配置"""
    return DEFAULT_CONFIG


def update_config(**kwargs) -> AgentFlowConfig:
    """更新配置"""
    global DEFAULT_CONFIG
    for key, value in kwargs.items():
        if hasattr(DEFAULT_CONFIG, key):
            setattr(DEFAULT_CONFIG, key, value)
    return DEFAULT_CONFIG
