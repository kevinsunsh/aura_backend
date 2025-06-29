"""
数据库连接配置
"""

from typing import Dict, Any
from dataclasses import dataclass
import os

@dataclass
class DatabaseConfig:
    """数据库配置类"""
    
    # 基础连接配置
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str = "public"
    
    # 连接池配置
    pool_size: int = 20
    max_overflow: int = 30
    pool_pre_ping: bool = True
    pool_recycle: int = 3600  # 1小时
    pool_timeout: int = 30
    
    # 连接超时配置
    connect_timeout: int = 10
    command_timeout: int = 60
    
    # 性能优化配置
    ssl_mode: str = "disable"  # disable, require, verify-ca, verify-full
    application_name: str = "aura_backend"
    
    # 查询优化配置
    statement_timeout: int = 30000  # 30秒
    idle_in_transaction_session_timeout: int = 60000  # 60秒
    
    def get_connection_string(self, driver: str = "postgresql") -> str:
        """获取连接字符串"""
        base_url = f"{driver}://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        
        # 添加查询参数
        params = [
            f"sslmode={self.ssl_mode}",
            f"connect_timeout={self.connect_timeout}",
            f"application_name={self.application_name}",
            f"options=-c%20timezone=utc"
        ]
        
        return f"{base_url}?{'&'.join(params)}"
    
    def get_sqlalchemy_config(self) -> Dict[str, Any]:
        """获取SQLAlchemy配置"""
        return {
            "poolclass": "QueuePool",
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_recycle": self.pool_recycle,
            "pool_timeout": self.pool_timeout,
            "echo": False,
            "echo_pool": False,
            "connect_args": {
                "connect_timeout": self.connect_timeout,
                "application_name": self.application_name,
                "options": "-c timezone=utc"
            }
        }
    
    def get_asyncpg_config(self) -> Dict[str, Any]:
        """获取asyncpg配置"""
        return {
            "min_size": self.pool_size // 2,
            "max_size": self.pool_size,
            "command_timeout": self.command_timeout,
            "server_settings": {
                "application_name": self.application_name,
                "statement_timeout": str(self.statement_timeout),
                "idle_in_transaction_session_timeout": str(self.idle_in_transaction_session_timeout)
            }
        }

class DatabaseConfigManager:
    """数据库配置管理器"""
    
    @staticmethod
    def get_development_config() -> DatabaseConfig:
        """获取开发环境配置"""
        return DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "aura_dev"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            schema=os.getenv("POSTGRES_SCHEMA", "public"),
            # 开发环境使用较小的连接池
            pool_size=10,
            max_overflow=15,
            # 开发环境启用SQL日志
            echo=True
        )
    
    @staticmethod
    def get_production_config() -> DatabaseConfig:
        """获取生产环境配置"""
        return DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "aura_prod"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            schema=os.getenv("POSTGRES_SCHEMA", "public"),
            # 生产环境使用较大的连接池
            pool_size=30,
            max_overflow=50,
            # 生产环境优化
            pool_recycle=1800,  # 30分钟
            connect_timeout=5,
            command_timeout=30,
            # 生产环境启用SSL
            ssl_mode="require"
        )
    
    @staticmethod
    def get_test_config() -> DatabaseConfig:
        """获取测试环境配置"""
        return DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "aura_test"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            schema=os.getenv("POSTGRES_SCHEMA", "public"),
            # 测试环境使用最小连接池
            pool_size=5,
            max_overflow=10,
            # 测试环境快速超时
            connect_timeout=3,
            command_timeout=10
        )
    
    @staticmethod
    def get_config_by_environment(env: str = None) -> DatabaseConfig:
        """根据环境获取配置"""
        if env is None:
            env = os.getenv("ENVIRONMENT", "development")
        
        env = env.lower()
        
        if env == "production":
            return DatabaseConfigManager.get_production_config()
        elif env == "test":
            return DatabaseConfigManager.get_test_config()
        else:
            return DatabaseConfigManager.get_development_config()

# 性能优化建议
PERFORMANCE_TIPS = {
    "connection_pool": [
        "使用连接池而不是每次创建新连接",
        "根据并发用户数调整连接池大小",
        "监控连接池使用情况，避免连接泄漏"
    ],
    "query_optimization": [
        "使用索引优化查询性能",
        "避免N+1查询问题",
        "使用批量操作减少数据库往返",
        "合理使用事务，避免长事务"
    ],
    "connection_string": [
        "禁用SSL（如果不需要）以提高性能",
        "设置合适的连接超时时间",
        "使用连接池参数优化性能"
    ],
    "monitoring": [
        "监控连接时间和查询时间",
        "设置告警阈值",
        "定期检查连接池状态"
    ]
}

# 连接字符串模板
CONNECTION_STRING_TEMPLATES = {
    "basic": "postgresql://{user}:{password}@{host}:{port}/{database}",
    "with_ssl": "postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=require",
    "optimized": "postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=disable&connect_timeout=10&application_name=aura_backend",
    "pool_optimized": "postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=disable&connect_timeout=10&application_name=aura_backend&pool_size=20&max_overflow=30"
} 