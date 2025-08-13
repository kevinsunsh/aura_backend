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
from agents.prompt_manager.world_info.models import (
    WorldInfoEntry, WorldInfoBook
)
from agents.prompt_manager.world_info.manager import DBManager
from agents.agent_memory.database.connection_config import DatabaseConfigManager

def create_world_info_tables():
    """创建world_info相关的所有表"""
    print("开始创建world_info相关数据库表...")
    db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
    db = Database(db_conn_string)
    try:
        # 创建所有表
        # 先创建被引用表，再创建引用表
        Base.metadata.create_all(db.engine, tables=[
            WorldInfoBook.__table__,
            WorldInfoEntry.__table__,
        ])
        
        print("✅ 成功创建world_info相关数据库表:")
        print("  - world_info_entries (世界书条目表)")
        print("  - world_info_books (世界书表)")
        
    except Exception as e:
        print(f"❌ 创建表时发生错误: {e}")
        return False
    
    return True

def drop_world_info_tables():
    """删除world_info相关的所有表"""
    print("开始删除world_info相关数据库表...")
    try:
        # 删除所有表
        db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
        db = Database(db_conn_string)
        Base.metadata.drop_all(db.engine, tables=[
            WorldInfoEntry.__table__,
            WorldInfoBook.__table__,
        ])
        print("✅ 成功删除world_info相关数据库表")
    except Exception as e:
        print(f"❌ 删除表时发生错误: {e}")
        return False
    return True

def load_all_world_info_books():
    """加载所有世界书到数据库"""
    print("开始加载所有世界书到数据库...")
    try:
        # 创建数据库管理器
        manager = DBManager()
        # 设置角色卡目录
        world_info_book_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "world_book")
        for file in os.listdir(world_info_book_dir):
            if file.endswith('.json'):
                world_info_name = file.replace('.json', '')
                world_info = manager.load_world_info_book_from_file(os.path.join(world_info_book_dir, file))
                if world_info:
                    print(f"成功导入世界书: {world_info_name}")
                else:
                    print(f"❌ 导入世界书失败: {world_info_name}")
        print(f"成功导入世界书到数据库")
        return True
    except Exception as e:
        print(f"❌ 加载世界书时发生错误: {e}")
        return False

def show_world_info_books():
    """显示所有世界书"""
    print("开始显示所有世界书...")
    try:
        manager = DBManager()
        world_info_books = manager.list_world_info_books()
        for world_info_book in world_info_books:
            print(f"世界书: {world_info_book.name}")
            for entry in world_info_book.entries:
                print(f"世界书: {entry.content}")
                print(f"世界书: {entry.comment}")
                print(f"世界书: {entry.keys}")
                print(f"世界书: {entry.keysecondary}")
        return True
    except Exception as e:
        print(f"❌ 显示角色卡时发生错误: {e}")
        return False

recreate_tables = True
if __name__ == "__main__":
    if recreate_tables:
        success = drop_world_info_tables()
        if success:
            success = create_world_info_tables()
            if success:
                success = load_all_world_info_books()
                if success:
                    print("✅ 成功加载world_info_book到数据库")
                else:
                    print("❌ 加载world_info_book到数据库失败")
            else:
                print("❌ 创建world_info相关数据库表失败")
    else:
        show_world_info_books()
