#!/usr/bin/env python3
"""
测试音频客户端类型切换功能
"""

import asyncio
import logging
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.agents.message_processor_audio import (
    MessageProcessorAudio, 
    AudioClientType,
    AudioTaskType
)
from src.agents.aura_memory.message_store import MessageStore
from src.agents.aura_memory.chat_stream import ChatStream, ChatStreamManager
from src.configuration import ServerEventEnum

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MockMessageStore:
    """模拟消息存储"""
    def __init__(self):
        self.messages = []
    
    async def add_message(self, message):
        self.messages.append(message)
        logger.info(f"添加消息: {message.content[:50]}...")

class MockChatStream:
    """模拟聊天流"""
    def __init__(self, chat_id: str):
        self.chat_id = chat_id

class MockChatStreamManager:
    """模拟聊天流管理器"""
    def __init__(self):
        self.chat_streams = {}
    
    def get_chat_stream(self, chat_id: str) -> ChatStream:
        if chat_id not in self.chat_streams:
            self.chat_streams[chat_id] = MockChatStream(chat_id)
        return self.chat_streams[chat_id]

async def websocket_send_callback(message: dict):
    """模拟WebSocket发送回调"""
    event = message.get("event", "unknown")
    logger.info(f"WebSocket发送事件: {event}")
    
    if event == ServerEventEnum.ASRInfo.value:
        logger.info("收到ASR开始事件")
    elif event == ServerEventEnum.ASRResponse.value:
        text = message.get("payload_msg", {}).get("text", "")
        is_interim = message.get("payload_msg", {}).get("is_interim", False)
        logger.info(f"收到ASR响应: '{text}' (临时: {is_interim})")
    elif event == ServerEventEnum.ASREnded.value:
        logger.info("收到ASR结束事件")
    elif event == ServerEventEnum.TTSSentenceStart.value:
        text = message.get("payload_msg", {}).get("text", "")
        logger.info(f"收到TTS开始事件: '{text}'")
    elif event == ServerEventEnum.TTSResponse.value:
        audio_data = message.get("payload_msg", {}).get("audio_data", b"")
        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
    elif event == ServerEventEnum.TTSSentenceEnd.value:
        logger.info("收到TTS结束事件")

async def test_client_switching():
    """测试客户端类型切换功能"""
    logger.info("开始测试音频客户端类型切换功能")
    
    # 创建模拟组件
    message_store = MockMessageStore()
    chat_stream = MockChatStream("test_chat_001")
    chat_stream_manager = MockChatStreamManager()
    db_conn_string = "sqlite:///test.db"
    
    # 创建音频处理器，初始使用DialogSession
    audio_processor = MessageProcessorAudio(
        message_store=message_store,
        chat_stream=chat_stream,
        chat_stream_manager=chat_stream_manager,
        db_conn_string=db_conn_string,
        websocket_send_callback=websocket_send_callback,
        client_type=AudioClientType.DIALOG_SESSION
    )
    
    try:
        # 启动处理器
        logger.info("启动音频处理器...")
        await audio_processor.start()
        
        # 检查当前客户端类型
        current_type = audio_processor.get_current_client_type()
        logger.info(f"当前客户端类型: {current_type.value}")
        
        # 等待一段时间
        await asyncio.sleep(2)
        
        # 切换到单独的ASR/TTS客户端
        logger.info("切换到单独的ASR/TTS客户端...")
        success = await audio_processor.switch_client_type(AudioClientType.SEPARATE_CLIENTS)
        if success:
            logger.info("客户端类型切换成功")
        else:
            logger.error("客户端类型切换失败")
        
        # 检查切换后的客户端类型
        current_type = audio_processor.get_current_client_type()
        logger.info(f"切换后客户端类型: {current_type.value}")
        
        # 等待一段时间
        await asyncio.sleep(2)
        
        # 切换回DialogSession
        logger.info("切换回DialogSession...")
        success = await audio_processor.switch_client_type(AudioClientType.DIALOG_SESSION)
        if success:
            logger.info("客户端类型切换成功")
        else:
            logger.error("客户端类型切换失败")
        
        # 检查最终客户端类型
        current_type = audio_processor.get_current_client_type()
        logger.info(f"最终客户端类型: {current_type.value}")
        
        # 等待一段时间
        await asyncio.sleep(2)
        
    except Exception as e:
        logger.error(f"测试过程中出错: {e}")
    finally:
        # 清理资源
        logger.info("清理资源...")
        await audio_processor.cleanup()
        logger.info("测试完成")

async def test_different_client_types():
    """测试不同的客户端类型初始化"""
    logger.info("开始测试不同客户端类型的初始化")
    
    # 创建模拟组件
    message_store = MockMessageStore()
    chat_stream = MockChatStream("test_chat_002")
    chat_stream_manager = MockChatStreamManager()
    db_conn_string = "sqlite:///test.db"
    
    # 测试DialogSession类型
    logger.info("测试DialogSession类型...")
    audio_processor1 = MessageProcessorAudio(
        message_store=message_store,
        chat_stream=chat_stream,
        chat_stream_manager=chat_stream_manager,
        db_conn_string=db_conn_string,
        websocket_send_callback=websocket_send_callback,
        client_type=AudioClientType.DIALOG_SESSION
    )
    
    try:
        await audio_processor1.start()
        logger.info(f"DialogSession类型初始化成功: {audio_processor1.get_current_client_type().value}")
        await asyncio.sleep(1)
    finally:
        await audio_processor1.cleanup()
    
    # 测试单独的ASR/TTS客户端类型
    logger.info("测试单独的ASR/TTS客户端类型...")
    audio_processor2 = MessageProcessorAudio(
        message_store=message_store,
        chat_stream=chat_stream,
        chat_stream_manager=chat_stream_manager,
        db_conn_string=db_conn_string,
        websocket_send_callback=websocket_send_callback,
        client_type=AudioClientType.SEPARATE_CLIENTS
    )
    
    try:
        await audio_processor2.start()
        logger.info(f"单独客户端类型初始化成功: {audio_processor2.get_current_client_type().value}")
        await asyncio.sleep(1)
    finally:
        await audio_processor2.cleanup()
    
    logger.info("不同客户端类型测试完成")

async def main():
    """主函数"""
    logger.info("开始音频客户端切换功能测试")
    
    try:
        # 测试客户端类型切换
        await test_client_switching()
        
        # 测试不同客户端类型初始化
        await test_different_client_types()
        
        logger.info("所有测试完成")
        
    except Exception as e:
        logger.error(f"测试过程中出现错误: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 