#!/usr/bin/env python3
"""
WebSocket聊天功能测试脚本
专门测试WebSocket聊天功能
"""

import asyncio
import websockets
import json
import time

# 测试配置
WS_BASE_URL = "ws://localhost:5876"
TEST_USER_ID = "test_user_001"

async def test_websocket_simple_chat():
    """测试WebSocket简单聊天"""
    print("🚀 测试WebSocket简单聊天")
    
    url = f"{WS_BASE_URL}/ws/{TEST_USER_ID}"
    
    try:
        async with websockets.connect(url) as websocket:
            # 发送消息
            message = {
                "message": "你好，请简单介绍一下你自己"
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
                    
                    print(f"收到消息类型: {data.get('type')}")
                    if data.get("type") == "response":
                        print(f"AI响应: {data.get('message', '')[:100]}...")
                    
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
                print("✅ WebSocket简单聊天测试成功")
            else:
                print("❌ WebSocket简单聊天测试失败")
                
    except Exception as e:
        print(f"❌ WebSocket简单聊天测试异常: {str(e)}")

async def test_websocket_stream_chat():
    """测试WebSocket流式聊天"""
    print("\n🚀 测试WebSocket流式聊天")
    
    url = f"{WS_BASE_URL}/ws/stream/{TEST_USER_ID}"
    
    try:
        async with websockets.connect(url) as websocket:
            # 发送消息
            message = {
                "message": "请详细介绍一下人工智能的发展历程和未来趋势"
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
                    
                    print(f"收到消息类型: {data.get('type')}")
                    
                    if data.get("type") == "full_response":
                        print(f"完整响应: {data.get('message', '')[:100]}...")
                    elif data.get("type") == "stream_segment":
                        stream_segments.append(data)
                        print(f"流式片段 {data.get('segment_index')}: {data.get('message', '')[:50]}...")
                    
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

async def test_websocket_error_handling():
    """测试WebSocket错误处理"""
    print("\n🚀 测试WebSocket错误处理")
    
    url = f"{WS_BASE_URL}/ws/{TEST_USER_ID}"
    
    try:
        async with websockets.connect(url) as websocket:
            # 发送错误格式的消息
            message = {
                "wrong_field": "这是一个错误格式的消息"
            }
            
            print(f"发送错误格式消息: {json.dumps(message, ensure_ascii=False)}")
            await websocket.send(json.dumps(message))
            
            # 接收响应
            responses = []
            
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    data = json.loads(response)
                    responses.append(data)
                    
                    print(f"收到消息类型: {data.get('type')}")
                    if data.get("type") == "error":
                        print(f"错误消息: {data.get('message')}")
                    
                    # 如果收到结束消息，退出循环
                    if data.get("type") == "end":
                        break
                        
                except asyncio.TimeoutError:
                    print("⚠️ 接收响应超时")
                    break
            
            print(f"收到消息数量: {len(responses)}")
            
            # 检查是否有错误响应
            error_responses = [r for r in responses if r.get("type") == "error"]
            if error_responses:
                print("✅ WebSocket错误处理测试成功")
            else:
                print("❌ WebSocket错误处理测试失败")
                
    except Exception as e:
        print(f"❌ WebSocket错误处理测试异常: {str(e)}")

async def main():
    """主函数"""
    print("=" * 50)
    print("WebSocket聊天功能测试")
    print("=" * 50)
    
    # 测试WebSocket简单聊天
    await test_websocket_simple_chat()
    
    # 测试WebSocket流式聊天
    await test_websocket_stream_chat()
    
    # 测试WebSocket错误处理
    await test_websocket_error_handling()
    
    print("\n" + "=" * 50)
    print("WebSocket测试完成")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main()) 