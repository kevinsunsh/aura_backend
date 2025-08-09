import os
import json
import uuid
import time
from typing import Optional, List
from sqlalchemy.orm import Session
from .models import WorldInfoEntry, WorldInfoBook
# 导入数据库相关模块
from agents.agent_memory.database.database import Database
from agents.agent_memory.database.connection_config import DatabaseConfigManager

class DBManager:
    """
    支持数据库的角色管理器，负责加载和管理角色卡
    支持从文件系统导入到数据库，以及从数据库加载角色
    """
    def __init__(self):
        self.db: Optional[Database] = None
        self.db_session: Optional[Session] = None
    
    def _get_db_session(self) -> Session:
        """获取数据库实例"""
        if self.db is None:
            # 创建数据库连接
            db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
            self.db = Database(db_conn_string)
            self.db_session = self.db.get_db()
        return self.db_session
    
    def create_world_info_book(self, world_info_book_name: str, world_info_book_data: dict) -> str:
        """创建世界书"""
        world_info_book_id = str(uuid.uuid4())
        
        # 创建主角色记录
        world_info_book = WorldInfoBook(
            id=world_info_book_id,
            name=world_info_book_name,
        )
        self._get_db_session().add(world_info_book)
        self._get_db_session().flush()  # 获取book.id
        
        # 如果有data字段，处理详细信息
        entries = world_info_book_data.get('entries', {})
        for entry_index in entries:
            entry = entries[entry_index]
            self._create_world_info_entry(world_info_book_id, entry)
        self._get_db_session().add(world_info_book)
        self._get_db_session().commit()
        return world_info_book_name
    
    def _create_world_info_entry(self, world_info_book_id: str, entry_data: dict):
        """创建世界书条目"""
        world_info_entry = WorldInfoEntry(
            world_info_book_id=world_info_book_id,
            uid=entry_data.get('uid', ''),
            keys=entry_data.get('key', []),
            keysecondary=entry_data.get('keysecondary', []),
            comment=entry_data.get('comment', ''),
            content=entry_data.get('content', ''),
            constant=entry_data.get('constant', False),
            selective=entry_data.get('selective', True),
            order=entry_data.get('order', 100),
            position=entry_data.get('position', 'before_char'),
            disable=entry_data.get('disable', False),
            display_index=entry_data.get('display_index', 0),
            addMemo=entry_data.get('addMemo', True),
            group=entry_data.get('group', ''),
            groupOverride=entry_data.get('groupOverride', False),
            groupWeight=entry_data.get('groupWeight', 100),
            sticky=entry_data.get('sticky', 0),
            cooldown=entry_data.get('cooldown', 0),
            delay=entry_data.get('delay', 0),
            probability=entry_data.get('probability', 100),
            depth=entry_data.get('depth', 4),
            useProbability=entry_data.get('useProbability', True),
            role=entry_data.get('role', 0),
            vectorized=entry_data.get('vectorized', False),
            excludeRecursion=entry_data.get('excludeRecursion', False),
            preventRecursion=entry_data.get('preventRecursion', False),
            delayUntilRecursion=entry_data.get('delayUntilRecursion', False),
            scanDepth=entry_data.get('scanDepth', None),
            caseSensitive=entry_data.get('caseSensitive', None),
            matchWholeWords=entry_data.get('matchWholeWords', None),
            useGroupScoring=entry_data.get('useGroupScoring', None),
            automationId=entry_data.get('automationId', ''),
            selectiveLogic=entry_data.get('selectiveLogic', 0),
            matchPersonaDescription=entry_data.get('matchPersonaDescription', False),
            matchCharacterDescription=entry_data.get('matchCharacterDescription', False),
            matchCharacterPersonality=entry_data.get('matchCharacterPersonality', False),
            matchCharacterDepthPrompt=entry_data.get('matchCharacterDepthPrompt', False),
            matchScenario=entry_data.get('matchScenario', False),
            matchCreatorNotes=entry_data.get('matchCreatorNotes', False),
            triggers=entry_data.get('triggers', []),
            characterFilter=entry_data.get('characterFilter', {})
        )
        self._get_db_session().add(world_info_entry)
    
    def get_world_info_book_by_name(self, name: str) -> Optional[WorldInfoBook]:
        """根据名称获取世界书"""
        return self._get_db_session().query(WorldInfoBook).filter(WorldInfoBook.name == name).first()
    
    def load_world_info_book_from_file(self, file_path: str) -> Optional[WorldInfoBook]:
        """
        从文件加载角色卡
        
        Args:
            file_path (str): 角色卡文件路径
            
        Returns:
            Optional[CharacterModel]: 加载的角色模型，如果失败返回None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 使用DAO创建角色到数据库并返回
            if self._get_db_session() is None:
                print("错误: 无法创建数据库连接")
                return None
            world_info_book_name = os.path.basename(file_path).replace('.json', '')
            world_info_book = self.get_world_info_book_by_name(world_info_book_name)
            if world_info_book:
                print(f"从数据库加载世界书: {world_info_book.id}")
                return world_info_book
            
            world_info_book_name = self.create_world_info_book(world_info_book_name, data)
            world_info_book = self.get_world_info_book_by_name(world_info_book_name)
            print(f"成功加载世界书到数据库: {world_info_book.id} (ID: {world_info_book_name})")
            return world_info_book
        except FileNotFoundError:
            print(f"错误: 角色卡文件未找到 {file_path}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            print(f"错误: 解析角色卡文件失败 {file_path}: {e}")
            return None
    
    def list_world_info_books(self) -> List[WorldInfoBook]:
        """列出所有世界书"""
        return self._get_db_session().query(WorldInfoBook).all()

    def list_all_activated_entries(self) -> List[WorldInfoEntry]:
        return self._get_db_session().query(WorldInfoEntry).filter(WorldInfoEntry.disable == False).all()