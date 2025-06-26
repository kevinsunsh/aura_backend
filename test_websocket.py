#!/usr/bin/env python3
import asyncio
import websockets
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_websocket_stream():
    """测试WebSocket流式接口"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            
            # 发送测试消息
            test_message = {
                "message": "你好，请介绍一下你自己"
            }
            
            logger.info(f"发送消息: {test_message}")
            await websocket.send(json.dumps(test_message))
            
            # 接收流式响应
            full_response = ""
            chunk_count = 0
            
            while True:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    logger.info(f"收到响应: {data}")
                    
                    if data["type"] == "start":
                        logger.info("开始处理消息...")
                    elif data["type"] == "stream_chunk":
                        chunk_count += 1
                        content = data["content"]
                        full_response += content
                        logger.info(f"收到第{chunk_count}个内容片段: '{content}'")
                        # 实时打印内容（不换行）
                        print(content, end="", flush=True)
                    elif data["type"] == "end":
                        logger.info("处理完成")
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    break
            
            print("\n")  # 换行
            logger.info(f"总共收到 {chunk_count} 个内容片段")
            logger.info(f"完整响应: {full_response}")
            
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_websocket_stream()) 