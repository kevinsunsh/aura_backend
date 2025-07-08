from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Boolean,
    Text,
    Float, 
    DateTime,
    Double,
    UniqueConstraint,
    Index,
    BigInteger
)
from .database.database import Base, Database
import threading
import logging
import time
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from utils.utils import performance_point_context

logger = logging.getLogger(__name__)

class ChatStreamModel(Base):
    """聊天流数据库模型"""
    __tablename__ = 'chat_streams'

    chat_id = Column(String, primary_key=True)
    chatstream_checked_at = Column(BigInteger, nullable=False)  # 预处理器检查时间
    created_at = Column(BigInteger, nullable=False)
    chatstream_locked = Column(Boolean, nullable=False, default=False)  # 处理器锁
    chatstream_heartbeat = Column(BigInteger, nullable=False, default=0)  # 处理器心跳

    # 索引
    __table_args__ = (
        Index('idx_chat_streams_chatstream_checked_at', 'chatstream_checked_at'),
        Index('idx_chat_streams_created_at', 'created_at'),
    )

class ChatStream(BaseModel):
    """ChatStream模型"""
    chat_id: str
    chatstream_checked_at: int  # 预处理器检查时间
    created_at: int
    chatstream_locked: bool       # 预处理器锁
    chatstream_heartbeat: int  # 处理器心跳

