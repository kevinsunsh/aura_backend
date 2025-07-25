import asyncio
import time
from loguru import logger
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class ConnectionMetrics:
    """连接指标"""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    connection_time: float = 0.0
    query_time: float = 0.0
    errors: int = 0
    last_activity: Optional[datetime] = None

class DatabaseConnectionMonitor:
    """数据库连接监控器"""
    
    def __init__(self):
        self.metrics = ConnectionMetrics()
        self.connection_times: List[float] = []
        self.query_times: List[float] = []
        self.error_log: List[Dict] = []
        self.start_time = datetime.now()
        
    def record_connection_time(self, duration: float):
        """记录连接时间"""
        self.connection_times.append(duration)
        self.metrics.connection_time = sum(self.connection_times) / len(self.connection_times)
        
    def record_query_time(self, duration: float):
        """记录查询时间"""
        self.query_times.append(duration)
        self.metrics.query_time = sum(self.query_times) / len(self.query_times)
        
    def record_error(self, error: Exception, context: str = ""):
        """记录错误"""
        self.metrics.errors += 1
        self.error_log.append({
            "timestamp": datetime.now(),
            "error": str(error),
            "context": context
        })
        
    def update_connection_count(self, total: int, active: int, idle: int):
        """更新连接数"""
        self.metrics.total_connections = total
        self.metrics.active_connections = active
        self.metrics.idle_connections = idle
        self.metrics.last_activity = datetime.now()
        
    def get_performance_report(self) -> Dict:
        """获取性能报告"""
        return {
            "uptime": (datetime.now() - self.start_time).total_seconds(),
            "total_connections": len(self.connection_times),
            "avg_connection_time": self.metrics.connection_time,
            "avg_query_time": self.metrics.query_time,
            "total_queries": len(self.query_times),
            "error_rate": self.metrics.errors / max(len(self.connection_times), 1),
            "current_connections": {
                "total": self.metrics.total_connections,
                "active": self.metrics.active_connections,
                "idle": self.metrics.idle_connections
            },
            "recent_errors": self.error_log[-10:] if self.error_log else []
        }

class ConnectionOptimizer:
    """连接优化器"""
    
    def __init__(self, monitor: DatabaseConnectionMonitor):
        self.monitor = monitor
        self.optimization_rules = [
            self._check_connection_pool_size,
            self._check_query_performance,
            self._check_error_rate
        ]
        
    def analyze_and_optimize(self) -> Dict:
        """分析并优化连接"""
        report = self.monitor.get_performance_report()
        recommendations = []
        
        for rule in self.optimization_rules:
            recommendation = rule(report)
            if recommendation:
                recommendations.append(recommendation)
                
        return {
            "current_performance": report,
            "recommendations": recommendations
        }
        
    def _check_connection_pool_size(self, report: Dict) -> Optional[str]:
        """检查连接池大小"""
        if report["current_connections"]["active"] > report["current_connections"]["total"] * 0.8:
            return "建议增加连接池大小，当前活跃连接数接近上限"
        return None
        
    def _check_query_performance(self, report: Dict) -> Optional[str]:
        """检查查询性能"""
        if report["avg_query_time"] > 1.0:  # 超过1秒
            return f"查询性能较慢，平均查询时间: {report['avg_query_time']:.2f}秒，建议优化查询或添加索引"
        return None
        
    def _check_error_rate(self, report: Dict) -> Optional[str]:
        """检查错误率"""
        if report["error_rate"] > 0.05:  # 错误率超过5%
            return f"错误率较高: {report['error_rate']:.2%}，建议检查数据库连接和查询语句"
        return None

@asynccontextmanager
async def timed_connection(monitor: DatabaseConnectionMonitor):
    """带时间监控的连接上下文管理器"""
    start_time = time.time()
    try:
        yield
        duration = time.time() - start_time
        monitor.record_connection_time(duration)
    except Exception as e:
        monitor.record_error(e, "connection")
        raise

@asynccontextmanager
async def timed_query(monitor: DatabaseConnectionMonitor):
    """带时间监控的查询上下文管理器"""
    start_time = time.time()
    try:
        yield
        duration = time.time() - start_time
        monitor.record_query_time(duration)
    except Exception as e:
        monitor.record_error(e, "query")
        raise

class DatabaseHealthChecker:
    """数据库健康检查器"""
    
    def __init__(self, db_conn_string: str):
        self.db_conn_string = db_conn_string
        self.monitor = DatabaseConnectionMonitor()
        self.optimizer = ConnectionOptimizer(self.monitor)
        
    async def check_connection_health(self) -> Dict:
        """检查连接健康状态"""
        try:
            import asyncpg
            
            start_time = time.time()
            conn = await asyncpg.connect(self.db_conn_string)
            connection_time = time.time() - start_time
            
            self.monitor.record_connection_time(connection_time)
            
            # 执行简单查询测试
            start_time = time.time()
            result = await conn.fetchval("SELECT 1")
            query_time = time.time() - start_time
            
            self.monitor.record_query_time(query_time)
            
            await conn.close()
            
            return {
                "status": "healthy",
                "connection_time": connection_time,
                "query_time": query_time,
                "result": result
            }
            
        except Exception as e:
            self.monitor.record_error(e, "health_check")
            return {
                "status": "unhealthy",
                "error": str(e)
            }
            
    async def get_optimization_report(self) -> Dict:
        """获取优化报告"""
        health_result = await self.check_connection_health()
        optimization_result = self.optimizer.analyze_and_optimize()
        
        return {
            "health_check": health_result,
            "optimization": optimization_result,
            "timestamp": datetime.now().isoformat()
        }

# 全局监控器实例
global_monitor = DatabaseConnectionMonitor()

def get_global_monitor() -> DatabaseConnectionMonitor:
    """获取全局监控器"""
    return global_monitor

def check_database_health(db_conn_string: str) -> Dict[str, Any]:
    """
    检查数据库连接健康状态
    
    Args:
        db_conn_string: 数据库连接字符串
        
    Returns:
        健康状态报告
    """
    health_checker = DatabaseHealthChecker(db_conn_string)
    
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环正在运行，创建新的事件循环
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, health_checker.get_optimization_report())
                return future.result()
        else:
            return loop.run_until_complete(health_checker.get_optimization_report())
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def get_connection_pool_info(db_conn_string: str) -> Dict[str, Any]:
    """
    获取连接池信息
    
    Args:
        db_conn_string: 数据库连接字符串
        
    Returns:
        连接池信息
    """
    try:
        from .database import Database
        db = Database(db_conn_string)
        return db.get_connection_info()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        } 