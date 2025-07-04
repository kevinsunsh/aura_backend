#!/usr/bin/env python3
"""
测试连接和session生命周期管理
展示客户端如何按照正确的流程与服务端通信：
1. start_connection
2. start_session  
3. 发送业务消息（文本/音频）
4. end_session
5. end_connection
"""

import asyncio
import websockets
import json
import gzip
import logging
import sys
import os
import signal

# 设置项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from agents.doubao_client import protocol

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SessionLifecycleClient:
    def __init__(self, uri: str, chat_id: str):
        self.uri = uri
        self.chat_id = chat_id
        self.websocket = None
        self.running = True
        
    def construct_protocol_message(self, action: str, data: dict = None) -> bytes:
        """构造协议格式的二进制消息"""
        try:
            # 构造payload
            payload_data = {"action": action}
            if data:
                payload_data.update(data)
                
            # JSON序列化并压缩
            payload_bytes = str.encode(json.dumps(payload_data))
            payload_bytes = gzip.compress(payload_bytes)
            
            # 构造协议头
            request = bytearray(protocol.generate_header(
                message_type=protocol.CLIENT_FULL_REQUEST,
                message_type_specific_flags=protocol.MSG_WITH_EVENT,
                serial_method=protocol.JSON,
                compression_type=protocol.GZIP
            ))
            
            # 添加事件ID (4 bytes) - 使用默认值
            request.extend(int(1001).to_bytes(4, 'big'))
            
            # 添加session ID
            session_id_bytes = str.encode(self.chat_id)
            request.extend(len(session_id_bytes).to_bytes(4, 'big', signed=True))
            request.extend(session_id_bytes)
            
            # 添加payload
            request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            request.extend(payload_bytes)
            
            return bytes(request)
            
        except Exception as e:
            logger.error(f"构造协议消息失败: {e}")
            return b''

    def send_audio_message(self, audio_data: bytes) -> bytes:
        """发送音频消息（使用gzip压缩）"""
        try:
            # 压缩音频数据
            compressed_audio = gzip.compress(audio_data)
            
            # 构造协议头
            request = bytearray(protocol.generate_header(
                message_type=protocol.CLIENT_FULL_REQUEST,
                message_type_specific_flags=protocol.MSG_WITH_EVENT,
                serial_method=protocol.NO_SERIALIZATION,
                compression_type=protocol.GZIP
            ))
            
            # 添加事件ID (4 bytes)
            request.extend(int(1002).to_bytes(4, 'big'))
            
            # 添加session ID
            session_id_bytes = str.encode(self.chat_id)
            request.extend(len(session_id_bytes).to_bytes(4, 'big', signed=True))
            request.extend(session_id_bytes)
            
            # 添加压缩的音频数据
            request.extend((len(compressed_audio)).to_bytes(4, 'big'))
            request.extend(compressed_audio)
            
            return bytes(request)
            
        except Exception as e:
            logger.error(f"构造音频消息失败: {e}")
            return b''

    async def parse_server_response(self, data: bytes) -> dict:
        """解析服务端响应 - 使用统一的协议解析函数"""
        try:
            # 导入统一的协议解析函数
            import sys
            import os
            sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
            from agents.doubao_client.protocol import parse_response
            
            result = parse_response(data)
            return result
                
        except Exception as e:
            return {"error": f"解析失败: {e}"}

    async def start_connection(self):
        """第一步：发送开始连接消息"""
        logger.info("发送开始连接消息...")
        message = self.construct_protocol_message("start_connection")
        await self.websocket.send(message)
        
        # 等待服务端确认
        response_data = await self.websocket.recv()
        response = await self.parse_server_response(response_data)
        
        if response.get("status") == "connected":
            logger.info("✅ 连接已建立")
            return True
        else:
            logger.error(f"❌ 连接建立失败: {response}")
            return False

    async def start_session(self):
        """第二步：发送开始session消息"""
        logger.info("发送开始session消息...")
        message = self.construct_protocol_message("start_session", {"chat_id": self.chat_id})
        await self.websocket.send(message)
        
        # 等待服务端确认
        response_data = await self.websocket.recv()
        response = await self.parse_server_response(response_data)
        
        if response.get("status") == "started":
            logger.info(f"✅ Session已开始: {response.get('chat_id')}")
            return True
        else:
            logger.error(f"❌ Session开始失败: {response}")
            return False

    async def send_text_message(self, text: str):
        """发送文本消息"""
        logger.info(f"发送文本消息: {text}")
        message = self.construct_protocol_message("text_message", {"message": text})
        await self.websocket.send(message)

    async def send_audio_data(self, audio_data: bytes):
        """发送音频数据"""
        logger.info(f"发送音频数据: {len(audio_data)} 字节")
        message = self.send_audio_message(audio_data)
        await self.websocket.send(message)

    async def end_session(self):
        """第三步：发送结束session消息"""
        logger.info("发送结束session消息...")
        message = self.construct_protocol_message("end_session")
        await self.websocket.send(message)
        
        # 等待服务端确认
        try:
            response_data = await asyncio.wait_for(self.websocket.recv(), timeout=3.0)
            response = await self.parse_server_response(response_data)
            
            if response.get("status") == "ended":
                logger.info("✅ Session已结束")
                return True
            else:
                logger.warning(f"⚠️ Session结束响应异常: {response}")
                return True  # 继续流程
        except asyncio.TimeoutError:
            logger.warning("⚠️ 等待session结束确认超时")
            return True

    async def end_connection(self):
        """第四步：发送结束连接消息"""
        logger.info("发送结束连接消息...")
        message = self.construct_protocol_message("end_connection")
        await self.websocket.send(message)
        
        # 等待服务端确认
        try:
            response_data = await asyncio.wait_for(self.websocket.recv(), timeout=3.0)
            response = await self.parse_server_response(response_data)
            
            if response.get("status") == "ended":
                logger.info("✅ 连接已结束")
                return True
            else:
                logger.warning(f"⚠️ 连接结束响应异常: {response}")
                return True
        except asyncio.TimeoutError:
            logger.warning("⚠️ 等待连接结束确认超时")
            return True

    async def listen_for_responses(self):
        """监听服务端响应"""
        try:
            while self.running:
                try:
                    response_data = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                    response = await self.parse_server_response(response_data)
                    
                    event = response.get("event", "unknown")
                    logger.info(f"收到服务端响应: {event}")
                    
                    if event in ["ASRResponse", "TTSResponse", "ChatResponse"]:
                        payload = response.get("payload_msg", {})
                        if "text" in payload:
                            logger.info(f"📄 文本响应: {payload['text']}")
                        if "audio_data" in payload:
                            logger.info(f"🔊 音频响应: {len(payload['audio_data'])} 字节")
                    
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if self.running:
                        logger.debug(f"接收响应时出错: {e}")
                    break
                    
        except Exception as e:
            logger.debug(f"监听响应时出错: {e}")

    async def run_demo(self):
        """运行完整的session生命周期演示"""
        try:
            # 连接WebSocket
            logger.info(f"连接到服务器: {self.uri}")
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                
                # 启动响应监听任务
                listen_task = asyncio.create_task(self.listen_for_responses())
                
                try:
                    # 第一步：开始连接
                    if not await self.start_connection():
                        return
                    
                    # 第二步：开始session
                    if not await self.start_session():
                        return
                    
                    # 第三步：发送业务消息
                    logger.info("开始发送业务消息...")
                    
                    # 发送文本消息
                    await self.send_text_message("你好，我是测试客户端")
                    await asyncio.sleep(1)
                    
                    # 发送音频消息（模拟音频数据）
                    fake_audio = b"fake_audio_data_" * 100  # 模拟音频数据
                    await self.send_audio_data(fake_audio)
                    await asyncio.sleep(1)
                    
                    # 再发送一条文本消息
                    await self.send_text_message("session生命周期测试完成")
                    await asyncio.sleep(2)
                    
                    # 第四步：结束session
                    await self.end_session()
                    
                    # 第五步：结束连接
                    await self.end_connection()
                    
                    logger.info("🎉 Session生命周期测试完成！")
                    
                finally:
                    # 停止监听任务
                    self.running = False
                    if not listen_task.done():
                        listen_task.cancel()
                        try:
                            await listen_task
                        except asyncio.CancelledError:
                            pass
                
        except Exception as e:
            logger.error(f"测试过程中出错: {e}")

def signal_handler(signum, frame):
    logger.info("收到中断信号，正在退出...")
    sys.exit(0)

async def main():
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 配置连接参数
    uri = "ws://localhost:8001/ws/test_chat_123"
    chat_id = "test_chat_123"
    
    # 创建客户端并运行演示
    client = SessionLifecycleClient(uri, chat_id)
    await client.run_demo()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出: {e}") 