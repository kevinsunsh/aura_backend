import logging
from datetime import datetime
from typing import List, Optional, Dict, Type, Union, Any
from sqlalchemy import create_engine, Column, String, Integer, JSON, ForeignKey, BigInteger, Index, Boolean, update, Float
from sqlalchemy.dialects.postgresql import JSONB
from pydantic import BaseModel
from .database.database import Database, Base
from utils.utils import performance_point_context
from configuration.config import get_db_conn_string
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
    def __init__(self):
        with performance_point_context("初始化消息存储"):
            self.db = Database(get_db_conn_string())
    
    @classmethod
    def get_instance(cls):
        if cls.instance is None:
            cls.instance = cls()
        return cls.instance
    
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
            logger.debug(f"添加消息成功: {message.content}")
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

    def get_recent_messages(self, user_id: Optional[str] = None, limit: int = 10) -> List[Message]:
        """获取最近的N条消息记录，可选择指定用户"""
        session = self.db.get_db()
        try:
            query = session.query(MessageModel)
            
            # 如果提供了user_id，则按用户过滤
            if user_id:
                query = query.filter(MessageModel.user_id == user_id)
            
            db_messages = query.order_by(MessageModel.created_at.desc()).limit(limit).all()
            
            # 按时间正序返回
            messages = [Message(
                msg_id=m.msg_id,
                chat_id=m.chat_id,
                user_id=m.user_id,
                platform=m.platform,
                m_type=m.m_type,
                content=m.content,
                data=m.data,
                created_at=m.created_at
            ) for m in db_messages]
            
            # 反转列表以保持时间正序
            messages.reverse()
            return messages
        except Exception as e:
            user_filter = f"用户 {user_id}" if user_id else "所有用户"
            logger.error(f"获取{user_filter}最近 {limit} 条消息失败: {str(e)}")
            return []
        finally:
            session.close()

    def get_messages_in_recent_time(self, milliseconds: int, user_id: Optional[str] = None, chat_id: Optional[str] = None) -> List[Message]:
        """获取最近指定秒数内的所有消息，可选择指定用户"""
        session = self.db.get_db()
        try:
            # 计算时间范围（转换为毫秒）
            current_time =int(datetime.now().timestamp() * 1000)
            start_time = current_time - milliseconds
            
            query = session.query(MessageModel).filter(
                MessageModel.created_at >= start_time,
                MessageModel.created_at <= current_time
            )
            
            # 如果提供了user_id，则按用户过滤
            if user_id:
                query = query.filter(MessageModel.user_id == user_id)
            
            # 如果提供了chat_id，则按聊天ID过滤
            if chat_id:
                query = query.filter(MessageModel.chat_id == chat_id)
            
            db_messages = query.order_by(MessageModel.created_at).all()
            
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
            user_filter = f"用户 {user_id}" if user_id else "所有用户"
            logger.error(f"获取{user_filter}最近 {seconds} 秒内消息失败: {str(e)}")
            return []
        finally:
            session.close()

    def get_messages_by_timestamp_range(self, chat_id: str, start_time: int, end_time: int, limit: int = 100, limit_mode: str = "latest") -> List[dict]:
        """获取指定聊天流在时间区间内的消息（不包含边界）
        
        Args:
            chat_id: 聊天ID
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            limit: 限制返回的消息数量
            limit_mode: 限制模式，"latest"表示最新的消息，"earliest"表示最早的消息
        """
        session = self.db.get_db()
        try:
            query = session.query(MessageModel).filter(
                MessageModel.chat_id == chat_id,
                MessageModel.created_at > start_time,
                MessageModel.created_at < end_time
            )
            
            if limit_mode == "latest":
                query = query.order_by(MessageModel.created_at.desc()).limit(limit)
            else:
                query = query.order_by(MessageModel.created_at).limit(limit)
            
            db_messages = query.all()
            
            # 转换为字典格式，保持与原代码兼容
            messages = []
            for m in db_messages:
                message_dict = {
                    "msg_id": m.msg_id,
                    "chat_id": m.chat_id,
                    "user_id": m.user_id,
                    "platform": m.platform,
                    "m_type": m.m_type,
                    "content": m.content,
                    "data": m.data,
                    "created_at": m.created_at,
                    "time": m.created_at,  # 兼容原代码
                    "user_platform": m.platform,  # 兼容原代码
                    "chat_info_platform": m.platform,  # 兼容原代码
                }
                messages.append(message_dict)
            
            # 如果是最新消息模式，需要反转顺序
            if limit_mode == "latest":
                messages.reverse()
            
            return messages
        except Exception as e:
            logger.error(f"获取聊天流 {chat_id} 时间区间消息失败: {str(e)}")
            return []
        finally:
            session.close()

    def get_messages_by_timestamp_range_inclusive(self, chat_id: str, start_time: int, end_time: int, limit: int = 100) -> List[dict]:
        """获取指定聊天流在时间区间内的消息（包含边界）"""
        session = self.db.get_db()
        try:
            db_messages = session.query(MessageModel).filter(
                MessageModel.chat_id == chat_id,
                MessageModel.created_at >= start_time,
                MessageModel.created_at <= end_time
            ).order_by(MessageModel.created_at).limit(limit).all()
            
            # 转换为字典格式，保持与原代码兼容
            messages = []
            for m in db_messages:
                message_dict = {
                    "msg_id": m.msg_id,
                    "chat_id": m.chat_id,
                    "user_id": m.user_id,
                    "platform": m.platform,
                    "m_type": m.m_type,
                    "content": m.content,
                    "data": m.data,
                    "created_at": m.created_at,
                    "time": m.created_at,  # 兼容原代码
                    "user_platform": m.platform,  # 兼容原代码
                    "chat_info_platform": m.platform,  # 兼容原代码
                }
                messages.append(message_dict)
            
            return messages
        except Exception as e:
            logger.error(f"获取聊天流 {chat_id} 时间区间消息失败: {str(e)}")
            return []
        finally:
            session.close()

    def get_messages_before_timestamp(self, chat_id: str, timestamp: int, limit: int = 100) -> List[dict]:
        """获取指定时间戳之前的消息"""
        session = self.db.get_db()
        try:
            db_messages = session.query(MessageModel).filter(
                MessageModel.chat_id == chat_id,
                MessageModel.created_at < timestamp
            ).order_by(MessageModel.created_at.desc()).limit(limit).all()
            
            # 转换为字典格式，保持与原代码兼容
            messages = []
            for m in db_messages:
                message_dict = {
                    "msg_id": m.msg_id,
                    "chat_id": m.chat_id,
                    "user_id": m.user_id,
                    "platform": m.platform,
                    "m_type": m.m_type,
                    "content": m.content,
                    "data": m.data,
                    "created_at": m.created_at,
                    "time": m.created_at,  # 兼容原代码
                    "user_platform": m.platform,  # 兼容原代码
                    "chat_info_platform": m.platform,  # 兼容原代码
                }
                messages.append(message_dict)
            
            # 反转顺序以保持时间正序
            messages.reverse()
            return messages
        except Exception as e:
            logger.error(f"获取聊天流 {chat_id} 时间戳前消息失败: {str(e)}")
            return []
        finally:
            session.close()

    def count_messages_since(self, chat_id: str, start_time: int, end_time: int) -> int:
        """计算指定时间区间内的消息数量（不包含边界）"""
        session = self.db.get_db()
        try:
            count = session.query(MessageModel).filter(
                MessageModel.chat_id == chat_id,
                MessageModel.created_at > start_time,
                MessageModel.created_at < end_time
            ).count()
            return count
        except Exception as e:
            logger.error(f"计算聊天流 {chat_id} 消息数量失败: {str(e)}")
            return 0
        finally:
            session.close()
