#!/usr/bin/env python3
"""
麦克风打断播放演示脚本

这个脚本演示了如何使用新的音频打断功能：
1. 🎧 自动检测并使用耳机设备
2. 🎤 检测麦克风输入活动
3. ⏸️ 当有麦克风输入时自动暂停播放
4. ▶️ 麦克风静音后自动恢复播放
5. 🔄 无缝切换音频输出设备

使用方法:
python demo_interruption.py

功能测试:
- 运行脚本后，会开始播放测试音频
- 对着麦克风说话，播放会自动暂停并切换到耳机
- 停止说话后1秒，播放会自动恢复
"""

import asyncio
import logging
import time
from test_websocket_audio import (
    AudioConfig, 
    AudioDeviceManager, 
    MicrophoneActivityDetector,
    WebSocketTestSession
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InterruptionDemo:
    """播放打断演示类"""
    
    def __init__(self):
        # 创建音频设备管理器
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200)
        )
        
        # 创建麦克风活动检测器 (根据测试结果调整阈值)
        self.mic_detector = MicrophoneActivityDetector(threshold=0.009, window_size=5)
        
        # 状态控制
        self.is_running = True
        self.is_demo_playing = False
        
    def demo_audio_device_detection(self):
        """演示音频设备检测功能"""
        print("\n=== 🎧 音频设备检测演示 ===")
        
        if self.audio_device.headphone_device_index is not None:
            print(f"✅ 检测到耳机输出设备 (索引: {self.audio_device.headphone_device_index})")
        else:
            print("⚠️ 未检测到耳机输出设备")
        
        if self.audio_device.headphone_input_device_index is not None:
            # 判断是Mac内置麦克风还是耳机麦克风
            try:
                device_info = self.audio_device.pyaudio.get_device_info_by_index(self.audio_device.headphone_input_device_index)
                device_name = device_info['name'].lower()
                if 'macbook' in device_name or 'imac' in device_name or 'built-in' in device_name:
                    print(f"✅ 检测到Mac内置麦克风设备 (索引: {self.audio_device.headphone_input_device_index})")
                else:
                    print(f"✅ 检测到耳机麦克风设备 (索引: {self.audio_device.headphone_input_device_index})")
            except:
                print(f"✅ 检测到麦克风设备 (索引: {self.audio_device.headphone_input_device_index})")
        else:
            print("⚠️ 未检测到麦克风设备")
            
        if self.audio_device.speaker_device_index is not None:
            print(f"✅ 检测到扬声器设备 (索引: {self.audio_device.speaker_device_index})")
        else:
            print("⚠️ 未检测到扬声器设备")
            
        print("💡 会优先使用耳机作为输入和输出设备")
    
    async def demo_microphone_detection(self):
        """演示麦克风活动检测功能"""
        print("\n=== 🎤 麦克风活动检测演示 ===")
        print("请对着麦克风说话，观察活动检测效果...")
        print("按 Ctrl+C 结束演示")
        
        try:
            input_stream = self.audio_device.open_input_stream()
            
            for i in range(100):  # 运行10秒
                if not self.is_running:
                    break
                    
                # 读取麦克风数据
                audio_chunk = input_stream.read(
                    self.audio_device.input_config.chunk, 
                    exception_on_overflow=False
                )
                
                # 检测活动
                is_active = self.mic_detector.update(audio_chunk)
                
                # 打印状态
                if is_active:
                    volume_history = self.mic_detector.volume_history
                    avg_volume = sum(volume_history) / len(volume_history) if volume_history else 0
                    print(f"🎤 检测到麦克风活动! 音量: {avg_volume:.4f}", end='\r')
                else:
                    print("🔇 麦克风静音中...              ", end='\r')
                
                await asyncio.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n演示结束")
        except Exception as e:
            logger.error(f"麦克风检测演示出错: {e}")
        finally:
            self.is_running = False
    
    def demo_device_switching(self):
        """演示设备切换功能"""
        print("\n=== 🔄 设备切换演示 ===")
        
        try:
            # 测试输入设备切换
            print("🎤 测试输入设备...")
            input_stream = self.audio_device.open_input_stream(use_headphone=True)
            if input_stream:
                print("✅ 成功打开耳机麦克风")
            
            time.sleep(1)
            
            # 打开输出流（默认使用扬声器）
            print("🔊 测试输出设备切换...")
            self.audio_device.open_output_stream(use_headphone=False)
            print("🔊 当前使用扬声器输出")
            
            time.sleep(2)
            
            # 切换到耳机
            success = self.audio_device.switch_to_headphone()
            if success:
                print("🎧 已切换到耳机输出")
            else:
                print("⚠️ 切换到耳机失败或已经在使用耳机")
                
        except Exception as e:
            logger.error(f"设备切换演示出错: {e}")
    
    def demo_headphone_full_duplex(self):
        """演示耳机全双工模式（同时输入输出）"""
        print("\n=== 🎧 耳机全双工模式演示 ===")
        
        if (self.audio_device.headphone_device_index is None or 
            self.audio_device.headphone_input_device_index is None):
            print("⚠️ 需要同时检测到耳机输出和麦克风设备才能演示此功能")
            return
        
        try:
            # 同时打开耳机输入和输出
            input_stream = self.audio_device.open_input_stream(use_headphone=True)
            output_stream = self.audio_device.open_output_stream(use_headphone=True)
            
            if input_stream and output_stream:
                print("✅ 耳机全双工模式已启用")
                print(f"🎤 耳机麦克风设备: 索引 {self.audio_device.current_input_device}")
                print(f"🎧 耳机输出设备: 索引 {self.audio_device.current_output_device}")
                print("💡 现在可以同时录音和播放，避免扬声器回音")
            else:
                print("❌ 无法启用耳机全双工模式")
                
        except Exception as e:
            logger.error(f"耳机全双工演示出错: {e}")
            print("❌ 耳机全双工模式启用失败")
    
    async def run_full_demo(self):
        """运行完整演示"""
        print("🎵 麦克风打断播放功能演示")
        print("=" * 50)
        
        try:
            # 1. 设备检测演示
            self.demo_audio_device_detection()
            
            await asyncio.sleep(2)
            
            # 2. 设备切换演示
            self.demo_device_switching()
            
            await asyncio.sleep(2)
            
            # 3. 耳机全双工模式演示
            self.demo_headphone_full_duplex()
            
            await asyncio.sleep(2)
            
            # 4. 麦克风检测演示
            await self.demo_microphone_detection()
            
        except KeyboardInterrupt:
            print("\n\n👋 演示结束，感谢使用!")
        except Exception as e:
            logger.error(f"演示过程中出错: {e}")
        finally:
            # 清理资源
            self.audio_device.cleanup()
            print("🧹 资源已清理")

async def main():
    """主函数"""
    demo = InterruptionDemo()
    await demo.run_full_demo()

if __name__ == "__main__":
    asyncio.run(main()) 