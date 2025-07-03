#!/usr/bin/env python3
"""
ASR客户端保活功能测试脚本

测试内容：
1. 音频发送队列功能
2. 自动保活机制（静音音频发送）
3. 连接状态监控
4. 队列状态监控
"""

import asyncio
import logging
import time
import sys
import os
from typing import List

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents.doubao_client.asr_client import AsrClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AsrKeepaliveTest:
    """ASR保活功能测试类"""
    
    def __init__(self):
        self.asr_client = None
        self.recognition_results: List[str] = []
        self.test_start_time = 0
        
    def on_asr_start(self):
        """ASR开始回调"""
        logger.info("🎤 ASR 会话已开始")
        
    def on_asr_response(self, text: str):
        """ASR响应回调"""
        logger.info(f"🗣️  ASR 识别结果: {text}")
        self.recognition_results.append(text)
        
    def on_asr_end(self):
        """ASR结束回调"""
        logger.info("🏁 ASR 会话已结束")
        
    def on_asr_reconnect(self):
        """ASR重连回调"""
        logger.info("🔄 ASR 重连成功")
        
    def on_asr_disconnect(self):
        """ASR断开连接回调"""
        logger.warning("❌ ASR 连接已断开")
        
    def generate_test_audio(self, duration_seconds: float = 0.1) -> bytes:
        """
        生成测试音频数据（PCM格式）
        :param duration_seconds: 音频时长
        :return: PCM音频数据
        """
        # PCM参数（与ASR配置保持一致）
        sample_rate = 16000
        channels = 1
        bits_per_sample = 16
        
        # 计算音频数据大小
        bytes_per_sample = bits_per_sample // 8
        total_samples = int(sample_rate * channels * duration_seconds)
        audio_data_size = total_samples * bytes_per_sample
        
        # 生成简单的测试音频（正弦波）
        import math
        frequency = 440  # A4音符
        audio_data = bytearray()
        
        for i in range(total_samples):
            # 生成正弦波样本
            t = i / sample_rate
            sample = int(32767 * 0.1 * math.sin(2 * math.pi * frequency * t))
            
            # 转换为16位小端字节
            sample_bytes = sample.to_bytes(2, 'little', signed=True)
            audio_data.extend(sample_bytes)
            
        return bytes(audio_data)
        
    async def monitor_status(self, duration: int = 60):
        """监控ASR连接状态"""
        logger.info(f"📊 开始状态监控，持续 {duration} 秒")
        
        start_time = time.time()
        while time.time() - start_time < duration:
            if self.asr_client:
                status = self.asr_client.get_connection_status()
                logger.info(
                    f"📈 状态监控 - "
                    f"运行: {status['is_running']}, "
                    f"队列大小: {status['send_queue_size']}, "
                    f"保活启用: {status['keepalive_enabled']}, "
                    f"距离上次发送: {status['time_since_last_send']:.1f}秒"
                )
            
            await asyncio.sleep(5)  # 每5秒监控一次
            
    async def test_audio_sending(self):
        """测试音频发送功能"""
        logger.info("🎵 测试1: 音频发送队列功能")
        
        # 快速发送多个音频块，测试队列缓冲
        for i in range(10):
            audio_data = self.generate_test_audio(0.1)  # 100ms音频
            await self.asr_client.process_audio_chunk(audio_data)
            logger.info(f"✅ 已发送音频块 {i+1}/10")
            await asyncio.sleep(0.05)  # 50ms间隔
            
        logger.info("🎵 音频发送测试完成")
        
    async def test_keepalive(self):
        """测试自动保活功能"""
        logger.info("💓 测试2: 自动保活功能")
        logger.info("等待40秒，观察自动保活行为...")
        
        # 等待一段时间，不发送任何音频，观察保活机制
        await asyncio.sleep(40)
        
        logger.info("💓 保活测试观察期结束")
        
    async def test_mixed_scenario(self):
        """测试混合场景：音频发送 + 静默期 + 音频发送"""
        logger.info("🎭 测试3: 混合场景测试")
        
        # 第一阶段：发送音频
        logger.info("第一阶段：发送音频数据")
        for i in range(5):
            audio_data = self.generate_test_audio(0.2)
            await self.asr_client.process_audio_chunk(audio_data)
            await asyncio.sleep(0.1)
            
        # 第二阶段：静默期，触发保活
        logger.info("第二阶段：静默期（35秒），观察保活")
        await asyncio.sleep(35)
        
        # 第三阶段：再次发送音频
        logger.info("第三阶段：恢复音频发送")
        for i in range(5):
            audio_data = self.generate_test_audio(0.2)
            await self.asr_client.process_audio_chunk(audio_data)
            await asyncio.sleep(0.1)
            
        logger.info("🎭 混合场景测试完成")
        
    async def run_tests(self):
        """运行所有测试"""
        try:
            logger.info("🚀 开始ASR保活功能测试")
            self.test_start_time = time.time()
            
            # 初始化ASR客户端（保活间隔设置为10秒，便于测试）
            self.asr_client = AsrClient(
                asr_start_callback=self.on_asr_start,
                asr_response_callback=self.on_asr_response,
                asr_end_callback=self.on_asr_end,
                asr_reconnect_callback=self.on_asr_reconnect,
                asr_disconnect_callback=self.on_asr_disconnect,
                uid="test_keepalive_user",
                keepalive_interval=10.0,  # 10秒保活间隔
                keepalive_enabled=True
            )
            
            # 启动ASR连接
            logger.info("🔌 正在连接ASR服务...")
            await self.asr_client.start()
            
            # 等待连接稳定
            await asyncio.sleep(2)
            
            # 创建状态监控任务
            monitor_task = asyncio.create_task(self.monitor_status(120))
            
            # 依次运行测试
            await self.test_audio_sending()
            await asyncio.sleep(5)
            
            await self.test_keepalive()
            await asyncio.sleep(5)
            
            await self.test_mixed_scenario()
            
            # 等待监控任务完成
            await monitor_task
            
        except Exception as e:
            logger.error(f"❌ 测试过程中发生错误: {e}")
            raise
        finally:
            # 清理资源
            if self.asr_client:
                logger.info("🧹 正在清理ASR客户端...")
                await self.asr_client.cleanup()
                
            # 显示测试总结
            test_duration = time.time() - self.test_start_time
            logger.info("=" * 60)
            logger.info("📋 测试总结:")
            logger.info(f"⏱️  总测试时间: {test_duration:.1f} 秒")
            logger.info(f"🎯 识别结果数量: {len(self.recognition_results)}")
            if self.recognition_results:
                logger.info("📝 识别结果列表:")
                for i, result in enumerate(self.recognition_results, 1):
                    logger.info(f"  {i}. {result}")
            logger.info("=" * 60)

async def main():
    """主函数"""
    test = AsrKeepaliveTest()
    await test.run_tests()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 测试被用户中断")
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        sys.exit(1) 