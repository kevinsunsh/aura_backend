#!/usr/bin/env python3
"""
快速数据库测试脚本
"""

import asyncio
import time
import sys
import os
import urllib.parse

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.aura_memory.database.database import Database, AsyncDatabase
from src.config import settings
from sqlalchemy import text

def test_sync_db():
    """测试同步数据库"""
    print("🔧 测试同步数据库...")
    
    try:
        # 正确处理密码
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        
        # 创建数据库对象
        db = Database(db_conn_string)
        print("✅ 同步数据库对象创建成功")
        
        # 测试查询
        with db.get_session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            print(f"✅ 同步查询成功: {result}")
        
        # 测试连接池信息
        pool_info = db.get_connection_info()
        print(f"✅ 连接池信息: {pool_info}")
        
        # 关闭连接
        db.close()
        print("✅ 同步数据库关闭成功")
        
        return True
        
    except Exception as e:
        print(f"❌ 同步数据库测试失败: {e}")
        return False

async def test_async_db():
    """测试异步数据库"""
    print("\n🔧 测试异步数据库...")
    
    try:
        # 正确处理密码
        encoded_password = urllib.parse.quote_plus(settings.POSTGRES_PASSWORD)
        db_conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{encoded_password}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        
        # 创建数据库对象
        async_db = AsyncDatabase(db_conn_string)
        print("✅ 异步数据库对象创建成功")
        
        # 测试查询
        result = await async_db.fetchval("SELECT 1")
        print(f"✅ 异步查询成功: {result}")
        
        # 测试连接池信息
        pool_info = await async_db.get_pool_info()
        print(f"✅ 异步连接池信息: {pool_info}")
        
        # 关闭连接
        await async_db.close()
        print("✅ 异步数据库关闭成功")
        
        return True
        
    except Exception as e:
        print(f"❌ 异步数据库测试失败: {e}")
        return False

async def main():
    """主函数"""
    print("🚀 快速数据库测试")
    print("="*40)
    
    # 测试同步数据库
    sync_success = test_sync_db()
    
    # 测试异步数据库
    async_success = await test_async_db()
    
    print("\n" + "="*40)
    if sync_success and async_success:
        print("🎉 所有测试通过！")
        return 0
    else:
        print("⚠️ 部分测试失败")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"💥 测试错误: {e}")
        sys.exit(1) 