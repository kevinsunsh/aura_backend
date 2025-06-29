#!/usr/bin/env python3
"""
全面的数据库测试脚本
测试同步、异步和混合数据库类的所有功能
"""

import asyncio
import time
import sys
import os
from typing import List, Dict, Any
import logging
import urllib.parse

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.aura_memory.database.database import Database, AsyncDatabase, HybridDatabase
from src.config import settings
from sqlalchemy import text

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DatabaseTester:
    """数据库测试类"""
    
    def __init__(self):
        """初始化测试器"""
        # 正确处理密码中的特殊字符
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        self.test_results = []
    
    def log_test(self, test_name: str, success: bool, details: str = "", duration: float = 0):
        """记录测试结果"""
        status = "✅ 通过" if success else "❌ 失败"
        result = {
            "test": test_name,
            "success": success,
            "details": details,
            "duration": duration
        }
        self.test_results.append(result)
        print(f"{status} {test_name} - {details} ({duration:.4f}s)")
    
    def test_sync_database_connection(self):
        """测试同步数据库连接"""
        print("\n🔧 测试同步数据库连接")
        
        try:
            start_time = time.time()
            db = Database(self.db_conn_string)
            duration = time.time() - start_time
            
            self.log_test("同步数据库初始化", True, "数据库对象创建成功", duration)
            
            # 测试获取会话
            start_time = time.time()
            with db.get_session() as session:
                result = session.execute(text("SELECT 1")).scalar()
                duration = time.time() - start_time
                
                if result == 1:
                    self.log_test("同步数据库查询", True, f"查询结果: {result}", duration)
                else:
                    self.log_test("同步数据库查询", False, f"查询结果异常: {result}", duration)
            
            # 测试连接池信息
            pool_info = db.get_connection_info()
            self.log_test("同步连接池信息", True, f"池大小: {pool_info['pool_size']}")
            
            # 关闭连接
            db.close()
            self.log_test("同步数据库关闭", True, "连接已关闭")
            
            return True
            
        except Exception as e:
            self.log_test("同步数据库测试", False, f"错误: {str(e)}")
            return False
    
    async def test_async_database_connection(self):
        """测试异步数据库连接"""
        print("\n🔧 测试异步数据库连接")
        
        try:
            start_time = time.time()
            async_db = AsyncDatabase(self.db_conn_string)
            duration = time.time() - start_time
            
            self.log_test("异步数据库初始化", True, "数据库对象创建成功", duration)
            
            # 测试获取连接池
            start_time = time.time()
            pool = await async_db.get_pool()
            duration = time.time() - start_time
            
            self.log_test("异步连接池创建", True, "连接池创建成功", duration)
            
            # 测试基本查询
            start_time = time.time()
            result = await async_db.fetchval("SELECT 1")
            duration = time.time() - start_time
            
            if result == 1:
                self.log_test("异步数据库查询", True, f"查询结果: {result}", duration)
            else:
                self.log_test("异步数据库查询", False, f"查询结果异常: {result}", duration)
            
            # 测试多行查询
            start_time = time.time()
            rows = await async_db.fetch("SELECT generate_series(1, 5) as num")
            duration = time.time() - start_time
            
            if len(rows) == 5:
                self.log_test("异步多行查询", True, f"返回 {len(rows)} 行数据", duration)
            else:
                self.log_test("异步多行查询", False, f"返回行数异常: {len(rows)}", duration)
            
            # 测试连接池信息
            pool_info = await async_db.get_pool_info()
            self.log_test("异步连接池信息", True, f"状态: {pool_info['status']}")
            
            # 关闭连接
            await async_db.close()
            self.log_test("异步数据库关闭", True, "连接池已关闭")
            
            return True
            
        except Exception as e:
            self.log_test("异步数据库测试", False, f"错误: {str(e)}")
            return False
    
    def test_hybrid_database(self):
        """测试混合数据库"""
        print("\n🔧 测试混合数据库")
        
        try:
            start_time = time.time()
            hybrid_db = HybridDatabase(self.db_conn_string)
            duration = time.time() - start_time
            
            self.log_test("混合数据库初始化", True, "数据库对象创建成功", duration)
            
            # 测试同步功能
            start_time = time.time()
            with hybrid_db.get_session() as session:
                result = session.execute(text("SELECT 1")).scalar()
                duration = time.time() - start_time
                
                if result == 1:
                    self.log_test("混合数据库同步查询", True, f"查询结果: {result}", duration)
                else:
                    self.log_test("混合数据库同步查询", False, f"查询结果异常: {result}", duration)
            
            # 测试连接信息
            conn_info = hybrid_db.get_connection_info()
            self.log_test("混合数据库连接信息", True, f"池大小: {conn_info['pool_size']}")
            
            # 关闭同步连接
            hybrid_db.close()
            self.log_test("混合数据库同步关闭", True, "同步连接已关闭")
            
            return True
            
        except Exception as e:
            self.log_test("混合数据库测试", False, f"错误: {str(e)}")
            return False
    
    async def test_hybrid_database_async(self):
        """测试混合数据库的异步功能"""
        print("\n🔧 测试混合数据库异步功能")
        
        try:
            hybrid_db = HybridDatabase(self.db_conn_string)
            
            # 测试异步查询
            start_time = time.time()
            result = await hybrid_db.fetchval("SELECT 1")
            duration = time.time() - start_time
            
            if result == 1:
                self.log_test("混合数据库异步查询", True, f"查询结果: {result}", duration)
            else:
                self.log_test("混合数据库异步查询", False, f"查询结果异常: {result}", duration)
            
            # 测试异步连接池信息
            pool_info = await hybrid_db.get_pool_info()
            self.log_test("混合数据库异步连接池信息", True, f"状态: {pool_info['status']}")
            
            # 关闭异步连接
            await hybrid_db.close_async()
            self.log_test("混合数据库异步关闭", True, "异步连接池已关闭")
            
            return True
            
        except Exception as e:
            self.log_test("混合数据库异步测试", False, f"错误: {str(e)}")
            return False
    
    async def test_concurrent_operations(self):
        """测试并发操作"""
        print("\n🔧 测试并发操作")
        
        try:
            async_db = AsyncDatabase(self.db_conn_string)
            
            # 并发查询函数
            async def single_query(query_id: int):
                try:
                    result = await async_db.fetchval(f"SELECT {query_id} as num")
                    return query_id, result, True
                except Exception as e:
                    return query_id, str(e), False
            
            # 执行10个并发查询
            start_time = time.time()
            tasks = [single_query(i) for i in range(1, 11)]
            results = await asyncio.gather(*tasks)
            duration = time.time() - start_time
            
            # 检查结果
            success_count = sum(1 for _, _, success in results if success)
            if success_count == 10:
                self.log_test("并发查询测试", True, f"10个查询全部成功", duration)
            else:
                self.log_test("并发查询测试", False, f"成功: {success_count}/10", duration)
            
            # 测试批量操作
            start_time = time.time()
            await async_db.executemany(
                "SELECT $1::int as num",
                [(i,) for i in range(1, 6)]
            )
            duration = time.time() - start_time
            
            self.log_test("批量操作测试", True, "批量查询执行成功", duration)
            
            await async_db.close()
            return True
            
        except Exception as e:
            self.log_test("并发操作测试", False, f"错误: {str(e)}")
            return False
    
    async def test_error_handling(self):
        """测试错误处理"""
        print("\n🔧 测试错误处理")
        
        try:
            async_db = AsyncDatabase(self.db_conn_string)
            
            # 测试无效SQL
            try:
                await async_db.execute("SELECT * FROM non_existent_table")
                self.log_test("错误处理测试", False, "应该抛出异常但没有")
            except Exception as e:
                self.log_test("错误处理测试", True, f"正确捕获异常: {type(e).__name__}")
            
            # 测试连接池关闭后的操作
            await async_db.close()
            try:
                # 关闭后重新创建连接池并查询应该成功
                result = await async_db.fetchval("SELECT 1")
                if result == 1:
                    self.log_test("关闭后操作测试", True, "连接池重新创建并查询成功")
                else:
                    self.log_test("关闭后操作测试", False, f"查询结果异常: {result}")
            except Exception as e:
                self.log_test("关闭后操作测试", True, f"正确捕获异常: {type(e).__name__}")
            
            return True
            
        except Exception as e:
            self.log_test("错误处理测试", False, f"错误: {str(e)}")
            return False
    
    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*60)
        print("📊 测试结果总结")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"总测试数: {total_tests}")
        print(f"通过: {passed_tests}")
        print(f"失败: {failed_tests}")
        print(f"成功率: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print("\n❌ 失败的测试:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")
        
        print("\n⏱️ 性能统计:")
        durations = [r["duration"] for r in self.test_results if r["duration"] > 0]
        if durations:
            print(f"  平均耗时: {sum(durations)/len(durations):.4f}秒")
            print(f"  最快: {min(durations):.4f}秒")
            print(f"  最慢: {max(durations):.4f}秒")
        
        print("="*60)
        
        return passed_tests == total_tests

async def main():
    """主函数"""
    print("🚀 开始全面数据库测试")
    print("="*60)
    
    tester = DatabaseTester()
    
    # 运行所有测试
    await tester.test_async_database_connection()
    tester.test_sync_database_connection()
    tester.test_hybrid_database()
    await tester.test_hybrid_database_async()
    await tester.test_concurrent_operations()
    await tester.test_error_handling()
    
    # 打印总结
    success = tester.print_summary()
    
    if success:
        print("🎉 所有测试通过！数据库功能正常。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查数据库配置和连接。")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️ 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 测试过程中发生错误: {e}")
        sys.exit(1) 