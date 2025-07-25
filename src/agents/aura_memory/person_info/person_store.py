import json
from loguru import logger
from datetime import datetime
from typing import List, Optional, Dict, Type, Union, Any
from sqlalchemy import create_engine, Column, String, Integer, JSON, ForeignKey, BigInteger, Index, Boolean, update, Float, Text
from sqlalchemy.dialects.postgresql import JSONB
from pydantic import BaseModel
from ..database.database import Database, Base
from utils.utils import performance_point_context
from configuration.config import get_db_conn_string


class PersonInfoModel(Base):
    """用户信息数据库模型"""
    __tablename__ = 'person_info'
    
    # 主键
    person_id = Column(String, primary_key=True)  # 用户唯一ID（MD5哈希）
    
    # 基础信息
    person_name = Column(String, nullable=True)  # 用户昵称
    name_reason = Column(Text, nullable=True)  # 取名理由
    platform = Column(String, nullable=False, default="unknown")  # 平台
    user_id = Column(String, nullable=False, default="unknown")  # 平台用户ID
    nickname = Column(String, nullable=True)  # 用户昵称
    
    # 关系信息
    know_times = Column(Integer, nullable=False, default=0)  # 认识次数
    know_since = Column(BigInteger, nullable=True)  # 首次认识时间
    last_know = Column(BigInteger, nullable=True)  # 最后认识时间
    
    # 印象信息
    impression = Column(Text, nullable=True)  # 印象
    short_impression = Column(Text, nullable=True)  # 简短印象
    
    # 知识信息（JSON格式）
    info_list = Column(JSONB, nullable=True)  # 信息列表
    points = Column(JSONB, nullable=True)  # 要点
    forgotten_points = Column(JSONB, nullable=True)  # 遗忘的要点
    
    # 关系值
    relation_value = Column(Float, nullable=True)  # 关系值
    attitude = Column(Integer, nullable=False, default=50)  # 态度值（0-100）
    
    # 索引
    __table_args__ = (
        Index('idx_person_info_platform', 'platform'),
        Index('idx_person_info_user_id', 'user_id'),
        Index('idx_person_info_person_name', 'person_name'),
        Index('idx_person_info_know_times', 'know_times'),
        Index('idx_person_info_last_know', 'last_know'),
        Index('idx_person_info_attitude', 'attitude'),
    )

class PersonInfo(BaseModel):
    """基础用户信息模型"""
    person_id: str
    person_name: Optional[str] = None
    name_reason: Optional[str] = None
    platform: str = "unknown"
    user_id: str = "unknown"
    nickname: Optional[str] = None
    know_times: int = 0
    know_since: Optional[int] = None
    last_know: Optional[int] = None
    impression: Optional[str] = None
    short_impression: Optional[str] = None
    info_list: Optional[list] = None
    points: Optional[list] = None
    forgotten_points: Optional[list] = None
    relation_value: Optional[float] = None
    attitude: int = 50

