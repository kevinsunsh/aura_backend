#!/usr/bin/env python3
"""
测试SSL禁用对数据库连接性能的影响
"""

import asyncio
import time
import urllib.parse
from src.config import settings

async def test_connection_with_ssl_mode(ssl_mode: str, test_name: str):
    """测试不同SSL模式的连接性能"""
    print(f"\n🚀 测试 {test_name}")
    
    try:
        import asyncpg
        
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            f"?sslmode={ssl_mode}"
        )
        
        # 测试连接时间
        start_time = time.time()
        conn = await asyncpg.connect(conn_string)
        connection_time = time.time() - start_time
        
        print(f"✅ 连接成功，耗时: {connection_time:.4f}秒")
        
        # 测试查询时间
        start_time = time.time()
        result = await conn.fetchval("SELECT 1")
        query_time = time.time() - start_time
        
        print(f"✅ 查询成功，耗时: {query_time:.4f}秒，结果: {result}")
        
        await conn.close()
        return connection_time, query_time
        
    except Exception as e:
        print(f"❌ 连接失败: {str(e)}")
        return None, None

async def test_connection_pool_performance(ssl_mode: str, test_name: str):
    """测试连接池性能"""
    print(f"\n🚀 测试连接池性能 - {test_name}")
    
    try:
        import asyncpg
        
        # 构建连接字符串
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            f"?sslmode={ssl_mode}"
        )
        
        # 创建连接池
        start_time = time.time()
        pool = await asyncpg.create_pool(
            conn_string,
            min_size=3,
            max_size=8,
            command_timeout=60
        )
        pool_creation_time = time.time() - start_time
        
        print(f"✅ 连接池创建成功，耗时: {pool_creation_time:.4f}秒")
        
        # 测试并发查询
        async def single_query():
            async with pool.acquire() as conn:
                return await conn.fetchval("SELECT 1")
        
        # 执行5个并发查询
        start_time = time.time()
        tasks = [single_query() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        print(f"✅ 5个并发查询完成，总耗时: {total_time:.4f}秒")
        print(f"   平均每个查询: {total_time/5:.4f}秒")
        print(f"   每秒查询数: {5/total_time:.2f}")
        
        await pool.close()
        return pool_creation_time, total_time/5
        
    except Exception as e:
        print(f"❌ 连接池测试失败: {str(e)}")
        return None, None

async def main():
    """主函数"""
    print("="*60)
    print("SSL模式对数据库连接性能的影响测试")
    print("="*60)
    
    results = {}
    
    # 测试1: SSL禁用
    conn_time_disable, query_time_disable = await test_connection_with_ssl_mode("disable", "SSL禁用")
    pool_time_disable, avg_query_disable = await test_connection_pool_performance("disable", "SSL禁用")
    
    results["ssl_disable"] = {
        "connection_time": conn_time_disable,
        "query_time": query_time_disable,
        "pool_creation_time": pool_time_disable,
        "avg_query_time": avg_query_disable
    }
    
    # 测试2: SSL允许（不强制）
    conn_time_allow, query_time_allow = await test_connection_with_ssl_mode("allow", "SSL允许")
    pool_time_allow, avg_query_allow = await test_connection_pool_performance("allow", "SSL允许")
    
    results["ssl_allow"] = {
        "connection_time": conn_time_allow,
        "query_time": query_time_allow,
        "pool_creation_time": pool_time_allow,
        "avg_query_time": avg_query_allow
    }
    
    # 测试3: SSL要求（如果可用）
    conn_time_prefer, query_time_prefer = await test_connection_with_ssl_mode("prefer", "SSL优先")
    pool_time_prefer, avg_query_prefer = await test_connection_pool_performance("prefer", "SSL优先")
    
    results["ssl_prefer"] = {
        "connection_time": conn_time_prefer,
        "query_time": query_time_prefer,
        "pool_creation_time": pool_time_prefer,
        "avg_query_time": avg_query_prefer
    }
    
    # 性能对比报告
    print("\n" + "="*60)
    print("📊 性能对比报告")
    print("="*60)
    
    if all(results["ssl_disable"].values()):
        print("SSL禁用模式:")
        print(f"  连接时间: {results['ssl_disable']['connection_time']:.4f}秒")
        print(f"  查询时间: {results['ssl_disable']['query_time']:.4f}秒")
        print(f"  连接池创建: {results['ssl_disable']['pool_creation_time']:.4f}秒")
        print(f"  平均查询: {results['ssl_disable']['avg_query_time']:.4f}秒")
    
    if all(results["ssl_allow"].values()):
        print("\nSSL允许模式:")
        print(f"  连接时间: {results['ssl_allow']['connection_time']:.4f}秒")
        print(f"  查询时间: {results['ssl_allow']['query_time']:.4f}秒")
        print(f"  连接池创建: {results['ssl_allow']['pool_creation_time']:.4f}秒")
        print(f"  平均查询: {results['ssl_allow']['avg_query_time']:.4f}秒")
    
    if all(results["ssl_prefer"].values()):
        print("\nSSL优先模式:")
        print(f"  连接时间: {results['ssl_prefer']['connection_time']:.4f}秒")
        print(f"  查询时间: {results['ssl_prefer']['query_time']:.4f}秒")
        print(f"  连接池创建: {results['ssl_prefer']['pool_creation_time']:.4f}秒")
        print(f"  平均查询: {results['ssl_prefer']['avg_query_time']:.4f}秒")
    
    # 性能提升分析
    if all(results["ssl_disable"].values()) and all(results["ssl_prefer"].values()):
        conn_improvement = ((results['ssl_prefer']['connection_time'] - results['ssl_disable']['connection_time']) / results['ssl_prefer']['connection_time']) * 100
        query_improvement = ((results['ssl_prefer']['query_time'] - results['ssl_disable']['query_time']) / results['ssl_prefer']['query_time']) * 100
        
        print(f"\n💡 性能提升分析:")
        print(f"  SSL禁用相比SSL优先:")
        print(f"    连接时间提升: {conn_improvement:.1f}%")
        print(f"    查询时间提升: {query_improvement:.1f}%")
    
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main()) 