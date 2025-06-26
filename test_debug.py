#!/usr/bin/env python3
"""
调试测试脚本
"""

import asyncio
import aiohttp
import json

async def test_debug():
    """调试测试"""
    print("🚀 开始调试测试")
    
    # 测试配置
    base_url = "http://localhost:5876"
    test_user_id = "test_user_001"
    
    # 测试普通聊天并查看详细错误
    print("\n测试普通聊天（调试模式）")
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "user_id": test_user_id
            }
            
            print(f"发送请求到: {base_url}/chat")
            print(f"请求数据: {json.dumps(payload, ensure_ascii=False)}")
            
            async with session.post(f"{base_url}/chat", json=payload) as response:
                print(f"响应状态码: {response.status}")
                print(f"响应头: {dict(response.headers)}")
                
                result = await response.json()
                print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get("status") == "success":
                    print("✅ 聊天测试成功")
                else:
                    print("❌ 聊天测试失败")
                    print(f"错误信息: {result.get('response', '')}")
                    
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_debug()) 