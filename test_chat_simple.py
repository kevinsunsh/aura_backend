#!/usr/bin/env python3
"""
简单的聊天测试脚本
"""

import asyncio
import aiohttp
import json

async def test_chat():
    """测试聊天功能"""
    print("🚀 开始测试聊天功能")
    
    # 测试配置
    base_url = "http://localhost:5876"
    test_user_id = "test_user_001"
    
    # 测试健康检查
    print("\n1. 测试健康检查")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/health") as response:
                result = await response.json()
                print(f"健康检查结果: {result}")
                if result.get("status") == "healthy":
                    print("✅ 健康检查通过")
                else:
                    print("❌ 健康检查失败")
    except Exception as e:
        print(f"❌ 健康检查异常: {str(e)}")
        return
    
    # 测试普通聊天
    print("\n2. 测试普通聊天")
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "user_id": test_user_id
            }
            
            async with session.post(f"{base_url}/chat", json=payload) as response:
                result = await response.json()
                print(f"聊天响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get("status") == "success":
                    print("✅ 普通聊天测试成功")
                    print(f"响应内容: {result.get('response', '')[:100]}...")
                else:
                    print("❌ 普通聊天测试失败")
    except Exception as e:
        print(f"❌ 普通聊天测试异常: {str(e)}")
    
    # 测试流式聊天
    print("\n3. 测试流式聊天")
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "user_id": test_user_id
            }
            
            async with session.post(f"{base_url}/chat/stream", json=payload) as response:
                result = await response.json()
                print(f"流式聊天响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get("status") == "success":
                    print("✅ 流式聊天测试成功")
                    print(f"响应片段数量: {len(result.get('responses', []))}")
                    print(f"完整响应: {result.get('full_response', '')[:100]}...")
                else:
                    print("❌ 流式聊天测试失败")
    except Exception as e:
        print(f"❌ 流式聊天测试异常: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_chat()) 