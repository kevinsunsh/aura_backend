#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置初始化脚本

用于生成默认配置并保存到数据库
"""

import sys
import os
# 自动添加src到sys.path，保证包内导入正常
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import time
from configuration.config_manager import DatabaseConfigManager
from configuration.config import get_db_conn_string
from configuration.official_configs import (
    MemoryConfig, ChatConfig, BotConfig, PersonalityConfig, IdentityConfig,
    RelationshipConfig, MessageReceiveConfig, NormalChatConfig, FocusChatConfig,
    EmojiConfig, ExpressionConfig, MoodConfig, KeywordReactionConfig,
    ChineseTypoConfig, ResponsePostProcessConfig, ResponseSplitterConfig,
    TelemetryConfig, ExperimentalConfig, ModelConfig, MaimMessageConfig,
    LPMMKnowledgeConfig, ToolConfig, DebugConfig
)

def create_default_configs():
    """创建默认配置"""
    
    # 配置映射
    config_classes = {
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
    
    # 特殊配置（需要额外参数）
    special_configs = {
        'bot': {
            'qq_account': '123456789',
            'nickname': 'Aura Bot'
        },
        'personality': {
            'personality_core': '我是一个友好的AI助手，喜欢帮助用户解决问题。'
        },
        'identity': {
            'identity_detail': ['AI助手', '智能对话机器人']
        }
    }
    
    return config_classes, special_configs

def init_configs(environment: str = "production"):
    """初始化配置到数据库"""
    
    print(f"开始初始化 {environment} 环境的配置...")
    
    # 创建配置管理器
    config_manager = DatabaseConfigManager(get_db_conn_string())
    
    # 获取配置类
    config_classes, special_configs = create_default_configs()
    
    success_count = 0
    total_count = len(config_classes)
    
    for category, config_class in config_classes.items():
        try:
            print(f"正在初始化配置: {category}")
            
            # 检查是否已存在
            existing_config = config_manager.get_config(category, environment)
            if existing_config:
                print(f"⚠ 配置已存在，跳过: {category}")
                continue
            
            # 创建配置实例
            if category in special_configs:
                # 使用特殊参数
                config_instance = config_class(**special_configs[category])
            else:
                # 使用默认参数
                config_instance = config_class()
            
            # 转换为字典
            config_data = config_instance.__dict__
            
            # 处理特殊类型（set转换为list）
            for key, value in config_data.items():
                if isinstance(value, set):
                    config_data[key] = list(value)
            
            # 保存到数据库
            result = config_manager.save_config(
                config_id=f"{category}_config",
                config_data=config_data,
                name=f"{category.title()} Configuration",
                category=category,
                description=f"Default {category} configuration",
                environment=environment,
                version="1.0.0",
                is_default=True
            )
            
            if result:
                success_count += 1
                print(f"✓ 成功初始化配置: {category}")
            else:
                print(f"✗ 初始化配置失败: {category}")
                
        except Exception as e:
            print(f"✗ 初始化配置出错 {category}: {e}")
    
    print(f"初始化完成: {success_count}/{total_count} 成功")
    return success_count == total_count

def main():
    """主函数"""
    print("配置初始化工具")
    print("=" * 50)
    
    # 初始化生产环境配置
    success = init_configs("production")
    
    if success:
        print("🎉 所有配置初始化成功!")
    else:
        print("⚠ 部分配置初始化失败，请检查日志")
    
    return success

if __name__ == "__main__":
    exit(0 if main() else 1) 