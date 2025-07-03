#!/usr/bin/env python3
"""
TTS客户端队列优化测试脚本

测试功能：
1. 异步发送队列
2. 自动保活机制（无需手动调用）
3. 队列状态监控
"""

import asyncio
import logging
import time
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents.doubao_client.tts_client import TtsClient

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TTSQueueTester:
    """TTS队列优化测试器"""
    
    def __init__(self):
        self.tts_client = None
        self.received_audio_count = 0
        self.test_texts = [
            "这是第一段测试文本。",
            "这是第二段测试文本，稍微长一些，用于测试队列的处理能力。",
            "第三段文本，测试连续发送的效果。",
            "最后一段测试文本，验证队列是否能正常处理所有消息。"
        ]
        
    def tts_start_callback(self):
        """TTS开始回调"""
        logger.info("🎵 TTS开始合成")
        
    def tts_response_callback(self, audio_data: bytes):
        """TTS音频响应回调"""
        self.received_audio_count += 1
        logger.info(f"🔊 收到音频数据: {len(audio_data)} 字节 (第{self.received_audio_count}个)")
        
    def tts_end_callback(self):
        """TTS结束回调"""
        logger.info("✅ TTS合成结束")
        
    def tts_reconnect_callback(self):
        """TTS重连回调"""
        logger.info("🔄 TTS重连成功")
        
    def tts_disconnect_callback(self):
        """TTS断开连接回调"""
        logger.warning("❌ TTS连接断开")
        
    async def create_tts_client(self):
        """创建TTS客户端"""
        self.tts_client = TtsClient(
            uid="test_queue_user",
            tts_start_callback=self.tts_start_callback,
            tts_response_callback=self.tts_response_callback,
            tts_end_callback=self.tts_end_callback,
            tts_reconnect_callback=self.tts_reconnect_callback,
            tts_disconnect_callback=self.tts_disconnect_callback,
            keepalive_interval=10.0,  # 10秒保活间隔
            keepalive_enabled=True
        )
        
    async def test_queue_sending(self):
        """测试队列发送功能"""
        logger.info("🚀 开始测试队列发送功能")
        
        try:
            # 启动TTS客户端
            await self.tts_client.start()
            await asyncio.sleep(2)  # 等待连接稳定
            
            # 快速发送多个文本，测试队列处理
            logger.info("📤 快速发送多个文本...")
            for i, text in enumerate(self.test_texts):
                await self.tts_client.send_text_chunk(text)
                logger.info(f"已发送第{i+1}个文本到队列")
                # 很短的间隔，测试队列缓冲
                await asyncio.sleep(0.1)
            
            # 显示队列状态
            status = self.tts_client.get_connection_status()
            logger.info(f"📊 发送队列状态: {status['send_queue_size']} 个消息待发送")
            logger.info(f"📊 保活状态: 启用={status['keepalive_enabled']}, 上次发送={status['time_since_last_send']:.1f}秒前")
            
            # 等待消息处理
            logger.info("⏳ 等待消息处理...")
            await asyncio.sleep(10)
            
            # 再次检查队列状态
            status = self.tts_client.get_connection_status()
            logger.info(f"📊 处理后队列状态: {status['send_queue_size']} 个消息待发送")
            
        except Exception as e:
            logger.error(f"测试队列发送失败: {e}")
            
    async def test_keepalive(self):
        """测试自动保活功能"""
        logger.info("🔄 开始测试自动保活功能")
        
        try:
            # 等待一段时间，让自动保活触发
            logger.info("⏱️ 等待自动保活触发（不发送任何文本消息）...")
            await asyncio.sleep(15)  # 等待超过保活间隔
            
            status = self.tts_client.get_connection_status()
            logger.info(f"📊 保活状态: 上次发送={status['time_since_last_send']:.1f}秒前")
            logger.info("💚 保活功能完全自动化，无需手动调用")
            
        except Exception as e:
            logger.error(f"测试自动保活功能失败: {e}")
            
    async def test_queue_full_scenario(self):
        """测试队列满的情况"""
        logger.info("🚧 开始测试队列满的情况")
        
        try:
            # 快速发送大量文本，尝试填满队列
            logger.info("📤 快速发送大量文本...")
            for i in range(150):  # 发送超过队列容量的消息
                test_text = f"测试文本第{i+1}条，用于测试队列容量。"
                await self.tts_client.send_text_chunk(test_text)
                if i % 20 == 0:
                    status = self.tts_client.get_connection_status()
                    logger.info(f"📊 发送进度: {i+1}/150, 队列大小: {status['send_queue_size']}")
            
            # 最终状态
            status = self.tts_client.get_connection_status()
            logger.info(f"📊 最终队列状态: {status['send_queue_size']} 个消息")
            
        except Exception as e:
            logger.error(f"测试队列满情况失败: {e}")
            
    async def monitor_queue_status(self, duration=30):
        """监控队列状态"""
        logger.info(f"📊 开始监控队列状态 ({duration}秒)")
        
        start_time = time.time()
        while time.time() - start_time < duration:
            try:
                status = self.tts_client.get_connection_status()
                logger.info(f"📈 状态监控: 队列={status['send_queue_size']}, "
                          f"待处理={status['pending_texts_count']}, "
                          f"距离上次发送={status['time_since_last_send']:.1f}秒")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"监控状态失败: {e}")
                break
                
    async def run_all_tests(self):
        """运行所有测试"""
        try:
            await self.create_tts_client()
            
            # 测试1: 队列发送
            await self.test_queue_sending()
            await asyncio.sleep(2)
            
            # 测试2: 保活功能
            await self.test_keepalive()
            await asyncio.sleep(2)
            
            # 同时运行状态监控和队列满测试
            monitor_task = asyncio.create_task(self.monitor_queue_status(20))
            await asyncio.sleep(1)
            await self.test_queue_full_scenario()
            
            # 等待监控完成
            await monitor_task
            
            logger.info("🎉 所有测试完成")
            
        except Exception as e:
            logger.error(f"测试运行失败: {e}")
        finally:
            if self.tts_client:
                await self.tts_client.cleanup()
                logger.info("🧹 TTS客户端已清理")

async def main():
    """主函数"""
    logger.info("🎬 开始TTS队列优化测试")
    
    tester = TTSQueueTester()
    
    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        logger.info("❌ 测试被用户中断")
    except Exception as e:
        logger.error(f"测试失败: {e}")
    finally:
        logger.info("🏁 测试结束")

if __name__ == "__main__":
    asyncio.run(main()) 