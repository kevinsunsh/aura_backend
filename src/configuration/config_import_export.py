#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置导入导出示例

简单的配置导入导出工具，支持：
1. 从数据库导出配置到JSON文件
2. 从JSON文件导入配置到数据库
3. 配置验证和预览
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

from configuration.config_manager import ConfigManager
from configuration.config_loader import ConfigLoader
from agents.agent_memory.database.connection_config import DatabaseConfigManager

class ConfigImportExport:
    """配置导入导出工具"""
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化工具
        
        Args:
            db_conn_string: 数据库连接字符串
        """
        self.db_conn_string = db_conn_string or DatabaseConfigManager.get_config_by_environment().get_connection_string()
        self.config_manager = ConfigManager(self.db_conn_string)
        self.config_loader = ConfigLoader(self.db_conn_string)
    
    def export_configs(self, categories: List[str] = None, environment: str = "production", output_file: str = None) -> Dict[str, Any]:
        """
        导出配置到字典或文件
        
        Args:
            categories: 要导出的配置分类列表，None表示导出所有
            environment: 环境名称
            output_file: 输出文件路径，None表示只返回字典
            
        Returns:
            Dict: 导出的配置数据
        """
        print(f"正在导出 {environment} 环境的配置...")
        
        if categories is None:
            # 获取所有可用的配置分类
            categories = [
                'memory', 'chat', 'bot', 'personality', 'identity', 'relationship',
                'message_receive', 'normal_chat', 'focus_chat', 'emoji', 'expression',
                'mood', 'keyword_reaction', 'chinese_typo', 'response_post_process',
                'response_splitter', 'telemetry', 'experimental', 'model',
                'maim_message', 'lpmm_knowledge', 'tool', 'debug'
            ]
        
        exported_configs = {}
        
        for category in categories:
            try:
                # 从数据库加载配置
                config_id = f"{category}_config"
                config = self.config_manager.get_config(config_id, environment=environment)
                
                if config:
                    # 配置对象是配置类实例，需要从数据库模型获取元数据
                    config_id = f"{category}_config"
                    with self.config_manager.db.get_session() as session:
                        from configuration.config_manager import ConfigurationModel
                        config_model = session.query(ConfigurationModel).filter(
                            ConfigurationModel.id == config_id,
                            ConfigurationModel.environment == environment
                        ).first()
                        
                        if config_model:
                            exported_configs[category] = {
                                'id': config_model.id,
                                'name': config_model.name,
                                'description': config_model.description,
                                'category': config_model.category,
                                'config_data': config_model.config_data,
                                'version': config_model.version,
                                'environment': config_model.environment,
                                'is_active': config_model.is_active,
                                'is_default': config_model.is_default,
                                'created_at': config_model.created_at,
                                'updated_at': config_model.updated_at
                            }
                            print(f"✓ 导出配置: {category}")
                        else:
                            print(f"⚠ 配置模型不存在: {category}")
                else:
                    print(f"⚠ 配置不存在: {category}")
                    
            except Exception as e:
                print(f"✗ 导出配置出错 {category}: {e}")
        
        # 如果指定了输出文件，写入文件
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(exported_configs, f, indent=2, ensure_ascii=False)
                print(f"✓ 配置已导出到文件: {output_file}")
            except Exception as e:
                print(f"✗ 写入文件失败: {e}")
        
        print(f"导出完成: {len(exported_configs)} 个配置")
        return exported_configs
    
    def import_configs(self, configs: Dict[str, Any], environment: str = "production", overwrite: bool = False) -> bool:
        """
        导入配置到数据库
        
        Args:
            configs: 配置数据字典
            environment: 环境名称
            overwrite: 是否覆盖现有配置
            
        Returns:
            bool: 是否成功
        """
        print(f"正在导入配置到 {environment} 环境...")
        
        success_count = 0
        total_count = len(configs)
        
        for category, config_data in configs.items():
            try:
                # 检查配置是否已存在
                config_id = f"{category}_config"
                existing_config = self.config_manager.get_config(config_id, environment=environment)
                
                if existing_config and not overwrite:
                    print(f"⚠ 配置已存在，跳过: {category}")
                    continue
                
                # 导入配置
                result = self.config_manager.save_config(
                    config_id=config_data['id'],
                    config_data=config_data['config_data'],
                    name=config_data['name'],
                    category=config_data['category'],
                    description=config_data['description'],
                    environment=environment,
                    version=config_data['version'],
                    is_default=config_data['is_default']
                )
                
                if result:
                    success_count += 1
                    print(f"✓ 成功导入配置: {category}")
                else:
                    print(f"✗ 导入配置失败: {category}")
                    
            except Exception as e:
                print(f"✗ 导入配置出错 {category}: {e}")
        
        print(f"导入完成: {success_count}/{total_count} 成功")
        return success_count == total_count
    
    def import_from_file(self, file_path: str, environment: str = "production", overwrite: bool = False) -> bool:
        """
        从文件导入配置
        
        Args:
            file_path: 配置文件路径
            environment: 环境名称
            overwrite: 是否覆盖现有配置
            
        Returns:
            bool: 是否成功
        """
        try:
            print(f"从文件导入配置: {file_path}")
            
            # 读取配置文件
            with open(file_path, 'r', encoding='utf-8') as f:
                configs = json.load(f)
            
            # 导入配置
            return self.import_configs(configs, environment, overwrite)
            
        except Exception as e:
            print(f"从文件导入配置失败: {e}")
            return False
    
    def list_configs(self, environment: str = "production") -> List[str]:
        """
        列出指定环境的所有配置
        
        Args:
            environment: 环境名称
            
        Returns:
            List[str]: 配置分类列表
        """
        print(f"列出 {environment} 环境的配置...")
        
        categories = [
            'memory', 'chat', 'bot', 'personality', 'identity', 'relationship',
            'message_receive', 'normal_chat', 'focus_chat', 'emoji', 'expression',
            'mood', 'keyword_reaction', 'chinese_typo', 'response_post_process',
            'response_splitter', 'telemetry', 'experimental', 'model',
            'maim_message', 'lpmm_knowledge', 'tool', 'debug'
        ]
        
        available_configs = []
        
        for category in categories:
            try:
                config_id = f"{category}_config"
                config = self.config_manager.get_config(config_id, environment=environment)
                if config:
                    available_configs.append(category)
                    # 配置对象是配置类实例，没有name和version属性，使用分类名
                    print(f"✓ {category}: 配置已加载")
                else:
                    print(f"✗ {category}: 不存在")
                    
            except Exception as e:
                print(f"✗ {category}: 查询失败 - {e}")
        
        print(f"可用配置: {len(available_configs)}/{len(categories)}")
        return available_configs
    
    def preview_config(self, category: str, environment: str = "production") -> bool:
        """
        预览配置内容
        
        Args:
            category: 配置分类
            environment: 环境名称
            
        Returns:
            bool: 是否成功
        """
        try:
            print(f"预览配置: {category} ({environment})")
            
            config_id = f"{category}_config"
            config = self.config_manager.get_config(config_id, environment=environment)
            
            if config:
                # 从数据库模型获取元数据
                config_id = f"{category}_config"
                with self.config_manager.db.get_session() as session:
                    from configuration.config_manager import ConfigurationModel
                    config_model = session.query(ConfigurationModel).filter(
                        ConfigurationModel.id == config_id,
                        ConfigurationModel.environment == environment
                    ).first()
                    
                    if config_model:
                        print(f"配置名称: {config_model.name}")
                        print(f"配置描述: {config_model.description}")
                        print(f"配置版本: {config_model.version}")
                        print(f"是否激活: {config_model.is_active}")
                        print(f"是否默认: {config_model.is_default}")
                        print(f"创建时间: {config_model.created_at}")
                        print(f"更新时间: {config_model.updated_at}")
                        print("配置数据:")
                        print(json.dumps(config_model.config_data, indent=2, ensure_ascii=False))
                        return True
                    else:
                        print(f"配置模型不存在: {category}")
                        return False
            else:
                print(f"配置不存在: {category}")
                return False
                
        except Exception as e:
            print(f"预览配置失败: {e}")
            return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="配置导入导出工具")
    parser.add_argument("action", choices=["export", "import", "list", "preview"], help="操作类型")
    parser.add_argument("--file", "-f", help="配置文件路径")
    parser.add_argument("--categories", "-c", nargs="+", help="配置分类列表")
    parser.add_argument("--environment", "-e", default="production", help="环境名称")
    parser.add_argument("--overwrite", "-o", action="store_true", help="覆盖现有配置")
    parser.add_argument("--category", help="预览时指定的配置分类")
    
    args = parser.parse_args()
    
    # 创建工具实例
    tool = ConfigImportExport()
    
    if args.action == "export":
        # 导出配置
        output_file = args.file or f"configs_{args.environment}.json"
        tool.export_configs(args.categories, args.environment, output_file)
        
    elif args.action == "import":
        # 导入配置
        if not args.file:
            print("错误: 导入操作需要指定文件路径 (--file)")
            return 1
        
        success = tool.import_from_file(args.file, args.environment, args.overwrite)
        return 0 if success else 1
        
    elif args.action == "list":
        # 列出配置
        tool.list_configs(args.environment)
        
    elif args.action == "preview":
        # 预览配置
        if not args.category:
            print("错误: 预览操作需要指定配置分类 (--category)")
            return 1
        
        success = tool.preview_config(args.category, args.environment)
        return 0 if success else 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 