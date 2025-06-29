#!/usr/bin/env python3
"""
简单的聊天流性能测试脚本
"""

import time
import urllib.parse
import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.config import settings
from src.agents.aura_memory.chat_stream import ChatStreamManager

def test_chat_stream_performance():
    """测试聊天流性能"""
    print("🚀 开始聊天流性能测试")
    
    try:
        # 构建数据库连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        
        # 初始化聊天流管理器
        chat_manager = ChatStreamManager(db_conn_string)
        
        # 测试获取或创建聊天流
        print("\n📊 测试获取或创建聊天流性能")
        test_iterations = 50
        
        times = []
        for i in range(test_iterations):
            chat_id = f"test_performance_{i}_{int(time.time())}"
            
            start_time = time.time()
            result = chat_manager.get_or_create_chat_stream(chat_id)
            duration = time.time() - start_time
            times.append(duration)
            
            if result:
                print(f"  ✅ 创建成功: {chat_id} ({duration*1000:.2f}ms)")
            else:
                print(f"  ❌ 创建失败: {chat_id}")
        
        # 统计结果
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\n📈 性能统计:")
        print(f"  平均时间: {avg_time*1000:.2f}ms")
        print(f"  最小时间: {min_time*1000:.2f}ms")
        print(f"  最大时间: {max_time*1000:.2f}ms")
        print(f"  每秒操作: {test_iterations/sum(times):.2f}")
        
        # 测试更新操作
        print(f"\n💓 测试更新心跳性能")
        update_times = []
        for i in range(test_iterations):
            chat_id = f"test_heartbeat_{i}_{int(time.time())}"
            
            # 先创建聊天流
            chat_manager.get_or_create_chat_stream(chat_id)
            
            start_time = time.time()
            result = chat_manager.update_lock_heartbeat(chat_id)
            duration = time.time() - start_time
            update_times.append(duration)
            
            if result:
                print(f"  ✅ 更新成功: {chat_id} ({duration*1000:.2f}ms)")
            else:
                print(f"  ❌ 更新失败: {chat_id}")
        
        # 统计更新结果
        avg_update_time = sum(update_times) / len(update_times)
        print(f"\n📈 更新性能统计:")
        print(f"  平均时间: {avg_update_time*1000:.2f}ms")
        print(f"  每秒操作: {test_iterations/sum(update_times):.2f}")
        
        print("\n✅ 性能测试完成！")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_chat_stream_performance() 