class ChatStreamManager:
    instance = None
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance
    
    def __init__(self, db_conn_string: str = None):
        with performance_point_context("初始化聊天流管理器"):
            self.db = Database(db_conn_string)
            # self.db.initialize_database()

            # 心跳相关属性
            self.current_locked_chat_id = None  # 当前进程持有的处理器锁（最多一个）
            self.heartbeat_interval = 2  # 心跳间隔（秒）
            self.heartbeat_running = True
            
            # 锁相关配置
            self.retry_interval = 0.1  # 重试间隔（秒）
            self.heartbeat_timeout = 60  # 心跳超时（秒）
            
            # 启动心跳线程
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
            self.heartbeat_thread.start()
            
            logger.info("ChatStreamManager初始化完成，心跳线程已启动")

    def _heartbeat_worker(self):
        """心跳工作线程"""
        while self.heartbeat_running:
            try:
                # 更新当前进程持有的处理器锁的心跳
                if self.current_locked_chat_id:
                    if not self.update_lock_heartbeat(self.current_locked_chat_id):
                        # 如果更新失败，清除锁持有
                        logger.warning(f"处理器锁心跳更新失败，清除锁持有: {self.current_locked_chat_id}")
                        self.current_locked_chat_id = None

                time.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"心跳工作线程异常: {str(e)}")
                time.sleep(self.heartbeat_interval)

    def _set_locked_chat(self, chat_id: str):
        """设置当前处理器锁持有者"""
        self.current_locked_chat_id = chat_id
        logger.debug(f"设置处理器锁持有者: {chat_id}")

    def _clear_locked_chat(self):
        """清除当前处理器锁持有者"""
        self.current_locked_chat_id = None
        logger.debug("清除处理器锁持有者")

    def _set_preprocessor_locked_chat(self, chat_id: str):
        """设置当前预处理器锁持有者"""
        self.current_preprocessor_locked_chat_id = chat_id
        logger.debug(f"设置预处理器锁持有者: {chat_id}")

    def _clear_preprocessor_locked_chat(self):
        """清除当前预处理器锁持有者"""
        self.current_preprocessor_locked_chat_id = None
        logger.debug("清除预处理器锁持有者")

    def stop_heartbeat(self):
        """停止心跳线程"""
        self.heartbeat_running = False
        if self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=5)
        logger.info("心跳线程已停止")

    def get_current_locked_chat(self) -> Optional[str]:
        """获取当前进程持有的锁"""
        return self.current_locked_chat_id

    def is_holding_lock(self, chat_id: str) -> bool:
        """检查当前进程是否持有指定聊天流的锁"""
        return self.current_locked_chat_id == chat_id

    def is_holding_any_lock(self) -> bool:
        """检查当前进程是否持有任何锁"""
        return self.current_locked_chat_id is not None

    def set_heartbeat_interval(self, interval_seconds: float):
        """设置心跳间隔（秒）"""
        self.heartbeat_interval = interval_seconds
        logger.info(f"心跳间隔已设置为 {interval_seconds} 秒")

    def get_heartbeat_interval(self) -> float:
        """获取当前心跳间隔（秒）"""
        return self.heartbeat_interval

    def __del__(self):
        """析构方法，确保程序退出时停止心跳线程"""
        try:
            self.stop_heartbeat()
        except:
            pass  # 忽略析构时的异常
    
    def update_lock_heartbeat(self, chat_id: str) -> bool:
        """更新锁心跳（处理器/预处理器）- 使用psycopg直接SQL优化性能"""
        try:
            with self.db.get_session() as session:
                result = session.execute(
                    text("""
                        UPDATE chat_streams 
                        SET chatstream_heartbeat = :heartbeat
                        WHERE chat_id = :chat_id AND chatstream_locked = TRUE
                    """),
                    {
                        "chat_id": chat_id,
                        "heartbeat": int(datetime.now().timestamp() * 1000)
                    }
                )
                
                if result.rowcount > 0:
                    logger.debug(f"更新处理器锁心跳成功: {chat_id}")
                    return True
                else:
                    logger.warning(f"处理器锁不存在或未被锁定，无法更新心跳: {chat_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"更新处理器锁心跳失败: {str(e)}")
            return False
    
    def update_chat_stream_checked_at(self, chat_id: str) -> bool:
        """更新聊天流的预处理器检查时间为当前时间 - 使用psycopg直接SQL优化性能"""
        try:
            with self.db.get_session() as session:
                result = session.execute(
                    text("""
                        UPDATE chat_streams 
                        SET chatstream_checked_at = :checked_at
                        WHERE chat_id = :chat_id
                    """),
                    {
                        "chat_id": chat_id,
                        "checked_at": int(datetime.now().timestamp() * 1000)
                    }
                )
                
                if result.rowcount > 0:
                    logger.info(f"更新聊天流 {chat_id} 预处理器检查时间成功")
                    return True
                else:
                    logger.warning(f"聊天流不存在，无法更新预处理器检查时间: {chat_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"更新聊天流预处理器检查时间失败: {str(e)}")
            return False
    
    def get_or_create_chat_stream(self, chat_id: str) -> Optional[ChatStream]:
        """获取或创建聊天流（并发安全，使用psycopg直接SQL优化性能）"""
        try:
            # 使用psycopg直接执行SQL，避免SQLAlchemy ORM开销
            with self.db.get_session() as session:
                # 首先尝试获取现有记录
                result = session.execute(
                    text("""
                        SELECT chat_id, chatstream_checked_at, created_at, 
                               chatstream_heartbeat, chatstream_locked
                        FROM chat_streams 
                        WHERE chat_id = :chat_id
                    """),
                    {"chat_id": chat_id}
                ).fetchone()
                
                if result:
                    # logger.info(f"获取聊天流成功: {chat_id}")
                    return ChatStream(
                        chat_id=result.chat_id,
                        chatstream_checked_at=result.chatstream_checked_at,
                        created_at=result.created_at,
                        chatstream_heartbeat=result.chatstream_heartbeat,
                        chatstream_locked=result.chatstream_locked
                    )

                # 记录不存在，使用UPSERT语法创建
                current_time = int(datetime.now().timestamp() * 1000)  # 毫秒时间戳
                
                # 使用PostgreSQL的ON CONFLICT DO NOTHING语法，只在不存在时插入
                session.execute(
                    text("""
                        INSERT INTO chat_streams 
                        (chat_id, chatstream_checked_at, created_at, chatstream_locked, chatstream_heartbeat)
                        VALUES (:chat_id, :checked_at, :created_at, :locked, :heartbeat)
                        ON CONFLICT (chat_id) DO NOTHING
                    """),
                    {
                        "chat_id": chat_id,
                        "checked_at": current_time,
                        "created_at": current_time,
                        "locked": False,
                        "heartbeat": current_time
                    }
                )
                
                logger.info(f"创建聊天流成功: {chat_id}")
                return ChatStream(
                    chat_id=chat_id,
                    chatstream_checked_at=current_time,
                    created_at=current_time,
                    chatstream_heartbeat=current_time,
                    chatstream_locked=False
                )
                
        except Exception as e:
            logger.error(f"获取或创建聊天流失败: {str(e)}")
            return None

    def acquire_lock(self, chat_id: str) -> bool:
        """获取锁（处理器/预处理器）"""
        field_locked = "chatstream_locked"
        field_heartbeat = "chatstream_heartbeat"
        try:
            current_locked_id = self.current_locked_chat_id
            if current_locked_id is not None:
                if current_locked_id == chat_id:
                    logger.debug(f"处理器锁已由当前进程持有: {chat_id}")
                    return True
                else:
                    logger.warning(f"处理器锁被其他进程持有: {current_locked_id}")
                    return False
            with self.db.get_session() as session:
                result = session.execute(
                    text(f"""
                        SELECT {field_locked}, {field_heartbeat} 
                        FROM chat_streams 
                        WHERE chat_id = :chat_id
                    """),
                    {"chat_id": chat_id}
                ).fetchone()
                if not result:
                    logger.warning(f"聊天流不存在: {chat_id}")
                    return False
                locked, heartbeat = result
                current_time = int(datetime.now().timestamp() * 1000)
                if locked:
                    if current_time - heartbeat > self.heartbeat_timeout:
                        logger.info(f"处理器锁已超时，强制获取: {chat_id}")
                    else:
                        logger.warning(f"处理器锁被其他进程持有且未超时: {chat_id}")
                        return False
                session.execute(
                    text(f"""
                        UPDATE chat_streams 
                        SET {field_locked} = TRUE, {field_heartbeat} = :heartbeat
                        WHERE chat_id = :chat_id
                    """),
                    {"chat_id": chat_id, "heartbeat": current_time}
                )
                self._set_locked_chat(chat_id)
                logger.info(f"成功获取处理器锁: {chat_id}")
                return True
        except Exception as e:
            logger.error(f"获取处理器锁失败: {e}")
            return False

    def release_lock(self, chat_id: str) -> bool:
        """释放锁（处理器/预处理器）"""
        current_locked_id = self.current_locked_chat_id
        field_locked = "chatstream_locked"
        field_heartbeat = "chatstream_heartbeat"
        try:
            if current_locked_id != chat_id:
                logger.warning(f"尝试释放不属于当前进程的处理器锁: {chat_id}")
                return False
            with self.db.get_session() as session:
                session.execute(
                    text(f"""
                        UPDATE chat_streams 
                        SET {field_locked} = FALSE, {field_heartbeat} = 0
                        WHERE chat_id = :chat_id
                    """),
                    {"chat_id": chat_id}
                )
                self._clear_locked_chat()
                logger.info(f"成功释放处理器锁: {chat_id}")
                return True
        except Exception as e:
            logger.error(f"释放处理器锁失败: {e}")
            return False

    def check_lock(self, chat_id: str) -> bool:
        """检查锁状态（处理器/预处理器）"""
        field_locked = "chatstream_locked"
        field_heartbeat = "chatstream_heartbeat"
        try:
            with self.db.get_session() as session:
                result = session.execute(
                    text(f"""
                        SELECT {field_locked}, {field_heartbeat} 
                        FROM chat_streams 
                        WHERE chat_id = :chat_id
                    """),
                    {"chat_id": chat_id}
                ).fetchone()
                if not result:
                    return False
                locked, heartbeat = result
                current_time = int(datetime.now().timestamp() * 1000)
                if locked and current_time - heartbeat > self.heartbeat_timeout:
                    logger.info(f"处理器锁已超时: {chat_id}")
                    return False
                return locked
        except Exception as e:
            logger.error(f"检查处理器锁状态失败: {e}")
            return False

    def delete_chat_stream(self, chat_id: str) -> bool:
        """删除聊天流 - 使用psycopg直接SQL优化性能"""
        try:
            with self.db.get_session() as session:
                result = session.execute(
                    text("DELETE FROM chat_streams WHERE chat_id = :chat_id"),
                    {"chat_id": chat_id}
                )
                
                if result.rowcount > 0:
                    logger.info(f"删除聊天流成功: {chat_id}")
                    return True
                else:
                    logger.warning(f"聊天流不存在，无法删除: {chat_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"删除聊天流失败: {str(e)}")
            return False
