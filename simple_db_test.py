#!/usr/bin/env python3
"""
简化的数据库连接测试
"""

import asyncio
import time
import urllib.parse
from src.config import settings

async def test_basic_connection():
    """测试基本连接"""
    print("🚀 测试基本数据库连接")
    
    try:
        import asyncpg
        
        # 正确处理密码中的特殊字符
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        
        # 测试连接时间
        start_time = time.time()
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB
        )
        connection_time = time.time() - start_time
        
        print(f"✅ 连接成功，耗时: {connection_time:.4f}秒")
        
        # 测试查询时间
        start_time = time.time()
        result = await conn.fetchval("SELECT 1")
        query_time = time.time() - start_time
        
        print(f"✅ 查询成功，耗时: {query_time:.4f}秒，结果: {result}")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 连接失败: {str(e)}")
        return False

async def test_connection_pool():
    """测试连接池"""
    print("\n🚀 测试连接池性能")
    
    try:
        import asyncpg
        
        # 创建连接池
        start_time = time.time()
        pool = await asyncpg.create_pool(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            min_size=5,
            max_size=10,
            command_timeout=60
        )
        pool_creation_time = time.time() - start_time
        
        print(f"✅ 连接池创建成功，耗时: {pool_creation_time:.4f}秒")
        
        # 测试并发查询
        async def single_query():
            async with pool.acquire() as conn:
                return await conn.fetchval("SELECT 1")
        
        # 执行10个并发查询
        start_time = time.time()
        tasks = [single_query() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        print(f"✅ 10个并发查询完成，总耗时: {total_time:.4f}秒")
        print(f"   平均每个查询: {total_time/10:.4f}秒")
        print(f"   每秒查询数: {10/total_time:.2f}")
        
        await pool.close()
        return True
        
    except Exception as e:
        print(f"❌ 连接池测试失败: {str(e)}")
        return False

async def main():
    """主函数"""
    print("="*50)
    print("数据库连接性能测试")
    print("="*50)
    
    # 测试基本连接
    basic_success = await test_basic_connection()
    
    # 测试连接池
    pool_success = await test_connection_pool()
    
    print("\n" + "="*50)
    if basic_success and pool_success:
        print("✅ 所有测试通过")
    else:
        print("❌ 部分测试失败")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main()) 