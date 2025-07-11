"""
配置系统模块

提供数据库驱动的配置管理功能，支持多环境配置、版本控制、缓存等特性。
"""

# 导入主要组件
from .config_loader import (
    DatabaseConfigLoader,
    load_config,
    load_specific_config,
    get_config_loader,
    Config
)

from .config_manager import DatabaseConfigManager

from .database_models import (
    ConfigurationModel,
    ConfigurationHistoryModel,
    ConfigurationTemplateModel
)

from .config import (
    load_config_from_database,
    load_specific_config_from_database,
    initialize_database_configs,
    migrate_file_config_to_database,
    get_db_conn_string,
    global_config
)

# 导出主要类和函数
__all__ = [
    # 配置加载器
    'DatabaseConfigLoader',
    'load_config',
    'load_specific_config',
    'get_config_loader',
    'Config',
    
    # 配置管理器
    'DatabaseConfigManager',
    
    # 数据库模型
    'ConfigurationModel',
    'ConfigurationHistoryModel',
    'ConfigurationTemplateModel',
    
    # 便捷函数
    'load_config_from_database',
    'load_specific_config_from_database',
    'initialize_database_configs',
    'migrate_file_config_to_database',
    'get_db_conn_string',
    'global_config',
]

# 版本信息
__version__ = "1.0.0"
__author__ = "Aura Backend Team"
__description__ = "数据库驱动的配置管理系统"
