#!/usr/bin/env python3
import asyncio
import websockets
import json
import logging
import time
import base64
import jieba
from statistics import mean, median

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def split_message_with_jieba(message: str, max_chunk_length: int = 10) -> list:
    """
    使用jieba分词将消息切分成多个片段
    """
    # 使用jieba进行分词
    words = list(jieba.cut(message))
    
    chunks = []
    current_chunk = ""
    
    for word in words:
        # 如果当前片段加上新词不超过最大长度，就添加到当前片段
        if len(current_chunk + word) <= max_chunk_length:
            current_chunk += word
        else:
            # 如果当前片段不为空，保存它
            if current_chunk:
                chunks.append(current_chunk)
            # 开始新的片段
            current_chunk = word
    
    # 添加最后一个片段
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks

async def test_websocket_stream():
    """测试WebSocket流式接口"""
    # uri = "ws://sd1ejsni9optek6ooa8ng.apigateway-cn-beijing.volceapi.com/ws/stream/test_user_123"
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 延迟统计变量
    send_time = None
    first_response_delay = None
    delays = []
    chunk_times = []
    
    # 响应处理状态
    response_completed = False
    full_response = ""
    chunk_count = 0
    first_response_received = False
    
    async def receive_messages(websocket):
        """异步接收消息的任务"""
        nonlocal response_completed, full_response, chunk_count, first_response_received, first_response_delay, delays, chunk_times
        
        try:
            while not response_completed:
                try:
                    # 检查WebSocket连接状态
                    if hasattr(websocket, 'closed') and websocket.closed:
                        logger.info("WebSocket连接已关闭，停止接收")
                        response_completed = True
                        break
                    
                    response = await websocket.recv()
                    receive_time = time.time()  # 记录接收时间
                    data = json.loads(response)
                    
                    # 计算从发送到第一个响应的延迟
                    if data["type"] == "stream_chunk":
                        if not first_response_received and send_time:
                            first_response_delay = (receive_time - send_time) * 1000  # 转换为毫秒
                            first_response_received = True
                            logger.info(f"=== 关键延迟指标 ===")
                            logger.info(f"发送到第一个响应的延迟: {first_response_delay:.2f}ms")
                    
                    logger.info(f"收到响应: {data}")
                    
                    if data["type"] == "start":
                        logger.info("开始处理消息...")
                        start_time = receive_time
                    elif data["type"] == "stream_chunk":
                        chunk_count += 1
                        content = data["content"]
                        full_response += content
                        
                        # 计算每个片段的延迟
                        if send_time:
                            delay = (receive_time - send_time) * 1000  # 转换为毫秒
                            delays.append(delay)
                        else:
                            delay = 0
                            delays.append(delay)
                        
                        chunk_times.append(receive_time)
                        logger.info(f"收到第{chunk_count}个内容片段: '{content}' (延迟: {delay:.2f}ms)")
                        # 实时打印内容（不换行）
                        print(content, end="", flush=True)
                    elif data["type"] == "end":
                        end_time = receive_time
                        logger.info("处理完成")
                        response_completed = True
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        response_completed = True
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    response_completed = True
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭")
                    response_completed = True
                    break
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("WebSocket连接正常关闭")
                    response_completed = True
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止接收")
                        response_completed = True
                        break
                    response_completed = True
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            response_completed = True
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            
            # 启动接收消息的异步任务
            receive_task = asyncio.create_task(receive_messages(websocket))
            
            # 测试消息 - 将被jieba切分
            full_message = "你好，请介绍一下你自己，我想了解你的功能和特点"
            message_chunks = split_message_with_jieba(full_message, max_chunk_length=8)
            
            logger.info(f"原始消息: {full_message}")
            logger.info(f"切分后的片段: {message_chunks}")
            
            # 逐段发送消息
            for i, chunk in enumerate(message_chunks):
                logger.info(f"发送第{i+1}段消息: '{chunk}'")
                
                test_message = {
                    "message": chunk,
                    # "audio": "base64编码的音频数据",  # 可选：音频数据
                    # "audio_format": "wav"  # 可选：音频格式
                }
                
                # 记录第一段消息的发送时间
                if i == len(message_chunks) - 1:
                    send_time = time.time()
                
                await websocket.send(json.dumps(test_message))
                
                # 等待一小段时间再发送下一段（模拟用户输入）
                if i < len(message_chunks) - 1:
                    await asyncio.sleep(1.5)  # 1.5秒间隔
            
            # 等待接收任务完成
            await receive_task
            
            print("\n")  # 换行
            logger.info(f"总共收到 {chunk_count} 个内容片段")
            logger.info(f"完整响应: {full_response}")
            
            # 输出延迟统计信息
            if first_response_delay is not None:
                logger.info("=== 延迟统计总结 ===")
                logger.info(f"🚀 关键指标 - 发送到第一个响应延迟: {first_response_delay:.2f}ms")
                
            if delays:
                logger.info(f"📊 总体延迟统计:")
                logger.info(f"   总延迟: {delays[-1]:.2f}ms")
                logger.info(f"   平均延迟: {mean(delays):.2f}ms")
                logger.info(f"   中位数延迟: {median(delays):.2f}ms")
                logger.info(f"   最小延迟: {min(delays):.2f}ms")
                logger.info(f"   最大延迟: {max(delays):.2f}ms")
                
                # 计算片段间延迟
                if len(chunk_times) > 1:
                    chunk_delays = []
                    for i in range(1, len(chunk_times)):
                        chunk_delay = (chunk_times[i] - chunk_times[i-1]) * 1000
                        chunk_delays.append(chunk_delay)
                    
                    logger.info("📈 片段间延迟统计:")
                    logger.info(f"   平均片段间延迟: {mean(chunk_delays):.2f}ms")
                    logger.info(f"   中位数片段间延迟: {median(chunk_delays):.2f}ms")
                    logger.info(f"   最小片段间延迟: {min(chunk_delays):.2f}ms")
                    logger.info(f"   最大片段间延迟: {max(chunk_delays):.2f}ms")
            
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")

