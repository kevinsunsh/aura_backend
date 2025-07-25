from sqlalchemy import create_engine, Column, String, Integer, Boolean, Text, Float, DateTime, Double, UniqueConstraint, Index, BigInteger, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import inspect
from sqlalchemy.pool import QueuePool
import os
from contextlib import contextmanager, asynccontextmanager
from loguru import logger
import asyncio
from typing import Optional, List, Dict, Any, Union
import urllib.parse
import asyncpg
import sys
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
import sys
import os
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from utils.utils import performance_point_context

# SQLAlchemy Base
Base = declarative_base()

class Database:
    """
    同步数据库连接类 - 使用psycopg3驱动
    提供高性能的同步数据库操作
    """
    instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化数据库连接，使用psycopg3驱动优化性能
        
        Args:
            db_conn_string: 数据库连接字符串，例如 postgresql://user:password@localhost:5432/dbname
        """
        with performance_point_context("初始化数据库连接"):
            if not db_conn_string:
                raise ValueError("数据库连接字符串不能为空")
            
            # 解析连接字符串，确保使用psycopg3驱动
            parsed = urllib.parse.urlparse(db_conn_string)
            if parsed.scheme == 'postgresql':
                # 强制使用psycopg3驱动
                db_conn_string = db_conn_string.replace('postgresql://', 'postgresql+psycopg://', 1)
            
            # 优化连接池配置 - 使用psycopg3驱动
            self.engine = create_engine(
                db_conn_string,
                # 连接池配置
                poolclass=QueuePool,
                pool_size=10,  # 连接池大小
                max_overflow=20,  # 最大溢出连接数
                pool_pre_ping=True,  # 连接前ping检查
                pool_recycle=1800,  # 连接回收时间（30分钟）
                pool_timeout=30,  # 获取连接超时时间
                # 性能优化
                echo=False,  # 关闭SQL日志
                echo_pool=False,  # 关闭连接池日志
                # psycopg3特定优化
                connect_args={
                    "connect_timeout": 10,  # 连接超时
                    "application_name": "aura_backend_sync",  # 应用名称
                    "options": "-c timezone=utc -c statement_timeout=30000",  # 时区设置和语句超时
                    "sslmode": "disable",  # 禁用SSL以提高性能
                    "autocommit": False,  # 禁用自动提交
                    "row_factory": None,  # 使用默认行工厂
                    "prepare_threshold": None,  # 禁用预处理语句以避免pipeline模式警告
                }
            )
            
            self.SessionLocal = sessionmaker(
                bind=self.engine,
                expire_on_commit=False,  # 提交后不过期对象
                autoflush=False,  # 关闭自动flush
                autocommit=False  # 禁用自动提交
            )

    def get_db(self) -> Session:
        """
        获取一个新的数据库会话
        :return: SQLAlchemy Session 对象
        """
        session = self.SessionLocal()
        try:
            return session
        except Exception as e:
            session.close()
            raise e

    @contextmanager
    def get_session(self):
        """
        获取数据库会话的上下文管理器
        
        使用示例:
        with database.get_session() as session:
            # 执行数据库操作
            session.add(new_record)
            session.commit()
        """
        session = self.get_db()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            session.close()

    def create_all_tables(self):
        """
        创建所有表（如果不存在）
        """
        try:
            Base.metadata.create_all(self.engine)
        except Exception as e:
            raise ValueError(f"创建数据库表失败: {e}")

    def initialize_database(self):
        """
        检查所有定义的表是否存在，如果不存在则创建它们。
        """
        try:
            # 检查表是否存在
            inspector = inspect(self.engine)
            existing_tables = inspector.get_table_names()
            
            # 获取所有模型表名
            model_tables = [table.__tablename__ for table in Base.__subclasses__()]
            
            # 检查缺失的表
            missing_tables = [table for table in model_tables if table not in existing_tables]
            
            if missing_tables:
                self.create_all_tables()
            else:
                logger.info("所有表已存在")
            
            logger.info("数据库初始化完成")
            
        except Exception as e:
            logger.exception(f"初始化数据库时出错: {e}")
            # 如果检查失败，尝试创建表
            try:
                self.create_all_tables()
                logger.info("数据库表创建完成")
            except Exception as create_error:
                logger.error(f"创建数据库表失败: {create_error}")
                raise

    def get_connection_info(self):
        """获取连接池信息"""
        pool = self.engine.pool
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow()
        }

    def close(self):
        """关闭数据库连接"""
        if hasattr(self, 'engine'):
            self.engine.dispose()
            logger.info("数据库连接已关闭")

# 异步数据库连接类 - 使用asyncpg
class AsyncDatabase:
    """
    异步数据库连接类 - 使用asyncpg驱动
    提供高性能的异步数据库操作
    """
    instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化异步数据库连接
        
        Args:
            db_conn_string: 数据库连接字符串
        """
        if not db_conn_string:
            raise ValueError("数据库连接字符串不能为空")
        
        self.db_conn_string = db_conn_string
        self._pool = None
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def get_pool(self):
        """获取或创建连接池"""
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    # 解析连接字符串
                    parsed = urllib.parse.urlparse(self.db_conn_string)
                    
                    # 正确处理密码中的特殊字符
                    password = urllib.parse.unquote_plus(parsed.password) if parsed.password else ""
                    
                    # 构建asyncpg连接参数
                    conn_params = {
                        'host': parsed.hostname,
                        'port': parsed.port or 5432,
                        'user': parsed.username,
                        'password': password,
                        'database': parsed.path.lstrip('/'),
                        'command_timeout': 60,  # 命令超时
                        'server_settings': {
                            'application_name': 'aura_backend_async',
                            'timezone': 'utc',
                            'statement_timeout': '30000'  # 30秒语句超时
                        },
                        'ssl': False,  # 禁用SSL以提高性能
                        'setup': self._setup_connection,  # 连接设置函数
                        'prepared_statement_cache_size': 0,  # 禁用预处理语句缓存以避免pipeline模式问题
                    }
                    
                    # 解析查询参数
                    if parsed.query:
                        query_params = urllib.parse.parse_qs(parsed.query)
                        if 'connect_timeout' in query_params:
                            # asyncpg使用timeout而不是connect_timeout
                            conn_params['timeout'] = float(query_params['connect_timeout'][0])
                    
                    self._pool = await asyncpg.create_pool(
                        **conn_params,
                        min_size=5,  # 最小连接数
                        max_size=20,  # 最大连接数
                        max_inactive_connection_lifetime=1800,  # 连接回收时间
                        setup=self._setup_connection  # 连接设置函数
                    )
                    self._initialized = True
                    logger.info("异步数据库连接池已创建")
        
        return self._pool
    
    async def _setup_connection(self, connection):
        """设置连接参数"""
        await connection.set_type_codec(
            'json',
            encoder=lambda value: value,
            decoder=lambda value: value,
            schema='pg_catalog'
        )
    
    @asynccontextmanager
    async def get_connection(self):
        """
        获取数据库连接的异步上下文管理器
        
        使用示例:
        async with async_db.get_connection() as conn:
            result = await conn.fetch("SELECT * FROM table")
        """
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            try:
                yield conn
            except Exception as e:
                # 避免在pipeline模式下回滚
                try:
                    if not conn.is_closed():
                        await conn.rollback()
                except Exception as rollback_error:
                    # 忽略回滚错误，避免pipeline模式警告
                    logger.debug(f"回滚时忽略错误: {rollback_error}")
                logger.error(f"异步数据库操作失败: {e}")
                raise
    
    async def execute(self, query: str, *args) -> str:
        """
        执行SQL语句
        
        Args:
            query: SQL查询语句
            *args: 查询参数
            
        Returns:
            执行结果
        """
        async with self.get_connection() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """
        查询数据
        
        Args:
            query: SQL查询语句
            *args: 查询参数
            
        Returns:
            查询结果列表
        """
        async with self.get_connection() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchval(self, query: str, *args) -> Any:
        """
        查询单个值
        
        Args:
            query: SQL查询语句
            *args: 查询参数
            
        Returns:
            查询结果值
        """
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """
        查询单行数据
        
        Args:
            query: SQL查询语句
            *args: 查询参数
            
        Returns:
            查询结果行，如果没有结果则返回None
        """
        async with self.get_connection() as conn:
            return await conn.fetchrow(query, *args)
    
    async def executemany(self, query: str, args_list: List[tuple]) -> None:
        """
        批量执行SQL语句
        
        Args:
            query: SQL查询语句
            args_list: 参数列表
        """
        async with self.get_connection() as conn:
            await conn.executemany(query, args_list)
    
    async def copy_records_to_table(self, table_name: str, records: List[tuple], columns: List[str] = None) -> str:
        """
        批量插入数据（使用COPY命令）
        
        Args:
            table_name: 表名
            records: 记录列表
            columns: 列名列表
            
        Returns:
            插入的记录数
        """
        async with self.get_connection() as conn:
            if columns:
                columns_str = f"({', '.join(columns)})"
            else:
                columns_str = ""
            
            copy_query = f"COPY {table_name} {columns_str} FROM STDIN"
            return await conn.copy_records_to_table(table_name, records=records, columns=columns)
    
    async def get_pool_info(self) -> Dict[str, Any]:
        """获取连接池信息"""
        if not self._pool:
            return {"status": "not_initialized"}
        
        return {
            "status": "initialized",
            "pool_size": self._pool.get_size(),
            "min_size": self._pool.get_min_size(),
            "max_size": self._pool.get_max_size()
        }
    
    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("异步数据库连接池已关闭")

