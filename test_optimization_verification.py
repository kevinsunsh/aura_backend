#!/usr/bin/env python3
"""
验证聊天流优化效果
"""

import time
import urllib.parse
import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.config import settings
from src.agents.aura_memory.chat_stream import ChatStreamManager

def test_single_operation():
    """测试单个操作"""
    print("🔍 验证聊天流优化效果")
    
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
        
        # 测试单个获取或创建操作
        chat_id = f"test_optimization_{int(time.time())}"
        
        print(f"测试聊天流ID: {chat_id}")
        
        start_time = time.time()
        result = chat_manager.get_or_create_chat_stream(chat_id)
        duration = time.time() - start_time
        
        if result:
            print(f"✅ 操作成功: {duration*1000:.2f}ms")
            print(f"  聊天流ID: {result.chat_id}")
            print(f"  创建时间: {result.created_at}")
            print(f"  检查时间: {result.chatstream_checked_at}")
            print(f"  锁定状态: {result.chatstream_locked}")
            print(f"  心跳时间: {result.chatstream_heartbeat}")
        else:
            print(f"❌ 操作失败")
        
        # 测试更新操作
        start_time = time.time()
        update_result = chat_manager.update_lock_heartbeat(chat_id)
        update_duration = time.time() - start_time
        
        if update_result:
            print(f"✅ 更新成功: {update_duration*1000:.2f}ms")
        else:
            print(f"❌ 更新失败")
        
        print("\n✅ 优化验证完成！")
        return True
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_single_operation() 