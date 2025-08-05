#!/usr/bin/env python3
"""
配置管理工具
用于管理数据库中的配置
"""

import argparse
import json
import sys
import os
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import text
from agents.agent_memory.database.connection_config import DatabaseConfigManager
try:
    from configuration.config_loader import ConfigLoader, load_config
    from configuration.config import get_db_conn_string
    from agents.agent_memory.database.database import Database
except ImportError as e:
    print(f"导入错误: {e}")
    sys.exit(1)

def print_config_info(config_data: Dict[str, Any], indent: int = 0):
    """打印配置信息"""
    indent_str = "  " * indent
    
    for key, value in config_data.items():
        if isinstance(value, dict):
            print(f"{indent_str}{key}:")
            print_config_info(value, indent + 1)
        elif isinstance(value, list):
            print(f"{indent_str}{key}: {value}")
        else:
            print(f"{indent_str}{key}: {value}")

def list_configs(args):
    """列出所有配置"""
    try:
        db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
        config_loader = ConfigLoader(db_conn_string)
        
        configs = config_loader.get_config_list(environment=args.environment)
        
        if not configs:
            print("没有找到配置")
            return
        
        print(f"环境: {args.environment}")
        print("=" * 50)
        
        for config in configs:
            print(f"ID: {config['id']}")
            print(f"名称: {config['name']}")
            print(f"分类: {config['category']}")
            print(f"版本: {config['version']}")
            print(f"激活: {config['is_active']}")
            print(f"默认: {config['is_default']}")
            print(f"创建时间: {datetime.fromtimestamp(config['created_at'] / 1000)}")
            print(f"更新时间: {datetime.fromtimestamp(config['updated_at'] / 1000)}")
            print("-" * 30)
    except Exception as e:
        print(f"列出配置失败: {e}")
        sys.exit(1)

def show_config(args):
    """显示特定配置"""
    try:
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        config = config_loader.load_specific_config(
            args.config_name, 
            environment=args.environment
        )
        
        if config is None:
            print(f"配置不存在: {args.config_name}")
            return
        
        print(f"配置: {args.config_name}")
        print(f"环境: {args.environment}")
        print("=" * 50)
        
        # 转换为字典并打印
        if hasattr(config, '__dict__'):
            config_dict = config.__dict__
        else:
            config_dict = config
        
        print_config_info(config_dict)
    except Exception as e:
        print(f"显示配置失败: {e}")
        sys.exit(1)

def save_config(args):
    """保存配置"""
    try:
        # 读取配置文件
        if args.file:
            with open(args.file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        else:
            # 从标准输入读取
            config_data = json.loads(sys.stdin.read())
        
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        success = config_loader.save_config(
            config_name=args.config_name,
            config_data=config_data,
            environment=args.environment,
            description=args.description,
            is_default=args.default
        )
        
        if success:
            print(f"配置保存成功: {args.config_name}")
        else:
            print(f"配置保存失败: {args.config_name}")
            sys.exit(1)
            
    except Exception as e:
        print(f"保存配置失败: {e}")
        sys.exit(1)

def delete_config(args):
    """删除配置"""
    try:
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        success = config_loader.delete_config(
            config_name=args.config_name,
            environment=args.environment
        )
        
        if success:
            print(f"配置删除成功: {args.config_name}")
        else:
            print(f"配置删除失败: {args.config_name}")
            sys.exit(1)
            
    except Exception as e:
        print(f"删除配置失败: {e}")
        sys.exit(1)

def init_configs(args):
    """初始化默认配置"""
    try:
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        success = config_loader.initialize_default_configs(args.environment)
        
        if success:
            print("默认配置初始化成功")
        else:
            print("默认配置初始化失败")
            sys.exit(1)
            
    except Exception as e:
        print(f"初始化配置失败: {e}")
        sys.exit(1)

def migrate_config(args):
    """迁移文件配置到数据库"""
    try:
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        success = config_loader.migrate_from_file_config(
            config_file_path=args.file,
            environment=args.environment
        )
        
        if success:
            print(f"配置迁移成功: {args.file}")
        else:
            print(f"配置迁移失败: {args.file}")
            sys.exit(1)
            
    except Exception as e:
        print(f"迁移配置失败: {e}")
        sys.exit(1)

def export_config(args):
    """导出配置到文件"""
    try:
        db_conn_string = get_db_conn_string()
        config_loader = DatabaseConfigLoader(db_conn_string)
        
        config = config_loader.load_specific_config(
            args.config_name, 
            environment=args.environment
        )
        
        if config is None:
            print(f"配置不存在: {args.config_name}")
            return
        
        # 转换为字典
        if hasattr(config, '__dict__'):
            config_dict = config.__dict__
        else:
            config_dict = config
        
        # 写入文件
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
        
        print(f"配置已导出到: {args.output}")
        
    except Exception as e:
        print(f"导出配置失败: {e}")
        sys.exit(1)

def recreate_config_tables(args):
    """重建配置相关的三张表（configurations, configuration_history, configuration_templates）"""
    try:
        db_conn_string = get_db_conn_string()
        db = Database(db_conn_string)
        with db.get_session() as session:
            # 只删除配置相关的表
            session.execute(text("DROP TABLE IF EXISTS configurations CASCADE"))
            session.execute(text("DROP TABLE IF EXISTS configuration_history CASCADE"))
            session.execute(text("DROP TABLE IF EXISTS configuration_templates CASCADE"))
            session.commit()
            print("✅ 配置相关表已删除")
        # 重建表
        db.create_all_tables()
        print("✅ 配置相关表已重建")
    except Exception as e:
        print(f"重建配置相关表失败: {e}")
        sys.exit(1)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="配置管理工具")
    parser.add_argument('--environment', '-e', default='production', 
                       help='环境 (默认: production)')
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # list 命令
    list_parser = subparsers.add_parser('list', help='列出所有配置')
    list_parser.set_defaults(func=list_configs)
    
    # show 命令
    show_parser = subparsers.add_parser('show', help='显示特定配置')
    show_parser.add_argument('config_name', help='配置名称')
    show_parser.set_defaults(func=show_config)
    
    # save 命令
    save_parser = subparsers.add_parser('save', help='保存配置')
    save_parser.add_argument('config_name', help='配置名称')
    save_parser.add_argument('--file', '-f', help='配置文件路径')
    save_parser.add_argument('--description', '-d', help='配置描述')
    save_parser.add_argument('--default', action='store_true', help='设为默认配置')
    save_parser.set_defaults(func=save_config)
    
    # delete 命令
    delete_parser = subparsers.add_parser('delete', help='删除配置')
    delete_parser.add_argument('config_name', help='配置名称')
    delete_parser.set_defaults(func=delete_config)
    
    # init 命令
    init_parser = subparsers.add_parser('init', help='初始化默认配置')
    init_parser.set_defaults(func=init_configs)
    
    # migrate 命令
    migrate_parser = subparsers.add_parser('migrate', help='迁移文件配置到数据库')
    migrate_parser.add_argument('file', help='配置文件路径')
    migrate_parser.set_defaults(func=migrate_config)
    
    # export 命令
    export_parser = subparsers.add_parser('export', help='导出配置到文件')
    export_parser.add_argument('config_name', help='配置名称')
    export_parser.add_argument('output', help='输出文件路径')
    export_parser.set_defaults(func=export_config)
    
    # recreate_tables 命令
    recreate_parser = subparsers.add_parser('recreate_tables', help='重建配置相关的三张表（configurations, configuration_history, configuration_templates）')
    recreate_parser.set_defaults(func=recreate_config_tables)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)

if __name__ == '__main__':
    main() 