# 混合数据库类 - 同时支持同步和异步操作
class HybridDatabase:
    """
    混合数据库类 - 同时提供同步和异步操作
    根据使用场景自动选择最佳的实现方式
    """
    instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance
    
    def __init__(self, db_conn_string: str = None):
        """
        初始化混合数据库连接
        
        Args:
            db_conn_string: 数据库连接字符串
        """
        self.sync_db = Database(db_conn_string)
        self.async_db = AsyncDatabase(db_conn_string)
    
    # 同步方法代理
    def get_session(self):
        """获取同步会话"""
        return self.sync_db.get_session()
    
    def create_all_tables(self):
        """创建所有表"""
        return self.sync_db.create_all_tables()
    
    def initialize_database(self):
        """初始化数据库"""
        return self.sync_db.initialize_database()
    
    def get_connection_info(self):
        """获取连接信息"""
        return self.sync_db.get_connection_info()
    
    # 异步方法代理
    async def get_connection(self):
        """获取异步连接"""
        return self.async_db.get_connection()
    
    async def execute(self, query: str, *args):
        """异步执行SQL"""
        return await self.async_db.execute(query, *args)
    
    async def fetch(self, query: str, *args):
        """异步查询数据"""
        return await self.async_db.fetch(query, *args)
    
    async def fetchval(self, query: str, *args):
        """异步查询单个值"""
        return await self.async_db.fetchval(query, *args)
    
    async def fetchrow(self, query: str, *args):
        """异步查询单行"""
        return await self.async_db.fetchrow(query, *args)
    
    async def executemany(self, query: str, args_list: List[tuple]):
        """异步批量执行"""
        return await self.async_db.executemany(query, args_list)
    
    async def copy_records_to_table(self, table_name: str, records: List[tuple], columns: List[str] = None):
        """异步批量插入"""
        return await self.async_db.copy_records_to_table(table_name, records, columns)
    
    async def get_pool_info(self):
        """获取异步连接池信息"""
        return await self.async_db.get_pool_info()
    
    def close(self):
        """关闭同步连接"""
        self.sync_db.close()
    
    async def close_async(self):
        """关闭异步连接"""
        await self.async_db.close()
    
    async def close_all(self):
        """关闭所有连接"""
        self.close()
        await self.close_async()
