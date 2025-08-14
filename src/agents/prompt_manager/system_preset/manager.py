import os
import json
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session
from .models import PromptModel, PromptOrderModel, SystemPresetModel
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
    
    def create_system_preset(self, system_preset_name: str, system_preset_data: dict) -> str:
        """创建系统预设"""
        system_preset_id = str(uuid.uuid4())
        
        # 创建主角色记录
        system_preset = SystemPresetModel(
            id=system_preset_id,
            name=system_preset_name,
        )
        self._get_db_session().add(system_preset)
        self._get_db_session().flush()  # 获取system_preset.id
        
        # 如果有data字段，处理详细信息
        prompts = system_preset_data.get('prompts', {})
        for prompt in prompts:
            self._create_prompt(system_preset_id, prompt)
        prompt_orders = system_preset_data.get('prompt_order', {})
        for prompt_order in prompt_orders:
            self._create_prompt_order(system_preset_id, prompt_order)
        self._get_db_session().add(system_preset)
        self._get_db_session().commit()
        return system_preset_name
    
    def _create_prompt(self, system_preset_id: str, prompt_data: dict):
        """创建提示"""
        prompt = PromptModel(
            system_preset_id=system_preset_id,
            identifier=prompt_data.get('identifier', ''),
            name=prompt_data.get('name', ''),
            role=prompt_data.get('role', 'system'),
            system_prompt=prompt_data.get('system_prompt', True),
            enabled=prompt_data.get('enabled', True),
            marker=prompt_data.get('marker', False),
            content=prompt_data.get('content', ''),
            injection_position=prompt_data.get('injection_position', 0),
            injection_depth=prompt_data.get('injection_depth', 4),
            forbid_overrides=prompt_data.get('forbid_overrides', False),
        )
        self._get_db_session().add(prompt)
    
    def _create_prompt_order(self, system_preset_id: str, prompt_order_data: dict):
        """创建提示顺序"""
        prompt_order = PromptOrderModel(
            system_preset_id=system_preset_id,
            character_id=prompt_order_data.get('character_id', 0),
            order=prompt_order_data.get('order', []),
        )
        self._get_db_session().add(prompt_order)
    
    def get_system_preset_by_name(self, name: str) -> Optional[SystemPresetModel]:
        """根据名称获取系统预设"""
        return self._get_db_session().query(SystemPresetModel).filter(SystemPresetModel.name == name).first()
    
    def load_system_preset_from_file(self, file_path: str) -> Optional[SystemPresetModel]:
        """
        从文件加载系统预设
        
        Args:
            file_path (str): 角色卡文件路径
            
        Returns:
            Optional[SystemPreset]: 加载的系统预设，如果失败返回None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 使用DAO创建角色到数据库并返回
            if self._get_db_session() is None:
                print("错误: 无法创建数据库连接")
                return None
            system_preset_name = os.path.basename(file_path).replace('.json', '')
            system_preset = self.get_system_preset_by_name(system_preset_name)
            if system_preset:
                print(f"从数据库加载系统预设: {system_preset.id}")
                return system_preset
            
            system_preset_name = self.create_system_preset(system_preset_name, data)
            system_preset = self.get_system_preset_by_name(system_preset_name)
            print(f"成功加载系统预设到数据库: {system_preset.id} (ID: {system_preset_name})")
            return system_preset
        except FileNotFoundError:
            print(f"错误: 角色卡文件未找到 {file_path}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            print(f"错误: 解析角色卡文件失败 {file_path}: {e}")
            return None
    
    def get_system_preset_by_name(self, name: str) -> Optional[SystemPresetModel]:
        """根据名称获取系统预设"""
        from sqlalchemy.orm import joinedload
        return self._get_db_session().query(SystemPresetModel)\
            .options(joinedload(SystemPresetModel.prompts), joinedload(SystemPresetModel.prompt_orders))\
            .filter(SystemPresetModel.name == name).first()
    
    def list_system_presets(self) -> List[SystemPresetModel]:
        """列出所有系统预设"""
        return self._get_db_session().query(SystemPresetModel).all()
    
    def list_all_activated_prompts(self, system_preset_id: str) -> List[PromptModel]:
        return self._get_db_session().query(PromptModel).filter(PromptModel.system_preset_id == system_preset_id, PromptModel.enabled == True).all()
    
    def list_all_activated_prompt_orders(self, system_preset_id: str, character_id: int) -> List[PromptOrderModel]:
        return self._get_db_session().query(PromptOrderModel).filter(PromptOrderModel.system_preset_id == system_preset_id, PromptOrderModel.character_id == character_id).all()
