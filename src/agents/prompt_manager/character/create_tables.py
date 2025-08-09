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
from agents.prompt_manager.character.models import (
    CharacterModel, CharacterBookModel, CharacterBookEntryModel
)
from agents.prompt_manager.character.manager import DBManager
from agents.agent_memory.database.connection_config import DatabaseConfigManager

def create_character_tables():
    """创建character相关的所有表"""
    print("开始创建character相关数据库表...")
    db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
    db = Database(db_conn_string)
    try:
        # 创建所有表
        Base.metadata.create_all(db.engine, tables=[
            CharacterModel.__table__,
            CharacterBookModel.__table__,
            CharacterBookEntryModel.__table__
        ])
        
        print("✅ 成功创建character相关数据库表:")
        print("  - characters (角色主表)")
        print("  - character_books (角色书表)")
        print("  - character_book_entries (角色书条目表)")
        
    except Exception as e:
        print(f"❌ 创建表时发生错误: {e}")
        return False
    
    return True

def drop_character_tables():
    """删除character相关的所有表"""
    print("开始删除character相关数据库表...")
    try:
        # 删除所有表
        db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
        db = Database(db_conn_string)
        Base.metadata.drop_all(db.engine, tables=[
            CharacterModel.__table__,
            CharacterBookModel.__table__,
            CharacterBookEntryModel.__table__
        ])
        print("✅ 成功删除character相关数据库表")
    except Exception as e:
        print(f"❌ 删除表时发生错误: {e}")
        return False
    return True

def load_all_character_cards():
    """加载所有角色卡到数据库"""
    print("开始加载所有角色卡到数据库...")
    try:
        # 创建数据库管理器
        manager = DBManager()
        # 设置角色卡目录
        character_card_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "character_card")
        for file in os.listdir(character_card_dir):
            if file.endswith('.json'):
                character_name = file.replace('.json', '')
                character = manager.load_character_from_file(os.path.join(character_card_dir, file))
                if character:
                    print(f"成功导入角色: {character_name}")
                else:
                    print(f"❌ 导入角色失败: {character_name}")
        print(f"成功导入角色到数据库")
        return True
    except Exception as e:
        print(f"❌ 加载角色卡时发生错误: {e}")
        return False

def show_character_cards():
    """显示所有角色卡"""
    print("开始显示所有角色卡...")
    try:
        manager = DBManager()
        characters = manager.list_database_characters()
        for character in characters:
            print(f"角色: {character.name}")
            print(f"描述: {character.description}")
            print(f"性格: {character.personality}")
            print(f"创建者: {character.creator}")
            print(f"世界: {character.world}")
            print(f"话痨程度: {character.talkativeness}")
            print(f"收藏: {character.fav}")
            for entry in character.character_book.entries:
                print(f"角色书: {entry.content}")
        return True
    except Exception as e:
        print(f"❌ 显示角色卡时发生错误: {e}")
        return False

recreate_tables = True
if __name__ == "__main__":
    if recreate_tables:
        success = drop_character_tables()
        if success:
            success = create_character_tables()
            if success:
                success = load_all_character_cards()
                if success:
                    print("✅ 成功加载default_Seraphina角色卡到数据库")
                else:
                    print("❌ 加载default_Seraphina角色卡到数据库失败")
            else:
                print("❌ 创建character相关数据库表失败")
    else:
        show_character_cards()
