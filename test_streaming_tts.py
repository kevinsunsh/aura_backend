#!/usr/bin/env python3
"""双工流式TTS测试 - 使用jieba分词，流式输入输出"""
import asyncio
import sys
import os
import logging
import time
from pathlib import Path
import jieba
from datetime import datetime

# 添加src路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioRecorder:
    """音频录制器，将流式音频数据保存为MP3文件"""
    
    def __init__(self, output_dir="audio_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.output_file = None
        
    def start_recording(self, filename=None):
        """开始录制音频"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tts_output_{timestamp}.mp3"
        
        self.output_file = self.output_dir / filename
        self.audio_buffer.clear()
        self.is_recording = True
        logger.info(f"🎤 开始录制音频到: {self.output_file}")
        
    def add_audio_data(self, audio_data: bytes):
        """添加音频数据到缓冲区"""
        if self.is_recording:
            self.audio_buffer.extend(audio_data)
            
    def stop_recording(self):
        """停止录制并保存文件"""
        if not self.is_recording:
            return
            
        self.is_recording = False
        
        if self.audio_buffer and self.output_file:
            with open(self.output_file, 'wb') as f:
                f.write(self.audio_buffer)
            
            file_size = len(self.audio_buffer)
            logger.info(f"💾 音频文件已保存: {self.output_file} ({file_size} 字节)")
            
            # 使用更可靠的播放方式
            try:
                import subprocess
                if sys.platform == "darwin":  # macOS
                    # 使用afplay而不是open，afplay更适合音频播放
                    result = subprocess.run(['afplay', str(self.output_file)], 
                                          capture_output=True, text=True, timeout=1)
                    if result.returncode == 0:
                        logger.info("🔊 正在用afplay播放音频...")
                    else:
                        # 备用方案：用系统默认程序打开
                        subprocess.run(['open', str(self.output_file)], check=False)
                        logger.info("🔊 正在用系统默认程序播放音频...")
                elif sys.platform == "linux":  # Linux
                    subprocess.run(['aplay', str(self.output_file)], check=False)
                    logger.info("🔊 正在用aplay播放音频...")
                elif sys.platform == "win32":  # Windows
                    import os
                    os.system(f'start "" "{self.output_file}"')
                    logger.info("🔊 正在用系统播放器播放音频...")
            except Exception as e:
                logger.warning(f"自动播放失败: {e}")
                logger.info(f"💡 请手动播放文件: {self.output_file}")
            
            return self.output_file
        else:
            logger.warning("没有录制到音频数据")
            return None


async def test_streaming_tts():
    """测试双工流式TTS"""
    try:
        from agents.doubao_client.tts_client import TtsClient
        
        # 测试文本
        test_text = "你好，欢迎使用流式语音合成系统。这个系统可以实时将文本转换为语音，并且支持分词处理。让我们来测试一下这个功能的效果如何。"
        
        logger.info(f"📝 测试文本: {test_text}")
        
        # 使用jieba分词
        logger.info("✂️ 开始分词...")
        words = list(jieba.cut(test_text, cut_all=False))
        logger.info(f"✅ 分词结果: {words}")
        logger.info(f"📊 总共 {len(words)} 个词")
        
        # 创建音频录制器
        audio_recorder = AudioRecorder()
        
        # 状态变量
        synthesis_started = False
        synthesis_finished = False
        audio_data_count = 0
        total_audio_bytes = 0
        first_audio_received = False
        
        # TTS回调函数
        async def tts_start_callback():
            nonlocal synthesis_started, first_audio_received
            synthesis_started = True
            logger.info("🎵 TTS合成开始")
            # 只在第一次收到TTS开始信号时开始录制
            if not first_audio_received:
                audio_recorder.start_recording()
                first_audio_received = True
            
        async def tts_response_callback(audio_data: bytes):
            nonlocal audio_data_count, total_audio_bytes
            audio_data_count += 1
            total_audio_bytes += len(audio_data)
            logger.info(f"🔊 收到音频数据 #{audio_data_count}: {len(audio_data)} 字节 (总计: {total_audio_bytes} 字节)")
            audio_recorder.add_audio_data(audio_data)
            
        async def tts_end_callback():
            nonlocal synthesis_finished
            logger.info("🎵 TTS合成结束")
            
        async def tts_reconnect_callback():
            logger.info("🔄 TTS重连成功")
            
        async def tts_disconnect_callback():
            logger.warning("❌ TTS连接断开")
        
        # 创建TTS客户端
        tts_client = TtsClient(
            tts_start_callback=tts_start_callback,
            tts_response_callback=tts_response_callback,
            tts_end_callback=tts_end_callback,
            tts_reconnect_callback=tts_reconnect_callback,
            tts_disconnect_callback=tts_disconnect_callback,
            max_reconnect_attempts=3,
            reconnect_interval=2.0
        )
        
        logger.info("🚀 启动TTS客户端...")
        await tts_client.start()
        logger.info("✅ TTS客户端启动成功")
        
        # 流式发送文本片段
        logger.info("📤 开始流式发送文本片段...")
        
        for i, word in enumerate(words):
            logger.info(f"📝 发送第 {i+1}/{len(words)} 个词: '{word}'")
            await tts_client.send_text_chunk(word)
            
            # 模拟真实的打字速度，每个词间隔0.5秒
            await asyncio.sleep(0.5)
        
        logger.info("📤 所有文本片段发送完成")
        
        # 结束TTS会话
        logger.info("🔚 结束TTS会话...")
        await tts_client.finish_synthesis()
        
        # 等待合成完成
        logger.info("⏳ 等待音频合成完成...")
        await asyncio.sleep(3)  # 等待更长时间确保所有音频数据都收到
        
        # 停止录制并保存文件
        output_file = audio_recorder.stop_recording()
        
        logger.info("✅ 音频录制完成")
        
        # 清理资源
        logger.info("🧹 清理资源...")
        await tts_client.cleanup()
        
        # 显示连接状态信息
        status = tts_client.get_connection_status()
        logger.info(f"📊 最终连接状态: {status}")
        
        # 显示统计信息
        logger.info(f"📊 音频统计:")
        logger.info(f"   - 收到音频包数量: {audio_data_count}")
        logger.info(f"   - 总音频数据大小: {total_audio_bytes} 字节")
        if output_file:
            logger.info(f"   - 保存文件: {output_file}")
            
        logger.info("🎉 双工流式TTS测试完成！")
        
        if output_file:
            logger.info(f"🎵 请手动播放音频文件验证: {output_file}")
            # 尝试不同的播放方式
            try:
                import subprocess
                subprocess.run(['afplay', str(output_file)], check=False)
                logger.info("🔊 已用afplay播放音频")
            except:
                logger.info("💡 如果没有听到声音，请手动双击文件播放")
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


async def test_multiple_sentences():
    """测试多句话的流式TTS"""
    try:
        from agents.doubao_client.tts_client import TtsClient
        
        # 多个测试句子
        test_sentences = [
            "这是第一句话，测试流式语音合成。",
            "现在播放第二句，看看效果如何。", 
            "最后一句话，感谢您的测试！"
        ]
        
        # 创建音频录制器
        audio_recorder = AudioRecorder()
        
        # 音频数据统计
        audio_data_count = 0
        total_audio_bytes = 0
        
        # TTS回调函数
        async def tts_response_callback(audio_data: bytes):
            nonlocal audio_data_count, total_audio_bytes
            audio_data_count += 1
            total_audio_bytes += len(audio_data)
            logger.info(f"🔊 收到音频数据 #{audio_data_count}: {len(audio_data)} 字节 (总计: {total_audio_bytes} 字节)")
            audio_recorder.add_audio_data(audio_data)
        
        # 创建TTS客户端
        tts_client = TtsClient(tts_response_callback=tts_response_callback)
        
        logger.info("🚀 启动TTS客户端...")
        await tts_client.start()
        
        # 开始录制
        audio_recorder.start_recording("multi_sentences_test.mp3")
        
        for i, sentence in enumerate(test_sentences):
            logger.info(f"\n📝 处理第 {i+1} 句: {sentence}")
            
            # 分词
            words = list(jieba.cut(sentence, cut_all=False))
            logger.info(f"✂️ 分词: {words}")
            
            # 流式发送
            for word in words:
                logger.info(f"📤 发送: '{word}'")
                await tts_client.send_text_chunk(word)
                await asyncio.sleep(0.3)  # 稍快一点的速度
            
            # 句子间稍作停顿
            await asyncio.sleep(1.0)
        
        # 结束并等待
        await tts_client.finish_synthesis()
        await asyncio.sleep(3)  # 等待合成完成
        
        # 停止录制
        output_file = audio_recorder.stop_recording()
        
        # 清理
        await tts_client.cleanup()
        
        # 显示统计信息
        logger.info(f"📊 音频统计:")
        logger.info(f"   - 收到音频包数量: {audio_data_count}")
        logger.info(f"   - 总音频数据大小: {total_audio_bytes} 字节")
        if output_file:
            logger.info(f"   - 保存文件: {output_file}")
        
        logger.info("🎉 多句话流式TTS测试完成！")
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) > 1 and sys.argv[1] == "multi":
        logger.info("🎯 运行多句话测试模式")
        asyncio.run(test_multiple_sentences())
    else:
        logger.info("🎯 运行单句话测试模式")
        asyncio.run(test_streaming_tts()) 