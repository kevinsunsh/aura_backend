#!/usr/bin/env python3
"""
PostgreSQL数据库初始化脚本
用于设置LangGraph checkpoint所需的数据库和表结构
"""

import asyncio
import asyncpg
from src.config import settings

async def init_database():
    """初始化PostgreSQL数据库"""
    try:
        # 连接到PostgreSQL服务器（不指定数据库名）
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database='postgres'  # 连接到默认数据库
        )
        
        # 检查数据库是否存在
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            settings.POSTGRES_DB
        )
        
        if not db_exists:
            print(f"创建数据库: {settings.POSTGRES_DB}")
            await conn.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
            print(f"数据库 {settings.POSTGRES_DB} 创建成功")
        else:
            print(f"数据库 {settings.POSTGRES_DB} 已存在")
        
        await conn.close()
        
        # 连接到新创建的数据库
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB
        )
        
        # 检查schema是否存在
        schema_exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
            settings.POSTGRES_SCHEMA
        )
        
        if not schema_exists:
            print(f"创建schema: {settings.POSTGRES_SCHEMA}")
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{settings.POSTGRES_SCHEMA}"')
            print(f"Schema {settings.POSTGRES_SCHEMA} 创建成功")
        else:
            print(f"Schema {settings.POSTGRES_SCHEMA} 已存在")
        
        await conn.close()
        print("PostgreSQL数据库初始化完成")
        
    except Exception as e:
        print(f"数据库初始化失败: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(init_database()) 