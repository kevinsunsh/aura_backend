#!/usr/bin/env python3
"""
数据库连接性能测试脚本
"""

import asyncio
import time
import statistics
import urllib.parse
from typing import List, Dict
from src.config import settings
from src.agents.aura_memory.database.connection_monitor import DatabaseHealthChecker, get_global_monitor

class DatabasePerformanceTester:
    """数据库性能测试器"""
    
    def __init__(self):
        # 正确处理密码中的特殊字符
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        self.health_checker = DatabaseHealthChecker(self.db_conn_string)
        
    async def test_connection_performance(self, iterations: int = 10) -> Dict:
        """测试连接性能"""
        print(f"🚀 开始测试数据库连接性能 ({iterations} 次迭代)")
        
        connection_times = []
        query_times = []
        errors = []
        
        for i in range(iterations):
            try:
                print(f"  测试 {i+1}/{iterations}...")
                result = await self.health_checker.check_connection_health()
                
                if result["status"] == "healthy":
                    connection_times.append(result["connection_time"])
                    query_times.append(result["query_time"])
                else:
                    errors.append(result["error"])
                    
            except Exception as e:
                errors.append(str(e))
                
            # 短暂延迟，避免过于频繁的连接
            await asyncio.sleep(0.1)
        
        # 计算统计信息
        stats = {
            "total_tests": iterations,
            "successful_tests": len(connection_times),
            "failed_tests": len(errors),
            "connection_times": {
                "min": min(connection_times) if connection_times else 0,
                "max": max(connection_times) if connection_times else 0,
                "mean": statistics.mean(connection_times) if connection_times else 0,
                "median": statistics.median(connection_times) if connection_times else 0,
                "std": statistics.stdev(connection_times) if len(connection_times) > 1 else 0
            },
            "query_times": {
                "min": min(query_times) if query_times else 0,
                "max": max(query_times) if query_times else 0,
                "mean": statistics.mean(query_times) if query_times else 0,
                "median": statistics.median(query_times) if query_times else 0,
                "std": statistics.stdev(query_times) if len(query_times) > 1 else 0
            },
            "errors": errors
        }
        
        return stats
    
    async def test_connection_pool_performance(self, pool_size: int = 10, iterations: int = 50) -> Dict:
        """测试连接池性能"""
        print(f"🚀 开始测试连接池性能 (池大小: {pool_size}, 迭代: {iterations})")
        
        try:
            import asyncpg
            
            # 创建连接池
            pool = await asyncpg.create_pool(
                self.db_conn_string,
                min_size=pool_size // 2,
                max_size=pool_size,
                command_timeout=60
            )
            
            start_time = time.time()
            tasks = []
            
            async def single_query():
                async with pool.acquire() as conn:
                    return await conn.fetchval("SELECT 1")
            
            # 并发执行查询
            for i in range(iterations):
                task = asyncio.create_task(single_query())
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time
            
            # 统计结果
            successful = len([r for r in results if not isinstance(r, Exception)])
            failed = len([r for r in results if isinstance(r, Exception)])
            
            await pool.close()
            
            return {
                "pool_size": pool_size,
                "total_queries": iterations,
                "successful_queries": successful,
                "failed_queries": failed,
                "total_time": total_time,
                "queries_per_second": iterations / total_time,
                "avg_time_per_query": total_time / iterations
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "pool_size": pool_size,
                "total_queries": iterations
            }
    
    async def compare_connection_methods(self) -> Dict:
        """比较不同连接方法的性能"""
        print("🔍 比较不同连接方法的性能")
        
        results = {}
        
        # 测试1: 直接连接
        print("\n1. 测试直接连接...")
        results["direct_connection"] = await self.test_connection_performance(20)
        
        # 测试2: 连接池
        print("\n2. 测试连接池...")
        results["connection_pool"] = await self.test_connection_pool_performance(10, 50)
        
        # 测试3: 健康检查
        print("\n3. 测试健康检查...")
        results["health_check"] = await self.health_checker.get_optimization_report()
        
        return results
    
    def print_performance_report(self, stats: Dict):
        """打印性能报告"""
        print("\n" + "="*60)
        print("📊 数据库连接性能报告")
        print("="*60)
        
        if "connection_times" in stats:
            conn_times = stats["connection_times"]
            query_times = stats["query_times"]
            
            print(f"总测试次数: {stats['total_tests']}")
            print(f"成功次数: {stats['successful_tests']}")
            print(f"失败次数: {stats['failed_tests']}")
            print(f"成功率: {stats['successful_tests']/stats['total_tests']*100:.1f}%")
            
            print(f"\n连接时间统计 (秒):")
            print(f"  最小值: {conn_times['min']:.4f}")
            print(f"  最大值: {conn_times['max']:.4f}")
            print(f"  平均值: {conn_times['mean']:.4f}")
            print(f"  中位数: {conn_times['median']:.4f}")
            print(f"  标准差: {conn_times['std']:.4f}")
            
            print(f"\n查询时间统计 (秒):")
            print(f"  最小值: {query_times['min']:.4f}")
            print(f"  最大值: {query_times['max']:.4f}")
            print(f"  平均值: {query_times['mean']:.4f}")
            print(f"  中位数: {query_times['median']:.4f}")
            print(f"  标准差: {query_times['std']:.4f}")
            
            if stats['errors']:
                print(f"\n错误信息:")
                for error in stats['errors'][:5]:  # 只显示前5个错误
                    print(f"  - {error}")
        
        elif "queries_per_second" in stats:
            print(f"连接池大小: {stats['pool_size']}")
            print(f"总查询数: {stats['total_queries']}")
            print(f"成功查询: {stats['successful_queries']}")
            print(f"失败查询: {stats['failed_queries']}")
            print(f"总时间: {stats['total_time']:.2f}秒")
            print(f"每秒查询数: {stats['queries_per_second']:.2f}")
            print(f"平均查询时间: {stats['avg_time_per_query']:.4f}秒")
        
        print("="*60)
    
    def print_optimization_recommendations(self, report: Dict):
        """打印优化建议"""
        print("\n" + "="*60)
        print("💡 数据库连接优化建议")
        print("="*60)
        
        if "optimization" in report and "recommendations" in report["optimization"]:
            recommendations = report["optimization"]["recommendations"]
            
            if recommendations:
                for i, rec in enumerate(recommendations, 1):
                    print(f"{i}. {rec}")
            else:
                print("✅ 当前数据库连接性能良好，无需优化")
        
        print("="*60)

async def main():
    """主函数"""
    print("🚀 数据库连接性能测试")
    print("="*60)
    
    tester = DatabasePerformanceTester()
    
    try:
        # 1. 基础连接性能测试
        print("\n📈 基础连接性能测试")
        stats = await tester.test_connection_performance(15)
        tester.print_performance_report(stats)
        
        # 2. 连接池性能测试
        print("\n📈 连接池性能测试")
        pool_stats = await tester.test_connection_pool_performance(15, 100)
        tester.print_performance_report(pool_stats)
        
        # 3. 综合性能比较
        print("\n📈 综合性能比较")
        comparison = await tester.compare_connection_methods()
        
        # 4. 优化建议
        if "health_check" in comparison:
            tester.print_optimization_recommendations(comparison["health_check"])
        
        print("\n✅ 性能测试完成")
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 