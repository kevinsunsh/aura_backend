#!/usr/bin/env python3
"""
异步数据库 vs 同步数据库性能对比测试
使用asyncpg和psycopg3优化的实现
"""

import asyncio
import time
import statistics
import urllib.parse
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor
import threading
from sqlalchemy import text
from src.config import settings
from src.agents.aura_memory.database.database import Database, AsyncDatabase, HybridDatabase

class AsyncVsSyncPerformanceTester:
    """异步vs同步数据库性能测试器"""
    
    def __init__(self):
        # 正确处理密码中的特殊字符
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_performance_test"
        )
        
        # 初始化数据库连接
        self.sync_db = Database(self.db_conn_string)
        self.async_db = AsyncDatabase(self.db_conn_string)
        self.hybrid_db = HybridDatabase(self.db_conn_string)
        
    async def test_sync_database_performance(self, iterations: int = 100) -> Dict:
        """测试同步数据库性能"""
        print(f"🔄 开始测试同步数据库性能 ({iterations} 次迭代)")
        
        connection_times = []
        query_times = []
        errors = []
        
        for i in range(iterations):
            try:
                start_time = time.time()
                
                # 测试连接和查询
                with self.sync_db.get_session() as session:
                    conn_time = time.time() - start_time
                    connection_times.append(conn_time)
                    
                    # 执行简单查询 - 使用text()函数
                    query_start = time.time()
                    result = session.execute(text("SELECT 1")).scalar()
                    query_time = time.time() - query_start
                    query_times.append(query_time)
                    
                if i % 20 == 0:
                    print(f"  同步测试进度: {i+1}/{iterations}")
                    
            except Exception as e:
                errors.append(str(e))
                
        return {
            "type": "sync",
            "total_tests": iterations,
            "successful_tests": len(connection_times),
            "failed_tests": len(errors),
            "connection_times": connection_times,
            "query_times": query_times,
            "errors": errors
        }
    
    async def test_async_database_performance(self, iterations: int = 100) -> Dict:
        """测试异步数据库性能"""
        print(f"⚡ 开始测试异步数据库性能 ({iterations} 次迭代)")
        
        connection_times = []
        query_times = []
        errors = []
        
        async def single_test():
            try:
                start_time = time.time()
                
                # 测试连接和查询
                pool = await self.async_db.get_pool()
                conn_time = time.time() - start_time
                
                async with pool.acquire() as conn:
                    query_start = time.time()
                    result = await conn.fetchval("SELECT 1")
                    query_time = time.time() - query_start
                    
                return {
                    "conn_time": conn_time,
                    "query_time": query_time,
                    "error": None
                }
                
            except Exception as e:
                return {
                    "conn_time": 0,
                    "query_time": 0,
                    "error": str(e)
                }
        
        # 并发执行测试
        tasks = [single_test() for _ in range(iterations)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                connection_times.append(result["conn_time"])
                query_times.append(result["query_time"])
                if result["error"]:
                    errors.append(result["error"])
            
            if i % 20 == 0:
                print(f"  异步测试进度: {i+1}/{iterations}")
        
        return {
            "type": "async",
            "total_tests": iterations,
            "successful_tests": len(connection_times),
            "failed_tests": len(errors),
            "connection_times": connection_times,
            "query_times": query_times,
            "errors": errors
        }
    
    async def test_hybrid_database_performance(self, iterations: int = 100) -> Dict:
        """测试混合数据库性能"""
        print(f"🔀 开始测试混合数据库性能 ({iterations} 次迭代)")
        
        connection_times = []
        query_times = []
        errors = []
        
        async def single_test():
            try:
                start_time = time.time()
                
                # 测试异步连接和查询
                async with await self.hybrid_db.get_connection() as conn:
                    conn_time = time.time() - start_time
                    
                    query_start = time.time()
                    result = await conn.fetchval("SELECT 1")
                    query_time = time.time() - query_start
                    
                return {
                    "conn_time": conn_time,
                    "query_time": query_time,
                    "error": None
                }
                
            except Exception as e:
                return {
                    "conn_time": 0,
                    "query_time": 0,
                    "error": str(e)
                }
        
        # 并发执行测试
        tasks = [single_test() for _ in range(iterations)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                connection_times.append(result["conn_time"])
                query_times.append(result["query_time"])
                if result["error"]:
                    errors.append(result["error"])
            
            if i % 20 == 0:
                print(f"  混合测试进度: {i+1}/{iterations}")
        
        return {
            "type": "hybrid",
            "total_tests": iterations,
            "successful_tests": len(connection_times),
            "failed_tests": len(errors),
            "connection_times": connection_times,
            "query_times": query_times,
            "errors": errors
        }
    
    async def test_concurrent_performance(self, concurrent_users: int = 10, queries_per_user: int = 10) -> Dict:
        """测试并发性能"""
        print(f"🚀 开始测试并发性能 ({concurrent_users} 个并发用户，每个用户 {queries_per_user} 个查询)")
        
        # 同步并发测试
        print("\n🔄 测试同步数据库并发性能...")
        sync_start = time.time()
        sync_results = await self._test_sync_concurrent(concurrent_users, queries_per_user)
        sync_total_time = time.time() - sync_start
        
        # 异步并发测试
        print("\n⚡ 测试异步数据库并发性能...")
        async_start = time.time()
        async_results = await self._test_async_concurrent(concurrent_users, queries_per_user)
        async_total_time = time.time() - async_start
        
        # 混合并发测试
        print("\n🔀 测试混合数据库并发性能...")
        hybrid_start = time.time()
        hybrid_results = await self._test_hybrid_concurrent(concurrent_users, queries_per_user)
        hybrid_total_time = time.time() - hybrid_start
        
        return {
            "sync": {
                "total_time": sync_total_time,
                "total_queries": concurrent_users * queries_per_user,
                "queries_per_second": (concurrent_users * queries_per_user) / sync_total_time,
                "results": sync_results
            },
            "async": {
                "total_time": async_total_time,
                "total_queries": concurrent_users * queries_per_user,
                "queries_per_second": (concurrent_users * queries_per_user) / async_total_time,
                "results": async_results
            },
            "hybrid": {
                "total_time": hybrid_total_time,
                "total_queries": concurrent_users * queries_per_user,
                "queries_per_second": (concurrent_users * queries_per_user) / hybrid_total_time,
                "results": hybrid_results
            }
        }
    
    async def _test_sync_concurrent(self, concurrent_users: int, queries_per_user: int) -> List[Dict]:
        """同步并发测试"""
        results = []
        
        def user_work(user_id: int):
            user_results = []
            for i in range(queries_per_user):
                try:
                    start_time = time.time()
                    with self.sync_db.get_session() as session:
                        result = session.execute(text("SELECT 1")).scalar()
                        query_time = time.time() - start_time
                        user_results.append({
                            "user_id": user_id,
                            "query_id": i,
                            "time": query_time,
                            "success": True
                        })
                except Exception as e:
                    user_results.append({
                        "user_id": user_id,
                        "query_id": i,
                        "time": 0,
                        "success": False,
                        "error": str(e)
                    })
            return user_results
        
        # 使用线程池模拟并发用户
        with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = [executor.submit(user_work, i) for i in range(concurrent_users)]
            for future in futures:
                results.extend(future.result())
        
        return results
    
    async def _test_async_concurrent(self, concurrent_users: int, queries_per_user: int) -> List[Dict]:
        """异步并发测试"""
        results = []
        
        async def user_work(user_id: int):
            user_results = []
            for i in range(queries_per_user):
                try:
                    start_time = time.time()
                    pool = await self.async_db.get_pool()
                    async with pool.acquire() as conn:
                        result = await conn.fetchval("SELECT 1")
                        query_time = time.time() - start_time
                        user_results.append({
                            "user_id": user_id,
                            "query_id": i,
                            "time": query_time,
                            "success": True
                        })
                except Exception as e:
                    user_results.append({
                        "user_id": user_id,
                        "query_id": i,
                        "time": 0,
                        "success": False,
                        "error": str(e)
                    })
            return user_results
        
        # 创建并发任务
        tasks = [user_work(i) for i in range(concurrent_users)]
        user_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in user_results:
            if isinstance(result, Exception):
                results.append({
                    "user_id": -1,
                    "query_id": -1,
                    "time": 0,
                    "success": False,
                    "error": str(result)
                })
            else:
                results.extend(result)
        
        return results
    
    async def _test_hybrid_concurrent(self, concurrent_users: int, queries_per_user: int) -> List[Dict]:
        """混合并发测试"""
        results = []
        
        async def user_work(user_id: int):
            user_results = []
            for i in range(queries_per_user):
                try:
                    start_time = time.time()
                    async with await self.hybrid_db.get_connection() as conn:
                        result = await conn.fetchval("SELECT 1")
                        query_time = time.time() - start_time
                        user_results.append({
                            "user_id": user_id,
                            "query_id": i,
                            "time": query_time,
                            "success": True
                        })
                except Exception as e:
                    user_results.append({
                        "user_id": user_id,
                        "query_id": i,
                        "time": 0,
                        "success": False,
                        "error": str(e)
                    })
            return user_results
        
        # 创建并发任务
        tasks = [user_work(i) for i in range(concurrent_users)]
        user_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in user_results:
            if isinstance(result, Exception):
                results.append({
                    "user_id": -1,
                    "query_id": -1,
                    "time": 0,
                    "success": False,
                    "error": str(result)
                })
            else:
                results.extend(result)
        
        return results
    
    def calculate_statistics(self, data: Dict) -> Dict:
        """计算统计信息"""
        if not data["connection_times"]:
            return data
        
        conn_times = data["connection_times"]
        query_times = data["query_times"]
        
        return {
            **data,
            "connection_stats": {
                "min": min(conn_times),
                "max": max(conn_times),
                "mean": statistics.mean(conn_times),
                "median": statistics.median(conn_times),
                "std": statistics.stdev(conn_times) if len(conn_times) > 1 else 0
            },
            "query_stats": {
                "min": min(query_times),
                "max": max(query_times),
                "mean": statistics.mean(query_times),
                "median": statistics.median(query_times),
                "std": statistics.stdev(query_times) if len(query_times) > 1 else 0
            }
        }
    
    def print_performance_comparison(self, sync_stats: Dict, async_stats: Dict, hybrid_stats: Dict = None):
        """打印性能对比报告"""
        print("\n" + "="*80)
        print("📊 数据库性能对比报告")
        print("="*80)
        
        # 成功率对比
        sync_success_rate = sync_stats["successful_tests"] / sync_stats["total_tests"] * 100
        async_success_rate = async_stats["successful_tests"] / async_stats["total_tests"] * 100
        
        print(f"\n📈 成功率对比:")
        print(f"  同步数据库: {sync_success_rate:.1f}% ({sync_stats['successful_tests']}/{sync_stats['total_tests']})")
        print(f"  异步数据库: {async_success_rate:.1f}% ({async_stats['successful_tests']}/{async_stats['total_tests']})")
        
        if hybrid_stats:
            hybrid_success_rate = hybrid_stats["successful_tests"] / hybrid_stats["total_tests"] * 100
            print(f"  混合数据库: {hybrid_success_rate:.1f}% ({hybrid_stats['successful_tests']}/{hybrid_stats['total_tests']})")
        
        # 连接时间对比
        if "connection_stats" in sync_stats and "connection_stats" in async_stats:
            print(f"\n🔗 连接时间对比 (秒):")
            sync_conn = sync_stats["connection_stats"]
            async_conn = async_stats["connection_stats"]
            
            print(f"  同步数据库 - 平均: {sync_conn['mean']:.4f}, 中位数: {sync_conn['median']:.4f}")
            print(f"  异步数据库 - 平均: {async_conn['mean']:.4f}, 中位数: {async_conn['median']:.4f}")
            
            if async_conn['mean'] > 0:
                improvement = (sync_conn['mean'] - async_conn['mean']) / sync_conn['mean'] * 100
                print(f"  异步性能提升: {improvement:+.1f}%")
            
            if hybrid_stats and "connection_stats" in hybrid_stats:
                hybrid_conn = hybrid_stats["connection_stats"]
                print(f"  混合数据库 - 平均: {hybrid_conn['mean']:.4f}, 中位数: {hybrid_conn['median']:.4f}")
        
        # 查询时间对比
        if "query_stats" in sync_stats and "query_stats" in async_stats:
            print(f"\n⚡ 查询时间对比 (秒):")
            sync_query = sync_stats["query_stats"]
            async_query = async_stats["query_stats"]
            
            print(f"  同步数据库 - 平均: {sync_query['mean']:.4f}, 中位数: {sync_query['median']:.4f}")
            print(f"  异步数据库 - 平均: {async_query['mean']:.4f}, 中位数: {async_query['median']:.4f}")
            
            if async_query['mean'] > 0:
                improvement = (sync_query['mean'] - async_query['mean']) / sync_query['mean'] * 100
                print(f"  异步性能提升: {improvement:+.1f}%")
            
            if hybrid_stats and "query_stats" in hybrid_stats:
                hybrid_query = hybrid_stats["query_stats"]
                print(f"  混合数据库 - 平均: {hybrid_query['mean']:.4f}, 中位数: {hybrid_query['median']:.4f}")
        
        print("="*80)
    
    def print_concurrent_performance(self, concurrent_results: Dict):
        """打印并发性能报告"""
        print("\n" + "="*80)
        print("🚀 并发性能对比报告")
        print("="*80)
        
        sync_data = concurrent_results["sync"]
        async_data = concurrent_results["async"]
        hybrid_data = concurrent_results.get("hybrid")
        
        print(f"\n📊 总体性能:")
        print(f"  同步数据库:")
        print(f"    总时间: {sync_data['total_time']:.2f}秒")
        print(f"    总查询: {sync_data['total_queries']}")
        print(f"    每秒查询: {sync_data['queries_per_second']:.2f}")
        
        print(f"\n  异步数据库:")
        print(f"    总时间: {async_data['total_time']:.2f}秒")
        print(f"    总查询: {async_data['total_queries']}")
        print(f"    每秒查询: {async_data['queries_per_second']:.2f}")
        
        if hybrid_data:
            print(f"\n  混合数据库:")
            print(f"    总时间: {hybrid_data['total_time']:.2f}秒")
            print(f"    总查询: {hybrid_data['total_queries']}")
            print(f"    每秒查询: {hybrid_data['queries_per_second']:.2f}")
        
        # 性能提升计算
        if async_data['queries_per_second'] > 0:
            qps_improvement = (async_data['queries_per_second'] - sync_data['queries_per_second']) / sync_data['queries_per_second'] * 100
            time_improvement = (sync_data['total_time'] - async_data['total_time']) / sync_data['total_time'] * 100
            
            print(f"\n💡 异步性能提升:")
            print(f"  每秒查询数提升: {qps_improvement:+.1f}%")
            print(f"  总时间减少: {time_improvement:+.1f}%")
        
        if hybrid_data and hybrid_data['queries_per_second'] > 0:
            hybrid_qps_improvement = (hybrid_data['queries_per_second'] - sync_data['queries_per_second']) / sync_data['queries_per_second'] * 100
            hybrid_time_improvement = (sync_data['total_time'] - hybrid_data['total_time']) / sync_data['total_time'] * 100
            
            print(f"\n💡 混合性能提升:")
            print(f"  每秒查询数提升: {hybrid_qps_improvement:+.1f}%")
            print(f"  总时间减少: {hybrid_time_improvement:+.1f}%")
        
        # 成功率统计
        sync_success = len([r for r in sync_data['results'] if r['success']])
        async_success = len([r for r in async_data['results'] if r['success']])
        
        print(f"\n✅ 成功率:")
        print(f"  同步数据库: {sync_success}/{len(sync_data['results'])} ({sync_success/len(sync_data['results'])*100:.1f}%)")
        print(f"  异步数据库: {async_success}/{len(async_data['results'])} ({async_success/len(async_data['results'])*100:.1f}%)")
        
        if hybrid_data:
            hybrid_success = len([r for r in hybrid_data['results'] if r['success']])
            print(f"  混合数据库: {hybrid_success}/{len(hybrid_data['results'])} ({hybrid_success/len(hybrid_data['results'])*100:.1f}%)")
        
        print("="*80)
    
    async def run_comprehensive_test(self):
        """运行综合性能测试"""
        print("🎯 开始综合性能测试...")
        
        # 1. 基础性能测试
        print("\n1️⃣ 基础性能测试 (100次迭代)")
        sync_results = await self.test_sync_database_performance(10)
        async_results = await self.test_async_database_performance(10)
        hybrid_results = await self.test_hybrid_database_performance(10)
        
        # 计算统计信息
        sync_stats = self.calculate_statistics(sync_results)
        async_stats = self.calculate_statistics(async_results)
        hybrid_stats = self.calculate_statistics(hybrid_results)
        
        # 打印对比报告
        self.print_performance_comparison(sync_stats, async_stats, hybrid_stats)
        
        # 2. 并发性能测试
        print("\n2️⃣ 并发性能测试 (10个并发用户，每个用户10个查询)")
        concurrent_results = await self.test_concurrent_performance(10, 10)
        self.print_concurrent_performance(concurrent_results)
        
        # 3. 高并发测试
        print("\n3️⃣ 高并发性能测试 (50个并发用户，每个用户20个查询)")
        high_concurrent_results = await self.test_concurrent_performance(50, 20)
        self.print_concurrent_performance(high_concurrent_results)
        
        return {
            "basic_test": {
                "sync": sync_stats,
                "async": async_stats,
                "hybrid": hybrid_stats
            },
            "concurrent_test": concurrent_results,
            "high_concurrent_test": high_concurrent_results
        }

async def main():
    """主函数"""
    print("🚀 异步 vs 同步 vs 混合数据库性能测试")
    print("="*60)
    print("使用 asyncpg 和 psycopg3 优化的实现")
    print("="*60)
    
    try:
        tester = AsyncVsSyncPerformanceTester()
        results = await tester.run_comprehensive_test()
        
        print("\n🎉 测试完成！")
        print("\n📋 测试总结:")
        print("- 基础性能测试: 比较单次连接和查询的性能")
        print("- 并发性能测试: 比较多用户并发访问的性能")
        print("- 高并发测试: 测试极限并发情况下的性能")
        print("\n🔧 技术栈:")
        print("- 同步数据库: SQLAlchemy + psycopg3")
        print("- 异步数据库: asyncpg")
        print("- 混合数据库: 同时支持同步和异步操作")
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 