import logging
import time
import threading
from datetime import datetime
from typing import List, Optional, Dict, Type, Union, Any
from sqlalchemy import create_engine, Column, String, Integer, JSON, ForeignKey, BigInteger, Index, Boolean, update, Float
from sqlalchemy.dialects.postgresql import JSONB
from pydantic import BaseModel
from .database.database import Database, Base
from utils.utils import performance_point_context

logger = logging.getLogger(__name__)

class MessageModel(Base):
    """消息数据库模型 - 第一层：原始消息"""
    __tablename__ = 'messages'
    msg_id = Column(String, primary_key=True)
    chat_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    m_type = Column(String, nullable=False)
    content = Column(String, nullable=False)
    data = Column(JSONB, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    
    # 更新索引
    __table_args__ = (
        Index('idx_messages_created_at', 'created_at'),
        Index('idx_messages_chat_id', 'chat_id'),
        Index('idx_messages_user_id', 'user_id'),
        Index('idx_messages_platform', 'platform'),
    )

class Message(BaseModel):
    """基础消息模型"""
    msg_id: str
    chat_id: str
    user_id: str
    platform: str
    m_type: str
    content: str
    data: dict
    created_at: int

class MessageStore:
    instance = None
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance
    
    def __init__(self, db_conn_string: str = None):
        with performance_point_context("初始化消息存储"):
            self.db = Database(db_conn_string)
            # self.db.initialize_database()

    def add_message(self, message: Message) -> bool:
        """添加消息到第一层"""
        session = self.db.get_db()
        try:
            db_message = MessageModel(
                msg_id=message.msg_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                platform=message.platform,
                m_type=message.m_type,
                content=message.content,
                data=message.data,
                created_at=message.created_at
            )
            session.add(db_message)
            session.commit()
            logger.info(f"添加消息成功: {message.msg_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"添加消息失败: {str(e)}")
            return False
        finally:
            session.close()

    def get_messages_by_time_range(self, chat_id: str, start_time: int, end_time: int, limit: int = 100) -> List[Message]:
        """获取指定聊天流在时间区间内的消息"""
        session = self.db.get_db()
        try:
            db_messages = session.query(MessageModel).filter(
                MessageModel.chat_id == chat_id,
                MessageModel.created_at >= start_time,
                MessageModel.created_at <= end_time
            ).order_by(MessageModel.created_at).limit(limit).all()
            
            return [Message(
                msg_id=m.msg_id,
                chat_id=m.chat_id,
                user_id=m.user_id,
                platform=m.platform,
                m_type=m.m_type,
                content=m.content,
                data=m.data,
                created_at=m.created_at
            ) for m in db_messages]
        except Exception as e:
            logger.error(f"获取聊天流 {chat_id} 时间区间直接消息失败: {str(e)}")
            return []
        finally:
            session.close()
