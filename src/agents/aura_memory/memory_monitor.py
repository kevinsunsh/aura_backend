#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆系统监控工具

提供记忆系统的性能监控、健康检查和统计信息
"""

import time
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

from agents.aura_memory.Hippocampus import hippocampus_manager
from agents.aura_memory.message_store import MessageStore

@dataclass
class MemoryMetrics:
    """记忆系统指标"""
    total_nodes: int = 0
    total_edges: int = 0
    total_messages: int = 0
    memory_build_count: int = 0
    memory_forget_count: int = 0
    memory_consolidate_count: int = 0
    recall_operations: int = 0
    memorize_operations: int = 0
    avg_recall_time: float = 0.0
    avg_memorize_time: float = 0.0
    last_build_time: Optional[datetime] = None
    last_forget_time: Optional[datetime] = None
    last_consolidate_time: Optional[datetime] = None

class MemorySystemMonitor:
    """记忆系统监控器"""
    
    def __init__(self):
        self.metrics = MemoryMetrics()
        self.operation_times = defaultdict(list)
        self.error_log = []
        self.start_time = datetime.now()
        
    def record_operation(self, operation_type: str, duration: float, success: bool = True, error: str = None):
        """记录操作"""
        self.operation_times[operation_type].append(duration)
        
        if operation_type == "recall":
            self.metrics.recall_operations += 1
            if self.operation_times["recall"]:
                self.metrics.avg_recall_time = sum(self.operation_times["recall"]) / len(self.operation_times["recall"])
        elif operation_type == "memorize":
            self.metrics.memorize_operations += 1
            if self.operation_times["memorize"]:
                self.metrics.avg_memorize_time = sum(self.operation_times["memorize"]) / len(self.operation_times["memorize"])
        elif operation_type == "build":
            self.metrics.memory_build_count += 1
            self.metrics.last_build_time = datetime.now()
        elif operation_type == "forget":
            self.metrics.memory_forget_count += 1
            self.metrics.last_forget_time = datetime.now()
        elif operation_type == "consolidate":
            self.metrics.memory_consolidate_count += 1
            self.metrics.last_consolidate_time = datetime.now()
        
        if not success and error:
            self.error_log.append({
                "timestamp": datetime.now(),
                "operation": operation_type,
                "error": error,
                "duration": duration
            })
    
    def update_memory_graph_metrics(self):
        """更新记忆图指标"""
        try:
            if hippocampus_manager._initialized:
                memory_graph = hippocampus_manager.get_hippocampus().memory_graph.G
                self.metrics.total_nodes = len(memory_graph.nodes())
                self.metrics.total_edges = len(memory_graph.edges())
        except Exception as e:
            logger.warning(f"更新记忆图指标失败: {e}")
    
    def update_message_metrics(self):
        """更新消息指标"""
        try:
            # 这里可以添加从数据库获取消息统计的逻辑
            # 暂时使用默认值
            self.metrics.total_messages = 0
        except Exception as e:
            logger.warning(f"更新消息指标失败: {e}")
    
    def get_performance_report(self) -> Dict[str, Any]:
        """获取性能报告"""
        self.update_memory_graph_metrics()
        self.update_message_metrics()
        
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "uptime_seconds": uptime,
            "uptime_hours": uptime / 3600,
            "memory_graph": {
                "total_nodes": self.metrics.total_nodes,
                "total_edges": self.metrics.total_edges,
                "density": self.metrics.total_edges / max(self.metrics.total_nodes, 1)
            },
            "operations": {
                "recall_operations": self.metrics.recall_operations,
                "memorize_operations": self.metrics.memorize_operations,
                "build_operations": self.metrics.memory_build_count,
                "forget_operations": self.metrics.memory_forget_count,
                "consolidate_operations": self.metrics.memory_consolidate_count
            },
            "performance": {
                "avg_recall_time": self.metrics.avg_recall_time,
                "avg_memorize_time": self.metrics.avg_memorize_time,
                "recall_operations_per_hour": self.metrics.recall_operations / max(uptime / 3600, 1),
                "memorize_operations_per_hour": self.metrics.memorize_operations / max(uptime / 3600, 1)
            },
            "last_operations": {
                "last_build": self.metrics.last_build_time.isoformat() if self.metrics.last_build_time else None,
                "last_forget": self.metrics.last_forget_time.isoformat() if self.metrics.last_forget_time else None,
                "last_consolidate": self.metrics.last_consolidate_time.isoformat() if self.metrics.last_consolidate_time else None
            },
            "errors": {
                "total_errors": len(self.error_log),
                "recent_errors": self.error_log[-10:] if self.error_log else []
            }
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """获取健康状态"""
        report = self.get_performance_report()
        
        # 健康检查规则
        health_checks = {
            "memory_graph_active": report["memory_graph"]["total_nodes"] > 0,
            "operations_working": report["operations"]["recall_operations"] > 0 or report["operations"]["memorize_operations"] > 0,
            "performance_acceptable": report["performance"]["avg_recall_time"] < 5.0 and report["performance"]["avg_memorize_time"] < 2.0,
            "error_rate_low": len(report["errors"]["recent_errors"]) < 5
        }
        
        overall_health = all(health_checks.values())
        
        return {
            "status": "healthy" if overall_health else "unhealthy",
            "checks": health_checks,
            "recommendations": self._generate_recommendations(report, health_checks)
        }
    
    def _generate_recommendations(self, report: Dict[str, Any], health_checks: Dict[str, bool]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        if not health_checks["memory_graph_active"]:
            recommendations.append("记忆图为空，建议检查记忆构建是否正常工作")
        
        if not health_checks["operations_working"]:
            recommendations.append("没有检测到记忆操作，建议检查回忆和记住功能")
        
        if not health_checks["performance_acceptable"]:
            recommendations.append("记忆操作性能较慢，建议优化或检查系统负载")
        
        if not health_checks["error_rate_low"]:
            recommendations.append("错误率较高，建议检查系统日志和配置")
        
        if report["memory_graph"]["density"] < 0.1:
            recommendations.append("记忆图密度较低，建议增加记忆构建频率")
        
        return recommendations

class MemoryOptimizer:
    """记忆系统优化器"""
    
    def __init__(self, monitor: MemorySystemMonitor):
        self.monitor = monitor
    
    def analyze_and_optimize(self) -> Dict[str, Any]:
        """分析并优化记忆系统"""
        report = self.monitor.get_performance_report()
        health_status = self.monitor.get_health_status()
        
        optimizations = []
        
        # 基于性能指标进行优化建议
        if report["performance"]["avg_recall_time"] > 3.0:
            optimizations.append({
                "type": "performance",
                "action": "启用快速检索模式",
                "reason": f"回忆操作平均耗时 {report['performance']['avg_recall_time']:.2f}秒，超过阈值"
            })
        
        if report["memory_graph"]["density"] < 0.05:
            optimizations.append({
                "type": "connectivity",
                "action": "增加记忆构建频率",
                "reason": "记忆图密度较低，需要更多连接"
            })
        
        if len(report["errors"]["recent_errors"]) > 3:
            optimizations.append({
                "type": "reliability",
                "action": "检查数据库连接和配置",
                "reason": "错误率较高，需要排查系统问题"
            })
        
        return {
            "current_status": health_status,
            "performance_report": report,
            "optimizations": optimizations,
            "timestamp": datetime.now().isoformat()
        }

# 全局监控器实例
global_memory_monitor = MemorySystemMonitor()

def get_memory_monitor() -> MemorySystemMonitor:
    """获取全局记忆监控器"""
    return global_memory_monitor

def get_memory_optimizer() -> MemoryOptimizer:
    """获取记忆优化器"""
    return MemoryOptimizer(global_memory_monitor)

# 装饰器用于监控记忆操作
def monitor_memory_operation(operation_type: str):
    """监控记忆操作的装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            success = False
            error = None
            
            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                duration = time.time() - start_time
                global_memory_monitor.record_operation(operation_type, duration, success, error)
        
        return wrapper
    return decorator 