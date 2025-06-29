#!/usr/bin/env python3
"""
聊天流性能测试脚本
对比优化前后的性能差异
"""

import time
import statistics
import urllib.parse
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from src.config import settings
from src.agents.aura_memory.chat_stream import ChatStreamManager

class ChatStreamPerformanceTester:
    """聊天流性能测试器"""
    
    def __init__(self):
        # 构建数据库连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        self.db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_performance_test"
        )
        
        # 初始化聊天流管理器
        self.chat_manager = ChatStreamManager(self.db_conn_string)
        
    def test_get_or_create_performance(self, iterations: int = 100) -> Dict:
        """测试获取或创建聊天流的性能"""
        print(f"🚀 开始测试获取或创建聊天流性能 (迭代: {iterations})")
        
        times = []
        successful = 0
        failed = 0
        
        for i in range(iterations):
            chat_id = f"test_performance_{i}_{int(time.time())}"
            
            start_time = time.time()
            try:
                result = self.chat_manager.get_or_create_chat_stream(chat_id)
                if result:
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"错误: {e}")
            
            duration = time.time() - start_time
            times.append(duration)
        
        # 统计结果
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18]  # 95th percentile
        
        return {
            "operation": "get_or_create_chat_stream",
            "iterations": iterations,
            "successful": successful,
            "failed": failed,
            "avg_time_ms": avg_time * 1000,
            "min_time_ms": min_time * 1000,
            "max_time_ms": max_time * 1000,
            "p95_time_ms": p95_time * 1000,
            "ops_per_second": iterations / sum(times)
        }
    
    def test_update_heartbeat_performance(self, iterations: int = 100) -> Dict:
        """测试更新心跳的性能"""
        print(f"💓 开始测试更新心跳性能 (迭代: {iterations})")
        
        # 先创建一些测试聊天流
        test_chat_ids = []
        for i in range(iterations):
            chat_id = f"test_heartbeat_{i}_{int(time.time())}"
            self.chat_manager.get_or_create_chat_stream(chat_id)
            test_chat_ids.append(chat_id)
        
        times = []
        successful = 0
        failed = 0
        
        for chat_id in test_chat_ids:
            start_time = time.time()
            try:
                result = self.chat_manager.update_lock_heartbeat(chat_id)
                if result:
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"错误: {e}")
            
            duration = time.time() - start_time
            times.append(duration)
        
        # 统计结果
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max_time
        
        return {
            "operation": "update_lock_heartbeat",
            "iterations": iterations,
            "successful": successful,
            "failed": failed,
            "avg_time_ms": avg_time * 1000,
            "min_time_ms": min_time * 1000,
            "max_time_ms": max_time * 1000,
            "p95_time_ms": p95_time * 1000,
            "ops_per_second": iterations / sum(times)
        }
    
    def test_update_checked_at_performance(self, iterations: int = 100) -> Dict:
        """测试更新检查时间的性能"""
        print(f"⏰ 开始测试更新检查时间性能 (迭代: {iterations})")
        
        # 先创建一些测试聊天流
        test_chat_ids = []
        for i in range(iterations):
            chat_id = f"test_checked_{i}_{int(time.time())}"
            self.chat_manager.get_or_create_chat_stream(chat_id)
            test_chat_ids.append(chat_id)
        
        times = []
        successful = 0
        failed = 0
        
        for chat_id in test_chat_ids:
            start_time = time.time()
            try:
                result = self.chat_manager.update_chat_stream_checked_at(chat_id)
                if result:
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"错误: {e}")
            
            duration = time.time() - start_time
            times.append(duration)
        
        # 统计结果
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max_time
        
        return {
            "operation": "update_chat_stream_checked_at",
            "iterations": iterations,
            "successful": successful,
            "failed": failed,
            "avg_time_ms": avg_time * 1000,
            "min_time_ms": min_time * 1000,
            "max_time_ms": max_time * 1000,
            "p95_time_ms": p95_time * 1000,
            "ops_per_second": iterations / sum(times)
        }
    
    def test_concurrent_performance(self, concurrent_threads: int = 10, operations_per_thread: int = 50) -> Dict:
        """测试并发性能"""
        print(f"🔄 开始测试并发性能 (线程: {concurrent_threads}, 每线程操作: {operations_per_thread})")
        
        def worker(thread_id: int):
            """工作线程函数"""
            thread_times = []
            thread_successful = 0
            thread_failed = 0
            
            for i in range(operations_per_thread):
                chat_id = f"test_concurrent_{thread_id}_{i}_{int(time.time())}"
                
                start_time = time.time()
                try:
                    # 执行获取或创建操作
                    result = self.chat_manager.get_or_create_chat_stream(chat_id)
                    if result:
                        thread_successful += 1
                    else:
                        thread_failed += 1
                except Exception as e:
                    thread_failed += 1
                
                duration = time.time() - start_time
                thread_times.append(duration)
            
            return {
                "times": thread_times,
                "successful": thread_successful,
                "failed": thread_failed
            }
        
        # 使用线程池执行并发测试
        all_times = []
        total_successful = 0
        total_failed = 0
        
        with ThreadPoolExecutor(max_workers=concurrent_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(concurrent_threads)]
            
            for future in futures:
                result = future.result()
                all_times.extend(result["times"])
                total_successful += result["successful"]
                total_failed += result["failed"]
        
        # 统计结果
        total_operations = concurrent_threads * operations_per_thread
        avg_time = statistics.mean(all_times)
        min_time = min(all_times)
        max_time = max(all_times)
        p95_time = statistics.quantiles(all_times, n=20)[18] if len(all_times) >= 20 else max_time
        
        return {
            "operation": "concurrent_get_or_create",
            "concurrent_threads": concurrent_threads,
            "operations_per_thread": operations_per_thread,
            "total_operations": total_operations,
            "successful": total_successful,
            "failed": total_failed,
            "avg_time_ms": avg_time * 1000,
            "min_time_ms": min_time * 1000,
            "max_time_ms": max_time * 1000,
            "p95_time_ms": p95_time * 1000,
            "ops_per_second": total_operations / sum(all_times)
        }
    
    def run_comprehensive_test(self):
        """运行综合性能测试"""
        print("🎯 开始综合性能测试")
        print("=" * 60)
        
        results = []
        
        # 测试不同规模的性能
        test_scales = [10, 50, 100, 200]
        
        for scale in test_scales:
            print(f"\n📊 测试规模: {scale} 次操作")
            
            # 测试获取或创建性能
            result = self.test_get_or_create_performance(scale)
            results.append(result)
            self.print_result(result)
            
            # 测试更新心跳性能
            result = self.test_update_heartbeat_performance(scale)
            results.append(result)
            self.print_result(result)
            
            # 测试更新检查时间性能
            result = self.test_update_checked_at_performance(scale)
            results.append(result)
            self.print_result(result)
        
        # 测试并发性能
        print(f"\n🔄 测试并发性能")
        result = self.test_concurrent_performance(10, 50)
        results.append(result)
        self.print_result(result)
        
        # 生成性能报告
        self.generate_performance_report(results)
    
    def print_result(self, result: Dict):
        """打印测试结果"""
        print(f"  {result['operation']}:")
        print(f"    成功: {result['successful']}, 失败: {result['failed']}")
        print(f"    平均时间: {result['avg_time_ms']:.2f}ms")
        print(f"    最小时间: {result['min_time_ms']:.2f}ms")
        print(f"    最大时间: {result['max_time_ms']:.2f}ms")
        print(f"    95%分位: {result['p95_time_ms']:.2f}ms")
        print(f"    每秒操作: {result['ops_per_second']:.2f}")
    
    def generate_performance_report(self, results: List[Dict]):
        """生成性能报告"""
        print("\n" + "=" * 60)
        print("📈 性能测试报告")
        print("=" * 60)
        
        # 按操作类型分组
        operations = {}
        for result in results:
            op = result['operation']
            if op not in operations:
                operations[op] = []
            operations[op].append(result)
        
        for op, op_results in operations.items():
            print(f"\n🔧 {op}:")
            for result in op_results:
                if 'concurrent_threads' in result:
                    print(f"  并发测试 ({result['concurrent_threads']}线程): "
                          f"平均 {result['avg_time_ms']:.2f}ms, "
                          f"{result['ops_per_second']:.2f} ops/sec")
                else:
                    print(f"  规模 {result['iterations']}: "
                          f"平均 {result['avg_time_ms']:.2f}ms, "
                          f"{result['ops_per_second']:.2f} ops/sec")
        
        print("\n✅ 性能测试完成！")

def main():
    """主函数"""
    print("🚀 聊天流性能测试")
    print("使用psycopg直接SQL优化后的性能测试")
    
    try:
        tester = ChatStreamPerformanceTester()
        tester.run_comprehensive_test()
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 