class PersonStore:
    instance = None
    def __init__(self):
        with performance_point_context("初始化用户信息存储"):
            self.db = Database(get_db_conn_string())
    
    @classmethod
    def get_instance(cls):
        if cls.instance is None:
            cls.instance = cls()
        return cls.instance
    
    def add_person(self, person: PersonInfo) -> bool:
        """添加用户信息"""
        session = self.db.get_db()
        try:
            # 处理JSON字段
            info_list = json.dumps(person.info_list, ensure_ascii=False) if person.info_list else None
            points = json.dumps(person.points, ensure_ascii=False) if person.points else None
            forgotten_points = json.dumps(person.forgotten_points, ensure_ascii=False) if person.forgotten_points else None
            
            db_person = PersonInfoModel(
                person_id=person.person_id,
                person_name=person.person_name,
                name_reason=person.name_reason,
                platform=person.platform,
                user_id=person.user_id,
                nickname=person.nickname,
                know_times=person.know_times,
                know_since=person.know_since,
                last_know=person.last_know,
                impression=person.impression,
                short_impression=person.short_impression,
                info_list=info_list,
                points=points,
                forgotten_points=forgotten_points,
                relation_value=person.relation_value,
                attitude=person.attitude
            )
            session.add(db_person)
            session.commit()
            logger.info(f"添加用户信息成功: {person.person_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"添加用户信息失败: {str(e)}")
            return False
        finally:
            session.close()

    def get_person_by_id(self, person_id: str) -> Optional[PersonInfo]:
        """根据person_id获取用户信息"""
        session = self.db.get_db()
        try:
            db_person = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_id == person_id
            ).first()
            
            if db_person:
                # 解析JSON字段
                info_list = json.loads(db_person.info_list) if db_person.info_list else None
                points = json.loads(db_person.points) if db_person.points else None
                forgotten_points = json.loads(db_person.forgotten_points) if db_person.forgotten_points else None
                
                return PersonInfo(
                    person_id=db_person.person_id,
                    person_name=db_person.person_name,
                    name_reason=db_person.name_reason,
                    platform=db_person.platform,
                    user_id=db_person.user_id,
                    nickname=db_person.nickname,
                    know_times=db_person.know_times,
                    know_since=db_person.know_since,
                    last_know=db_person.last_know,
                    impression=db_person.impression,
                    short_impression=db_person.short_impression,
                    info_list=info_list,
                    points=points,
                    forgotten_points=forgotten_points,
                    relation_value=db_person.relation_value,
                    attitude=db_person.attitude
                )
            return None
        except Exception as e:
            logger.error(f"获取用户信息失败: {str(e)}")
            return None
        finally:
            session.close()

    def get_person_by_name(self, person_name: str) -> Optional[PersonInfo]:
        """根据person_name获取用户信息"""
        session = self.db.get_db()
        try:
            db_person = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_name == person_name
            ).first()
            
            if db_person:
                # 解析JSON字段
                info_list = json.loads(db_person.info_list) if db_person.info_list else None
                points = json.loads(db_person.points) if db_person.points else None
                forgotten_points = json.loads(db_person.forgotten_points) if db_person.forgotten_points else None
                
                return PersonInfo(
                    person_id=db_person.person_id,
                    person_name=db_person.person_name,
                    name_reason=db_person.name_reason,
                    platform=db_person.platform,
                    user_id=db_person.user_id,
                    nickname=db_person.nickname,
                    know_times=db_person.know_times,
                    know_since=db_person.know_since,
                    last_know=db_person.last_know,
                    impression=db_person.impression,
                    short_impression=db_person.short_impression,
                    info_list=info_list,
                    points=points,
                    forgotten_points=forgotten_points,
                    relation_value=db_person.relation_value,
                    attitude=db_person.attitude
                )
            return None
        except Exception as e:
            logger.error(f"根据名称获取用户信息失败: {str(e)}")
            return None
        finally:
            session.close()

    def update_person(self, person: PersonInfo) -> bool:
        """更新用户信息"""
        session = self.db.get_db()
        try:
            db_person = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_id == person.person_id
            ).first()
            
            if db_person:
                # 处理JSON字段
                info_list = json.dumps(person.info_list, ensure_ascii=False) if person.info_list else None
                points = json.dumps(person.points, ensure_ascii=False) if person.points else None
                forgotten_points = json.dumps(person.forgotten_points, ensure_ascii=False) if person.forgotten_points else None
                
                db_person.person_name = person.person_name
                db_person.name_reason = person.name_reason
                db_person.platform = person.platform
                db_person.user_id = person.user_id
                db_person.nickname = person.nickname
                db_person.know_times = person.know_times
                db_person.know_since = person.know_since
                db_person.last_know = person.last_know
                db_person.impression = person.impression
                db_person.short_impression = person.short_impression
                db_person.info_list = info_list
                db_person.points = points
                db_person.forgotten_points = forgotten_points
                db_person.relation_value = person.relation_value
                db_person.attitude = person.attitude
                
                session.commit()
                logger.info(f"更新用户信息成功: {person.person_id}")
                return True
            else:
                logger.warning(f"用户不存在，无法更新: {person.person_id}")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"更新用户信息失败: {str(e)}")
            return False
        finally:
            session.close()

    def update_person_field(self, person_id: str, field_name: str, value) -> bool:
        """更新用户信息的单个字段"""
        session = self.db.get_db()
        try:
            db_person = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_id == person_id
            ).first()
            
            if db_person:
                # 处理JSON字段的特殊情况
                if field_name in ['info_list', 'points', 'forgotten_points']:
                    if value is not None:
                        setattr(db_person, field_name, json.dumps(value, ensure_ascii=False))
                    else:
                        setattr(db_person, field_name, None)
                else:
                    setattr(db_person, field_name, value)
                
                session.commit()
                logger.debug(f"更新用户字段成功: {person_id}.{field_name}")
                return True
            else:
                logger.warning(f"用户不存在，无法更新字段: {person_id}.{field_name}")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"更新用户字段失败: {person_id}.{field_name}, 错误: {str(e)}")
            return False
        finally:
            session.close()

    def delete_person(self, person_id: str) -> bool:
        """删除用户信息"""
        session = self.db.get_db()
        try:
            db_person = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_id == person_id
            ).first()
            
            if db_person:
                session.delete(db_person)
                session.commit()
                logger.info(f"删除用户信息成功: {person_id}")
                return True
            else:
                logger.warning(f"用户不存在，无法删除: {person_id}")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"删除用户信息失败: {str(e)}")
            return False
        finally:
            session.close()

    def get_all_persons(self, limit: int = 100) -> List[PersonInfo]:
        """获取所有用户信息"""
        session = self.db.get_db()
        try:
            db_persons = session.query(PersonInfoModel).limit(limit).all()
            
            persons = []
            for db_person in db_persons:
                # 解析JSON字段
                info_list = json.loads(db_person.info_list) if db_person.info_list else None
                points = json.loads(db_person.points) if db_person.points else None
                forgotten_points = json.loads(db_person.forgotten_points) if db_person.forgotten_points else None
                
                person = PersonInfo(
                    person_id=db_person.person_id,
                    person_name=db_person.person_name,
                    name_reason=db_person.name_reason,
                    platform=db_person.platform,
                    user_id=db_person.user_id,
                    nickname=db_person.nickname,
                    know_times=db_person.know_times,
                    know_since=db_person.know_since,
                    last_know=db_person.last_know,
                    impression=db_person.impression,
                    short_impression=db_person.short_impression,
                    info_list=info_list,
                    points=points,
                    forgotten_points=forgotten_points,
                    relation_value=db_person.relation_value,
                    attitude=db_person.attitude
                )
                persons.append(person)
            
            return persons
        except Exception as e:
            logger.error(f"获取所有用户信息失败: {str(e)}")
            return []
        finally:
            session.close()

    def get_persons_by_platform(self, platform: str, limit: int = 100) -> List[PersonInfo]:
        """根据平台获取用户信息"""
        session = self.db.get_db()
        try:
            db_persons = session.query(PersonInfoModel).filter(
                PersonInfoModel.platform == platform
            ).limit(limit).all()
            
            persons = []
            for db_person in db_persons:
                # 解析JSON字段
                info_list = json.loads(db_person.info_list) if db_person.info_list else None
                points = json.loads(db_person.points) if db_person.points else None
                forgotten_points = json.loads(db_person.forgotten_points) if db_person.forgotten_points else None
                
                person = PersonInfo(
                    person_id=db_person.person_id,
                    person_name=db_person.person_name,
                    name_reason=db_person.name_reason,
                    platform=db_person.platform,
                    user_id=db_person.user_id,
                    nickname=db_person.nickname,
                    know_times=db_person.know_times,
                    know_since=db_person.know_since,
                    last_know=db_person.last_know,
                    impression=db_person.impression,
                    short_impression=db_person.short_impression,
                    info_list=info_list,
                    points=points,
                    forgotten_points=forgotten_points,
                    relation_value=db_person.relation_value,
                    attitude=db_person.attitude
                )
                persons.append(person)
            
            return persons
        except Exception as e:
            logger.error(f"根据平台获取用户信息失败: {str(e)}")
            return []
        finally:
            session.close()

    def batch_update_person_fields(self, updates: List[tuple]) -> Dict[str, bool]:
        """批量更新用户字段
        updates: List[tuple] - [(person_id, field_name, value), ...]
        returns: Dict[str, bool] - {person_id: success}
        """
        session = self.db.get_db()
        results = {}
        
        try:
            for person_id, field_name, value in updates:
                try:
                    db_person = session.query(PersonInfoModel).filter(
                        PersonInfoModel.person_id == person_id
                    ).first()
                    
                    if db_person:
                        # 处理JSON字段的特殊情况
                        if field_name in ['info_list', 'points', 'forgotten_points']:
                            if value is not None:
                                setattr(db_person, field_name, json.dumps(value, ensure_ascii=False))
                            else:
                                setattr(db_person, field_name, None)
                        else:
                            setattr(db_person, field_name, value)
                        
                        results[person_id] = True
                    else:
                        results[person_id] = False
                        logger.warning(f"用户不存在，无法更新字段: {person_id}.{field_name}")
                        
                except Exception as e:
                    results[person_id] = False
                    logger.error(f"更新用户字段失败: {person_id}.{field_name}, 错误: {str(e)}")
            
            session.commit()
            logger.debug(f"批量更新完成，成功: {sum(results.values())}/{len(updates)}")
            return results
            
        except Exception as e:
            session.rollback()
            logger.error(f"批量更新失败: {str(e)}")
            return {person_id: False for person_id, _, _ in updates}
        finally:
            session.close()

    def get_persons_by_ids(self, person_ids: List[str]) -> List[PersonInfo]:
        """根据person_id列表批量获取用户信息"""
        session = self.db.get_db()
        try:
            db_persons = session.query(PersonInfoModel).filter(
                PersonInfoModel.person_id.in_(person_ids)
            ).all()
            
            persons = []
            for db_person in db_persons:
                # 解析JSON字段
                info_list = json.loads(db_person.info_list) if db_person.info_list else None
                points = json.loads(db_person.points) if db_person.points else None
                forgotten_points = json.loads(db_person.forgotten_points) if db_person.forgotten_points else None
                
                person = PersonInfo(
                    person_id=db_person.person_id,
                    person_name=db_person.person_name,
                    name_reason=db_person.name_reason,
                    platform=db_person.platform,
                    user_id=db_person.user_id,
                    nickname=db_person.nickname,
                    know_times=db_person.know_times,
                    know_since=db_person.know_since,
                    last_know=db_person.last_know,
                    impression=db_person.impression,
                    short_impression=db_person.short_impression,
                    info_list=info_list,
                    points=points,
                    forgotten_points=forgotten_points,
                    relation_value=db_person.relation_value,
                    attitude=db_person.attitude
                )
                persons.append(person)
            
            return persons
        except Exception as e:
            logger.error(f"批量获取用户信息失败: {str(e)}")
            return []
        finally:
            session.close() 