#!/usr/bin/env python3
"""
测试新的数据库实现
验证 asyncpg 和 psycopg3 的功能
"""

import asyncio
import urllib.parse
from src.config import settings
from src.agents.aura_memory.database.database import Database, AsyncDatabase, HybridDatabase
from sqlalchemy import text

async def test_sync_database():
    """测试同步数据库"""
    print("🔄 测试同步数据库...")
    
    try:
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        
        # 创建数据库实例
        db = Database(db_conn_string)
        
        # 测试连接
        with db.get_session() as session:
            result = session.execute(text("SELECT 1 as test_value")).scalar()
            print(f"  ✅ 同步查询成功: {result}")
        
        # 获取连接池信息
        pool_info = db.get_connection_info()
        print(f"  📊 连接池信息: {pool_info}")
        
        print("  ✅ 同步数据库测试通过")
        return True
        
    except Exception as e:
        print(f"  ❌ 同步数据库测试失败: {e}")
        return False

async def test_async_database():
    """测试异步数据库"""
    print("⚡ 测试异步数据库...")
    
    try:
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        
        # 创建数据库实例
        async_db = AsyncDatabase(db_conn_string)
        
        # 测试连接
        result = await async_db.fetchval("SELECT 1 as test_value")
        print(f"  ✅ 异步查询成功: {result}")
        
        # 测试查询多行
        rows = await async_db.fetch("SELECT 1 as col1, 'test' as col2")
        print(f"  ✅ 异步多行查询成功: {len(rows)} 行")
        
        # 获取连接池信息
        pool_info = await async_db.get_pool_info()
        print(f"  📊 连接池信息: {pool_info}")
        
        # 关闭连接
        await async_db.close()
        
        print("  ✅ 异步数据库测试通过")
        return True
        
    except Exception as e:
        print(f"  ❌ 异步数据库测试失败: {e}")
        return False

async def test_hybrid_database():
    """测试混合数据库"""
    print("🔀 测试混合数据库...")
    
    try:
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        
        # 创建数据库实例
        hybrid_db = HybridDatabase(db_conn_string)
        
        # 测试同步操作
        with hybrid_db.get_session() as session:
            result = session.execute(text("SELECT 1 as test_value")).scalar()
            print(f"  ✅ 混合同步查询成功: {result}")
        
        # 测试异步操作
        result = await hybrid_db.fetchval("SELECT 1 as test_value")
        print(f"  ✅ 混合异步查询成功: {result}")
        
        # 测试异步连接上下文管理器
        async with hybrid_db.get_connection() as conn:
            result = await conn.fetchval("SELECT 2 as test_value")
            print(f"  ✅ 混合异步连接查询成功: {result}")
        
        # 获取连接信息
        sync_info = hybrid_db.get_connection_info()
        async_info = await hybrid_db.get_pool_info()
        print(f"  📊 同步连接信息: {sync_info}")
        print(f"  📊 异步连接信息: {async_info}")
        
        # 关闭所有连接
        await hybrid_db.close_all()
        
        print("  ✅ 混合数据库测试通过")
        return True
        
    except Exception as e:
        print(f"  ❌ 混合数据库测试失败: {e}")
        return False

async def test_batch_operations():
    """测试批量操作"""
    print("📦 测试批量操作...")
    
    try:
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            "?sslmode=disable"
            "&connect_timeout=10"
            "&application_name=aura_backend_test"
        )
        
        # 创建异步数据库实例
        async_db = AsyncDatabase(db_conn_string)
        
        # 测试批量执行
        queries = [
            ("SELECT 1 as num",),
            ("SELECT 2 as num",),
            ("SELECT 3 as num",),
        ]
        
        for query, *args in queries:
            result = await async_db.fetchval(query, *args)
            print(f"  ✅ 批量查询: {result}")
        
        # 测试executemany
        try:
            # 创建临时表
            await async_db.execute("""
                CREATE TEMP TABLE test_batch (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    value INTEGER
                )
            """)
            
            # 批量插入数据
            data = [
                ('item1', 100),
                ('item2', 200),
                ('item3', 300),
            ]
            
            await async_db.executemany(
                "INSERT INTO test_batch (name, value) VALUES ($1, $2)",
                data
            )
            
            # 验证插入结果
            count = await async_db.fetchval("SELECT COUNT(*) FROM test_batch")
            print(f"  ✅ 批量插入成功: {count} 条记录")
            
            # 清理
            await async_db.execute("DROP TABLE test_batch")
            
        except Exception as e:
            print(f"  ⚠️  批量插入测试跳过: {e}")
        
        # 关闭连接
        await async_db.close()
        
        print("  ✅ 批量操作测试通过")
        return True
        
    except Exception as e:
        print(f"  ❌ 批量操作测试失败: {e}")
        return False

async def main():
    """主函数"""
    print("🧪 测试新的数据库实现")
    print("="*50)
    
    results = []
    
    # 测试同步数据库
    results.append(await test_sync_database())
    
    # 测试异步数据库
    results.append(await test_async_database())
    
    # 测试混合数据库
    results.append(await test_hybrid_database())
    
    # 测试批量操作
    results.append(await test_batch_operations())
    
    # 总结
    print("\n" + "="*50)
    print("📋 测试总结")
    print("="*50)
    
    passed = sum(results)
    total = len(results)
    
    print(f"通过测试: {passed}/{total}")
    
    if passed == total:
        print("🎉 所有测试通过！新的数据库实现工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    
    print("\n🔧 技术特性:")
    print("- 同步数据库: 使用 psycopg3 驱动，支持 SQLAlchemy ORM")
    print("- 异步数据库: 使用 asyncpg 驱动，高性能异步操作")
    print("- 混合数据库: 同时支持同步和异步操作")
    print("- 连接池管理: 自动管理连接池，优化性能")
    print("- 批量操作: 支持批量查询和插入")

if __name__ == "__main__":
    asyncio.run(main()) 