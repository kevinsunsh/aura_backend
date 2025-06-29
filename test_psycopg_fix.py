#!/usr/bin/env python3
"""
测试psycopg驱动修复
"""

import asyncio
from src.config import settings
from src.agents.aura_memory.chat_stream import ChatStreamManager

def test_sync_connection():
    """测试同步数据库连接"""
    print("🚀 测试同步数据库连接")
    
    try:
        # 构建连接字符串，明确使用psycopg驱动
        db_conn_string = f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        
        print(f"连接字符串: {db_conn_string}")
        
        # 创建ChatStreamManager实例
        chat_stream_manager = ChatStreamManager(db_conn_string)
        print("✅ 成功创建ChatStreamManager")
        
        # 测试获取或创建聊天流
        test_chat_id = "test_psycopg_fix"
        chat_stream = chat_stream_manager.get_or_create_chat_stream(test_chat_id)
        
        if chat_stream:
            print(f"✅ 成功获取/创建聊天流: {chat_stream.chat_id}")
        else:
            print("❌ 获取/创建聊天流失败")
            return False
        
        # 测试锁操作
        locked = chat_stream_manager.acquire_lock(test_chat_id)
        if locked:
            print(f"✅ 成功获取锁: {test_chat_id}")
            
            # 测试释放锁
            released = chat_stream_manager.release_lock(test_chat_id)
            if released:
                print(f"✅ 成功释放锁: {test_chat_id}")
            else:
                print(f"❌ 释放锁失败: {test_chat_id}")
                return False
        else:
            print(f"❌ 获取锁失败: {test_chat_id}")
            return False
        
        # 清理测试数据
        deleted = chat_stream_manager.delete_chat_stream(test_chat_id)
        if deleted:
            print(f"✅ 成功删除测试聊天流: {test_chat_id}")
        else:
            print(f"⚠️ 删除测试聊天流失败: {test_chat_id}")
        
        print("✅ 同步数据库连接测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 同步数据库连接测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def test_async_connection():
    """测试异步数据库连接"""
    print("\n🚀 测试异步数据库连接")
    
    try:
        import asyncpg
        
        # 测试asyncpg连接
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB
        )
        
        print("✅ 成功连接到PostgreSQL (asyncpg)")
        
        # 测试简单查询
        result = await conn.fetchval("SELECT 1")
        print(f"✅ 查询测试成功: {result}")
        
        await conn.close()
        print("✅ 异步数据库连接测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 异步数据库连接测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主函数"""
    print("=" * 60)
    print("psycopg驱动修复测试")
    print("=" * 60)
    
    # 测试同步连接
    sync_success = test_sync_connection()
    
    # 测试异步连接
    async_success = await test_async_connection()
    
    print("\n" + "=" * 60)
    if sync_success and async_success:
        print("🎉 所有测试通过！psycopg驱动修复成功")
    else:
        print("❌ 部分测试失败，需要进一步检查")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main()) 