async def test_interactive_chat():
    """交互式聊天测试，模拟用户逐段输入"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 响应处理状态
    response_completed = False
    current_response = ""
    
    async def receive_messages(websocket):
        """异步接收消息的任务"""
        nonlocal response_completed, current_response
        
        try:
            while not response_completed:
                try:
                    # 检查WebSocket连接状态
                    if hasattr(websocket, 'closed') and websocket.closed:
                        logger.info("WebSocket连接已关闭，停止接收")
                        response_completed = True
                        break
                    
                    response = await websocket.recv()
                    data = json.loads(response)
                    logger.info(f"收到响应: {data}")
                    
                    if data["type"] == "stream_chunk":
                        current_response += data['content']
                        print(f"AI回复: {data['content']}", end="", flush=True)
                    elif data["type"] == "end":
                        print("\n")
                        response_completed = True
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        response_completed = True
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    response_completed = True
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭")
                    response_completed = True
                    break
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("WebSocket连接正常关闭")
                    response_completed = True
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(f"接收响应失败: {str(e)}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止接收")
                        response_completed = True
                        break
                    response_completed = True
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            response_completed = True
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            
            # 模拟用户输入的多段消息
            user_inputs = [
                "你好",
                "我想了解一下",
                "你的功能",
                "和特点"
            ]
            
            for i, user_input in enumerate(user_inputs):
                logger.info(f"用户输入第{i+1}段: '{user_input}'")
                
                # 重置响应状态
                response_completed = False
                current_response = ""
                
                # 启动接收消息的异步任务
                receive_task = asyncio.create_task(receive_messages(websocket))
                
                test_message = {
                    "message": user_input
                }
                
                await websocket.send(json.dumps(test_message))
                
                # 等待响应完成
                await receive_task
                
                # 模拟用户思考时间
                if i < len(user_inputs) - 1:
                    await asyncio.sleep(2)
            
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")

async def test_audio_websocket_stream():
    """测试带音频输入的WebSocket流式接口"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 响应处理状态
    response_completed = False
    full_response = ""
    chunk_count = 0
    
    async def receive_messages(websocket):
        """异步接收消息的任务"""
        nonlocal response_completed, full_response, chunk_count
        
        try:
            while not response_completed:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    logger.info(f"收到响应: {data}")
                    
                    if data["type"] == "start":
                        logger.info("开始处理音频消息...")
                    elif data["type"] == "stream_chunk":
                        chunk_count += 1
                        content = data["content"]
                        full_response += content
                        logger.info(f"收到第{chunk_count}个内容片段: '{content}'")
                        print(content, end="", flush=True)
                    elif data["type"] == "end":
                        logger.info("音频处理完成")
                        response_completed = True
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        response_completed = True
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    response_completed = True
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    response_completed = True
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            response_completed = True
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            
            # 启动接收消息的异步任务
            receive_task = asyncio.create_task(receive_messages(websocket))
            
            # 创建示例音频数据（这里用空字符串代替，实际使用时应该是base64编码的音频）
            sample_audio_data = ""  # 实际使用时应该是 base64.b64encode(audio_bytes).decode()
            
            # 发送带音频的测试消息
            test_message = {
                "message": "请分析这段音频内容",
                "audio": sample_audio_data,
                "audio_format": "wav"
            }
            
            logger.info("发送带音频的消息...")
            await websocket.send(json.dumps(test_message))
            
            # 等待接收任务完成
            await receive_task
            
            print("\n")
            logger.info(f"音频处理总共收到 {chunk_count} 个内容片段")
            logger.info(f"完整响应: {full_response}")
            
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")

if __name__ == "__main__":
    # 测试jieba分词逐段输入
    print("=== 测试jieba分词逐段输入 ===")
    asyncio.run(test_websocket_stream())
    
    # 测试交互式聊天
    # print("\n=== 测试交互式聊天 ===")
    # asyncio.run(test_interactive_chat())
    
    # # 测试音频输入
    # print("\n=== 测试音频输入 ===")
    # asyncio.run(test_audio_websocket_stream()) 