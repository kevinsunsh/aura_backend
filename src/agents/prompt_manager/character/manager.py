import json
import uuid
import time
from typing import Optional, List
from sqlalchemy.orm import Session
from .models import CharacterModel, CharacterBookModel, CharacterBookEntryModel
# 导入数据库相关模块
from agents.agent_memory.database.database import Database
from agents.agent_memory.database.connection_config import DatabaseConfigManager
from agents.prompt_manager.utils import char_turn_process, content_char_turn_process, count_tokens_openai

class DBManager:
    """
    支持数据库的角色管理器，负责加载和管理角色卡
    支持从文件系统导入到数据库，以及从数据库加载角色
    """
    def __init__(self):
        self.current_character: Optional[CharacterModel] = None
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
    
    def create_character(self, character_data: dict) -> str:
        """创建角色"""
        character_id = str(uuid.uuid4())
        current_time = int(time.time() * 1000)
        
        # 创建主角色记录
        character = CharacterModel(
            id=character_id,
            name=character_data.get('name', ''),
            description=character_data.get('description', ''),
            description_tokens=count_tokens_openai(character_data.get('description', '')),
            personality=character_data.get('personality', ''),
            personality_tokens=count_tokens_openai(character_data.get('personality', '')),
            scenario=character_data.get('scenario', ''),
            scenario_tokens=count_tokens_openai(character_data.get('scenario', '')),
            first_mes=character_data.get('first_mes', ''),
            first_mes_tokens=count_tokens_openai(character_data.get('first_mes', '')),
            mes_example=character_data.get('mes_example', ''),
            mes_example_tokens=count_tokens_openai(character_data.get('mes_example', '')),
            avatar=character_data.get('avatar', 'none'),
            create_date=character_data.get('create_date', ''),
            talkativeness=character_data.get('talkativeness', '0.5'),
            fav=character_data.get('fav', False),
            creator_notes=character_data.get('creator_notes', ''),
            system_prompt=character_data.get('system_prompt', ''),
            system_prompt_tokens=count_tokens_openai(character_data.get('system_prompt', '')),
            post_history_instructions=character_data.get('post_history_instructions', ''),
            tags=character_data.get('tags', []),
            creator=character_data.get('creator', ''),
            alternate_greetings=character_data.get('alternate_greetings', []),
            group_only_greetings=character_data.get('group_only_greetings', []),
            character_version=character_data.get('character_version', ''),
            world=character_data.get('world', ''),
            depth_prompt=character_data.get('depth_prompt', {}),
            spec=character_data.get('spec', 'chara_card_v3'),
            spec_version=character_data.get('spec_version', '3.0')
        )
        
        # 如果有data字段，处理详细信息
        data = character_data.get('data', {})
        if data:
            # 覆盖主要字段
            character.description = data.get('description', character.description)
            character.personality = data.get('personality', character.personality)
            character.scenario = data.get('scenario', character.scenario)
            character.first_mes = data.get('first_mes', character.first_mes)
            character.mes_example = data.get('mes_example', character.mes_example)
            character.creator_notes = data.get('creator_notes', character.creator_notes)
            character.system_prompt = data.get('system_prompt', character.system_prompt)
            character.post_history_instructions = data.get('post_history_instructions', character.post_history_instructions)
            character.creator = data.get('creator', character.creator)
            character.character_version = data.get('character_version', character.character_version)
        
        # 先提交角色到数据库
        self._get_db_session().add(character)
        self._get_db_session().commit()
        
        # 然后处理角色书（如果有的话）
        if data and data.get('character_book'):
            self._create_character_book(character_id, data['character_book'], current_time)
            self._get_db_session().commit()
        
        return character_id
    
    def _create_character_book(self, character_id: str, character_book_data: dict, current_time: int):
        """创建角色书"""
        book = CharacterBookModel(
            id=character_id,  # 使用角色ID作为角色书ID
            character_id=character_id,  # 添加外键关联
            name=character_book_data.get('name', '')
        )
        self._get_db_session().add(book)
        self._get_db_session().flush()  # 获取book.id
        
        # 创建角色书条目
        entries = character_book_data.get('entries', [])
        for entry_data in entries:
            self._create_character_book_entry(character_id, entry_data, current_time)
    
    def _create_character_book_entry(self, book_id: str, entry_data: dict, current_time: int):
        """创建角色书条目"""
        # 处理扩展信息
        extensions = entry_data.get('extensions', {})
        book_entry_content = entry_data.get('content', '')
        book_entry_content = content_char_turn_process(book_entry_content)
        book_entry = CharacterBookEntryModel(
            character_book_id=book_id,
            keys=entry_data.get('keys', []),
            secondary_keys=entry_data.get('secondary_keys', []),
            comment=entry_data.get('comment', ''),
            content=book_entry_content,
            content_tokens=count_tokens_openai(book_entry_content),
            constant=entry_data.get('constant', False),
            selective=entry_data.get('selective', True),
            insertion_order=entry_data.get('insertion_order', 100),
            enabled=entry_data.get('enabled', True),
            position=entry_data.get('position', 'before_char'),
            use_regex=entry_data.get('use_regex', False),
            # 展开扩展信息到具体字段
            ext_position=extensions.get('position', 0),
            ext_exclude_recursion=extensions.get('exclude_recursion', False),
            ext_display_index=extensions.get('display_index', 0),
            ext_probability=extensions.get('probability', 100),
            ext_use_probability=extensions.get('useProbability', True),
            ext_depth=extensions.get('depth', 4),
            ext_selective_logic=extensions.get('selectiveLogic', 0),
            ext_group=extensions.get('group', ''),
            ext_group_override=extensions.get('group_override', False),
            ext_group_weight=extensions.get('group_weight', 100),
            ext_prevent_recursion=extensions.get('prevent_recursion', False),
            ext_delay_until_recursion=extensions.get('delay_until_recursion', False),
            ext_scan_depth=extensions.get('scan_depth'),
            ext_match_whole_words=extensions.get('match_whole_words'),
            ext_use_group_scoring=extensions.get('use_group_scoring', False),
            ext_case_sensitive=extensions.get('case_sensitive'),
            ext_automation_id=extensions.get('automation_id', ''),
            ext_role=extensions.get('role', 0),
            ext_vectorized=extensions.get('vectorized', False),
            ext_sticky=extensions.get('sticky', 0),
            ext_cooldown=extensions.get('cooldown', 0),
            ext_delay=extensions.get('delay', 0),
            ext_match_persona_description=extensions.get('match_persona_description', False),
            ext_match_character_description=extensions.get('match_character_description', False),
            ext_match_character_personality=extensions.get('match_character_personality', False),
            ext_match_character_depth_prompt=extensions.get('match_character_depth_prompt', False),
            ext_match_scenario=extensions.get('match_scenario', False),
            ext_match_creator_notes=extensions.get('match_creator_notes', False),
            ext_triggers=extensions.get('triggers', [])
        )
        self._get_db_session().add(book_entry)
    
    def get_character_by_name(self, name: str) -> Optional[CharacterModel]:
        """根据名称获取角色"""
        return self._get_db_session().query(CharacterModel).filter(CharacterModel.name == name).first()
    
    def get_character_by_id(self, id: str) -> Optional[CharacterModel]:
        """根据ID获取角色"""
        return self._get_db_session().query(CharacterModel).filter(CharacterModel.id == id).first()
    
    def load_character_from_file(self, file_path: str) -> Optional[CharacterModel]:
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
            
            character = self.get_character_by_name(data['name'])
            if character:
                print(f"从数据库加载角色卡: {character.name}")
                return character
            data["data"]["first_mes"] = char_turn_process(data["data"]["first_mes"])
            data["data"]["description"] = content_char_turn_process(data["data"]["description"])
            character_id = self.create_character(data)
            character = self.get_character_by_id(character_id)
            print(f"成功加载角色卡到数据库: {character.name} (ID: {character_id})")
            return character
        except FileNotFoundError:
            print(f"错误: 角色卡文件未找到 {file_path}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            print(f"错误: 解析角色卡文件失败 {file_path}: {e}")
            return None
