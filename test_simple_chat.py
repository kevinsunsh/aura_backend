#!/usr/bin/env python3
"""
简化版聊天功能测试脚本
用于快速测试单个聊天功能
"""

import asyncio
import aiohttp
import json
import time

# 测试配置
BASE_URL = "http://localhost:5876"
TEST_USER_ID = "test_user_001"

async def test_simple_chat():
    """测试简单的HTTP聊天"""
    print("🚀 测试简单HTTP聊天")
    
    url = f"{BASE_URL}/chat"
    payload = {
        "user_id": TEST_USER_ID
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            async with session.post(url, json=payload) as response:
                result = await response.json()
                end_time = time.time()
                
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"响应状态: {result.get('status')}")
                print(f"用户ID: {result.get('user_id')}")
                print(f"响应内容: {result.get('response', '')[:200]}...")
                
                if result.get("status") == "success":
                    print("✅ 测试成功")
                else:
                    print("❌ 测试失败")
                    
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")

async def test_stream_chat():
    """测试流式HTTP聊天"""
    print("\n🚀 测试流式HTTP聊天")
    
    url = f"{BASE_URL}/chat/stream"
    payload = {
        "user_id": TEST_USER_ID
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            async with session.post(url, json=payload) as response:
                result = await response.json()
                end_time = time.time()
                
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"响应状态: {result.get('status')}")
                print(f"响应片段数量: {len(result.get('responses', []))}")
                print(f"完整响应长度: {len(result.get('full_response', ''))}")
                print(f"完整响应内容: {result.get('full_response', '')[:200]}...")
                
                if result.get("status") == "success":
                    print("✅ 测试成功")
                else:
                    print("❌ 测试失败")
                    
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")

async def test_health():
    """测试健康检查"""
    print("\n🚀 测试健康检查")
    
    url = f"{BASE_URL}/health"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                print(f"响应状态: {result.get('status')}")
                
                if result.get("status") == "healthy":
                    print("✅ 服务健康")
                else:
                    print("❌ 服务异常")
                    
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")

async def main():
    """主函数"""
    print("=" * 50)
    print("简化版聊天功能测试")
    print("=" * 50)
    
    # 测试健康检查
    await test_health()
    
    # 测试简单聊天
    await test_simple_chat()
    
    # 测试流式聊天
    await test_stream_chat()
    
    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main()) 