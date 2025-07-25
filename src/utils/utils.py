import time
import functools
import threading
from typing import Dict, List, Optional, Callable, Any, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import defaultdict
import json
from loguru import logger
import atexit
import sys
import random
import asyncio

def random_10_percent() -> bool:
    """返回10%概率的随机布尔值"""
    return random.random() < 0.1

@dataclass
class PerformancePoint:
    """性能统计点"""
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self):
        """结束计时"""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        return self.duration


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.points: List[PerformancePoint] = []
        self._lock = threading.Lock()
        self._active_points: Dict[str, PerformancePoint] = {}
    
    def start_point(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """开始一个性能统计点
        
        Args:
            name: 统计点名称
            metadata: 附加元数据
            
        Returns:
            统计点ID
        """
        point_id = f"{name}_{int(time.time() * 1000000)}"
        point = PerformancePoint(
            name=name,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        with self._lock:
            self._active_points[point_id] = point
            
        return point_id
    
    def end_point(self, point_id: str) -> Optional[float]:
        """结束一个性能统计点
        
        Args:
            point_id: 统计点ID
            
        Returns:
            耗时（秒），如果点不存在则返回None
        """
        with self._lock:
            if point_id not in self._active_points:
                # logger.warning(f"性能统计点 {point_id} 不存在")
                return None
                
            point = self._active_points.pop(point_id)
            duration = point.finish()
            self.points.append(point)
            
        return duration
    
    @contextmanager
    def point(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """上下文管理器，用于自动开始和结束性能统计点
        
        Args:
            name: 统计点名称
            metadata: 附加元数据
        """
        point_id = self.start_point(name, metadata)
        try:
            yield point_id
        finally:
            self.end_point(point_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取性能统计信息
        
        Returns:
            包含统计信息的字典
        """
        with self._lock:
            if not self.points:
                return {}
            
            # 按名称分组统计
            name_stats = defaultdict(list)
            for point in self.points:
                if point.duration is not None:
                    name_stats[point.name].append(point.duration)
            
            # 计算每个名称的统计信息
            statistics = {}
            for name, durations in name_stats.items():
                if durations:
                    statistics[name] = {
                        "count": len(durations),
                        "total_time": sum(durations),
                        "avg_time": sum(durations) / len(durations),
                        "min_time": min(durations),
                        "max_time": max(durations),
                        "recent_durations": durations[-10:]  # 最近10次
                    }
            
            return statistics
    
    def clear(self):
        """清空所有统计数据"""
        with self._lock:
            self.points.clear()
            self._active_points.clear()
    
    def export_report(self, format: str = "json") -> str:
        """导出性能报告
        
        Args:
            format: 报告格式 ("json" 或 "text")
            
        Returns:
            格式化的报告字符串
        """
        stats = self.get_statistics()
        
        if format == "json":
            return json.dumps(stats, indent=2, ensure_ascii=False)
        elif format == "text":
            lines = [f"性能监控报告 - {self.name}", "=" * 50]
            
            for name, stat in stats.items():
                lines.append(f"\n{name}:")
                lines.append(f"  调用次数: {stat['count']}")
                lines.append(f"  总耗时: {stat['total_time']:.4f}s")
                lines.append(f"  平均耗时: {stat['avg_time']:.4f}s")
                lines.append(f"  最小耗时: {stat['min_time']:.4f}s")
                lines.append(f"  最大耗时: {stat['max_time']:.4f}s")
                
                if stat['recent_durations']:
                    recent_avg = sum(stat['recent_durations']) / len(stat['recent_durations'])
                    lines.append(f"  最近10次平均: {recent_avg:.4f}s")
            
            return "\n".join(lines)
        else:
            raise ValueError(f"不支持的格式: {format}")


# 全局性能监控器实例
_global_monitor = PerformanceMonitor("global")


def performance_point(name: str, metadata: Optional[Dict[str, Any]] = None):
    """装饰器：为函数添加性能统计点
    
    Args:
        name: 统计点名称
        metadata: 附加元数据
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _global_monitor.point(name, metadata):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def start_performance_point(name: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """开始一个性能统计点（全局监控器）
    
    Args:
        name: 统计点名称
        metadata: 附加元数据
        
    Returns:
        统计点ID
    """
    return _global_monitor.start_point(name, metadata)


def end_performance_point(point_id: str) -> Optional[float]:
    """结束一个性能统计点（全局监控器）
    
    Args:
        point_id: 统计点ID
        
    Returns:
        耗时（秒），如果点不存在则返回None
    """
    return _global_monitor.end_point(point_id)


def get_performance_statistics() -> Dict[str, Any]:
    """获取全局性能统计信息
    
    Returns:
        包含统计信息的字典
    """
    return _global_monitor.get_statistics()


def export_performance_report(format: str = "json") -> str:
    """导出全局性能报告
    
    Args:
        format: 报告格式 ("json" 或 "text")
        
    Returns:
        格式化的报告字符串
    """
    return _global_monitor.export_report(format)


def clear_performance_data():
    """清空全局性能数据"""
    _global_monitor.clear()


# 便捷的上下文管理器
@contextmanager
def performance_point_context(name: str, metadata: Optional[Dict[str, Any]] = None):
    """性能统计点上下文管理器（全局监控器）
    
    Args:
        name: 统计点名称
        metadata: 附加元数据
    """
    with _global_monitor.point(name, metadata) as point_id:
        yield point_id

async def safe_call(func: Callable | None, *args, **kwargs) -> Tuple[Any, Optional[Exception]]:
    """
    安全调用传入的函数func，支持同步和异步函数，捕获异常并返回结果或异常信息。

    Args:
        func: 要调用的函数（可以是同步或异步）
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        (result, error): 
            result: 函数返回值（如果调用成功）
            error: 异常对象（如果发生异常，否则为None）
    """
    try:
        if func is None:
            return None, None
        if asyncio.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = func(*args, **kwargs)
        return result, None
    except Exception as e:
        return None, e


# 进程退出时自动输出性能报告
def _exit_handler():
    """进程退出时的处理函数"""
    try:
        stats = get_performance_statistics()
        if stats:
            print("\n" + "="*60)
            print("进程退出 - 性能统计报告")
            print("="*60)
            print(export_performance_report("text"))
            print("="*60)
        else:
            print("\n进程退出 - 无性能统计数据")
    except Exception as e:
        print(f"\n进程退出时输出性能报告失败: {e}")

# 注册进程退出处理函数
atexit.register(_exit_handler)


# 示例用法
if __name__ == "__main__":
    # 示例1: 使用装饰器
    @performance_point("数据库查询")
    def query_database():
        time.sleep(0.1)  # 模拟数据库查询
        return "查询结果"
    
    # 示例2: 使用上下文管理器
    def process_data():
        with performance_point_context("数据处理"):
            time.sleep(0.05)  # 模拟数据处理
            with performance_point_context("数据验证"):
                time.sleep(0.02)  # 模拟数据验证
    
    # 示例3: 手动控制
    def complex_operation():
        point_id = start_performance_point("复杂操作")
        try:
            time.sleep(0.08)  # 模拟复杂操作
            return "操作完成"
        finally:
            end_performance_point(point_id)
    
    # 运行示例
    query_database()
    process_data()
    complex_operation()
    
    # 输出统计报告
    print(export_performance_report("text"))
