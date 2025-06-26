#!/usr/bin/env python3
"""
Streaming聊天功能测试脚本
测试HTTP和WebSocket两种方式的streaming聊天
"""

import asyncio
import aiohttp
import websockets
import json
import time
from typing import List, Dict, Any

# 测试配置
BASE_URL = "http://localhost:5876"
WS_BASE_URL = "ws://localhost:5876"
TEST_USER_ID = "test_user_001"

class StreamingChatTester:
    def __init__(self):
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_http_chat(self):
        """测试HTTP普通聊天接口"""
        print("=" * 50)
        print("测试 HTTP 普通聊天接口")
        print("=" * 50)
        
        url = f"{BASE_URL}/chat"
        payload = {
            "user_id": TEST_USER_ID
        }
        
        try:
            start_time = time.time()
            async with self.session.post(url, json=payload) as response:
                result = await response.json()
                end_time = time.time()
                
                print(f"响应状态码: {response.status}")
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get("status") == "success":
                    print("✅ HTTP普通聊天测试成功")
                else:
                    print("❌ HTTP普通聊天测试失败")
                    
        except Exception as e:
            print(f"❌ HTTP普通聊天测试异常: {str(e)}")
    
    async def test_http_stream_chat(self):
        """测试HTTP流式聊天接口"""
        print("\n" + "=" * 50)
        print("测试 HTTP 流式聊天接口")
        print("=" * 50)
        
        url = f"{BASE_URL}/chat/stream"
        payload = {
            "user_id": TEST_USER_ID
        }
        
        try:
            start_time = time.time()
            async with self.session.post(url, json=payload) as response:
                result = await response.json()
                end_time = time.time()
                
                print(f"响应状态码: {response.status}")
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get("status") == "success":
                    print(f"✅ HTTP流式聊天测试成功")
                    print(f"   响应片段数量: {len(result.get('responses', []))}")
                    print(f"   完整响应长度: {len(result.get('full_response', ''))}")
                else:
                    print("❌ HTTP流式聊天测试失败")
                    
        except Exception as e:
            print(f"❌ HTTP流式聊天测试异常: {str(e)}")
    
    async def test_websocket_chat(self):
        """测试WebSocket普通聊天"""
        print("\n" + "=" * 50)
        print("测试 WebSocket 普通聊天")
        print("=" * 50)
        
        url = f"{WS_BASE_URL}/ws/{TEST_USER_ID}"
        
        try:
            async with websockets.connect(url) as websocket:
                # 发送消息
                message = {
                    "message": "你好，请介绍一下你自己"
                }
                
                print(f"发送消息: {json.dumps(message, ensure_ascii=False)}")
                await websocket.send(json.dumps(message))
                
                # 接收响应
                responses = []
                start_time = time.time()
                
                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                        data = json.loads(response)
                        responses.append(data)
                        
                        print(f"收到消息: {json.dumps(data, ensure_ascii=False)}")
                        
                        # 如果收到结束消息，退出循环
                        if data.get("type") == "end":
                            break
                            
                    except asyncio.TimeoutError:
                        print("⚠️ 接收响应超时")
                        break
                
                end_time = time.time()
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"收到消息数量: {len(responses)}")
                
                # 检查是否有成功响应
                success_responses = [r for r in responses if r.get("type") == "response"]
                if success_responses:
                    print("✅ WebSocket普通聊天测试成功")
                else:
                    print("❌ WebSocket普通聊天测试失败")
                    
        except Exception as e:
            print(f"❌ WebSocket普通聊天测试异常: {str(e)}")
    
    async def test_websocket_stream_chat(self):
        """测试WebSocket流式聊天"""
        print("\n" + "=" * 50)
        print("测试 WebSocket 流式聊天")
        print("=" * 50)
        
        url = f"{WS_BASE_URL}/ws/stream/{TEST_USER_ID}"
        
        try:
            async with websockets.connect(url) as websocket:
                # 发送消息
                message = {
                    "message": "请详细介绍一下人工智能的发展历史"
                }
                
                print(f"发送消息: {json.dumps(message, ensure_ascii=False)}")
                await websocket.send(json.dumps(message))
                
                # 接收响应
                responses = []
                stream_segments = []
                start_time = time.time()
                
                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                        data = json.loads(response)
                        responses.append(data)
                        
                        print(f"收到消息: {json.dumps(data, ensure_ascii=False)}")
                        
                        # 收集流式片段
                        if data.get("type") == "stream_segment":
                            stream_segments.append(data)
                        
                        # 如果收到结束消息，退出循环
                        if data.get("type") == "end":
                            break
                            
                    except asyncio.TimeoutError:
                        print("⚠️ 接收响应超时")
                        break
                
                end_time = time.time()
                print(f"响应时间: {end_time - start_time:.2f}秒")
                print(f"收到消息数量: {len(responses)}")
                print(f"流式片段数量: {len(stream_segments)}")
                
                # 检查是否有成功响应
                full_responses = [r for r in responses if r.get("type") == "full_response"]
                if full_responses:
                    print("✅ WebSocket流式聊天测试成功")
                else:
                    print("❌ WebSocket流式聊天测试失败")
                    
        except Exception as e:
            print(f"❌ WebSocket流式聊天测试异常: {str(e)}")
    
    async def test_health_check(self):
        """测试健康检查接口"""
        print("\n" + "=" * 50)
        print("测试健康检查接口")
        print("=" * 50)
        
        url = f"{BASE_URL}/health"
        
        try:
            async with self.session.get(url) as response:
                result = await response.json()
                print(f"响应状态码: {response.status}")
                print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if response.status == 200 and result.get("status") == "healthy":
                    print("✅ 健康检查测试成功")
                else:
                    print("❌ 健康检查测试失败")
                    
        except Exception as e:
            print(f"❌ 健康检查测试异常: {str(e)}")
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始运行Streaming聊天功能测试")
        print(f"测试用户ID: {TEST_USER_ID}")
        print(f"服务器地址: {BASE_URL}")
        
        # 测试健康检查
        await self.test_health_check()
        
        # 测试HTTP接口
        await self.test_http_chat()
        await self.test_http_stream_chat()
        
        # 测试WebSocket接口
        await self.test_websocket_chat()
        await self.test_websocket_stream_chat()
        
        print("\n" + "=" * 50)
        print("🎉 所有测试完成")
        print("=" * 50)

async def main():
    """主函数"""
    async with StreamingChatTester() as tester:
        await tester.run_all_tests()

if __name__ == "__main__":
    # 运行测试
    asyncio.run(main()) 