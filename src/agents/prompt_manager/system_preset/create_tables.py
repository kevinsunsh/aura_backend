#!/usr/bin/env python3
"""
创建character相关数据库表的迁移脚本
"""
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from agents.agent_memory.database.database import Base, Database
from agents.prompt_manager.system_preset.models import (
    PromptModel, PromptOrderModel, SystemPresetModel
)
from agents.prompt_manager.system_preset.manager import DBManager
from agents.agent_memory.database.connection_config import DatabaseConfigManager

def create_system_preset_tables():
    """创建system_preset相关的所有表"""
    print("开始创建system_preset相关数据库表...")
    db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
    db = Database(db_conn_string)
    try:
        # 创建所有表
        # 先创建被引用表，再创建引用表
        Base.metadata.create_all(db.engine, tables=[
            SystemPresetModel.__table__,
            PromptModel.__table__,
            PromptOrderModel.__table__,
        ])
        
        print("✅ 成功创建system_preset相关数据库表:")
        print("  - prompts (提示表)")
        print("  - prompt_orders (提示顺序表)")
        
    except Exception as e:
        print(f"❌ 创建表时发生错误: {e}")
        return False
    
    return True

def drop_system_preset_tables():
    """删除system_preset相关的所有表"""
    print("开始删除system_preset相关数据库表...")
    try:
        # 删除所有表
        db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
        db = Database(db_conn_string)
        Base.metadata.drop_all(db.engine, tables=[
            SystemPresetModel.__table__,
            PromptModel.__table__,
            PromptOrderModel.__table__,
        ])
        print("✅ 成功删除system_preset相关数据库表")
    except Exception as e:
        print(f"❌ 删除表时发生错误: {e}")
        return False
    return True

def load_all_system_presets():
    """加载所有系统预设到数据库"""
    print("开始加载所有系统预设到数据库...")
    try:
        # 创建数据库管理器
        manager = DBManager()
        # 设置角色卡目录
        system_preset_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "system_preset")
        for file in os.listdir(system_preset_dir):
            if file.endswith('.json'):
                system_preset_name = file.replace('.json', '')
                system_preset = manager.load_system_preset_from_file(os.path.join(system_preset_dir, file))
                if system_preset:
                    print(f"成功导入系统预设: {system_preset_name}")
                else:
                    print(f"❌ 导入系统预设失败: {system_preset_name}")
        print(f"成功导入系统预设到数据库")
        return True
    except Exception as e:
        print(f"❌ 加载系统预设时发生错误: {e}")
        return False

def show_system_presets():
    """显示所有系统预设"""
    print("开始显示所有系统预设...")
    try:
        manager = DBManager()
        system_presets = manager.list_system_presets()
        for system_preset in system_presets:
            print(f"系统预设: {system_preset.name}")
            for prompt in system_preset.prompts:
                print(f"提示: {prompt.content}")
            for prompt_order in system_preset.prompt_orders:
                print(f"提示顺序: {prompt_order.character_id}")
        return True
    except Exception as e:
        print(f"❌ 显示系统预设时发生错误: {e}")
        return False

recreate_tables = True
if __name__ == "__main__":
    if recreate_tables:
        # success = drop_system_preset_tables()
        success = True
        if success:
            # success = create_system_preset_tables()
            success = True
            if success:
                success = load_all_system_presets()
                if success:
                    print("✅ 成功加载系统预设到数据库")
                else:
                    print("❌ 加载系统预设到数据库失败")
            else:
                print("❌ 创建系统预设相关数据库表失败")
    else:
        show_system_presets()
