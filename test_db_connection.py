#!/usr/bin/env python3
"""
数据库连接测试脚本
"""

import asyncio
import asyncpg
from src.config import settings

async def test_postgres_connection():
    """测试PostgreSQL连接"""
    print("🚀 开始测试PostgreSQL连接")
    
    try:
        # 测试连接到PostgreSQL服务器（不指定数据库）
        print(f"1. 连接到PostgreSQL服务器: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database='postgres'  # 连接到默认数据库
        )
        
        print("✅ 成功连接到PostgreSQL服务器")
        
        # 检查数据库是否存在
        print(f"2. 检查数据库是否存在: {settings.POSTGRES_DB}")
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            settings.POSTGRES_DB
        )
        
        if db_exists:
            print(f"✅ 数据库 {settings.POSTGRES_DB} 已存在")
        else:
            print(f"❌ 数据库 {settings.POSTGRES_DB} 不存在")
            print("3. 创建数据库...")
            await conn.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
            print(f"✅ 数据库 {settings.POSTGRES_DB} 创建成功")
        
        await conn.close()
        
        # 连接到新创建的数据库
        print(f"4. 连接到数据库: {settings.POSTGRES_DB}")
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB
        )
        
        print("✅ 成功连接到目标数据库")
        
        # 检查schema是否存在
        print(f"5. 检查schema是否存在: {settings.POSTGRES_SCHEMA}")
        schema_exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
            settings.POSTGRES_SCHEMA
        )
        
        if schema_exists:
            print(f"✅ Schema {settings.POSTGRES_SCHEMA} 已存在")
        else:
            print(f"❌ Schema {settings.POSTGRES_SCHEMA} 不存在")
            print("6. 创建schema...")
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{settings.POSTGRES_SCHEMA}"')
            print(f"✅ Schema {settings.POSTGRES_SCHEMA} 创建成功")
        
        await conn.close()
        print("✅ 数据库连接测试完成")
        
    except Exception as e:
        print(f"❌ 数据库连接测试失败: {str(e)}")
        raise

async def test_langgraph_checkpointer():
    """测试LangGraph checkpointer"""
    print("\n🚀 开始测试LangGraph checkpointer")
    
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        
        # 构建连接字符串
        conn_string = f"postgres://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}?sslmode=disable"
        
        print(f"连接字符串: {conn_string}")
        
        # 测试PostgresSaver
        with PostgresSaver.from_conn_string(conn_string) as checkpointer:
            print("✅ 成功创建PostgresSaver")
            
            # 调用setup方法
            checkpointer.setup()
            print("✅ 成功调用setup方法")
            
            print("✅ LangGraph checkpointer测试完成")
            
    except Exception as e:
        print(f"❌ LangGraph checkpointer测试失败: {str(e)}")
        raise

async def main():
    """主函数"""
    print("=" * 50)
    print("数据库连接测试")
    print("=" * 50)
    
    # 测试PostgreSQL连接
    await test_postgres_connection()
    
    # 测试LangGraph checkpointer
    await test_langgraph_checkpointer()
    
    print("\n" + "=" * 50)
    print("所有测试完成")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main()) 