#!/usr/bin/env python3
"""
麦克风打断播放功能独立测试

不需要WebSocket服务器的独立测试脚本，直接测试：
1. 麦克风活动检测
2. 播放打断机制
3. 耳机设备切换

使用方法:
python test_interruption_standalone.py

功能:
- 播放测试音频文件
- 检测麦克风输入
- 当检测到麦克风活动时暂停播放并切换到耳机
- 麦克风静音后恢复播放
"""

import asyncio
import logging
import time
import threading
import queue
import signal
import os
from test_websocket_audio import (
    AudioConfig, 
    AudioDeviceManager, 
    MicrophoneActivityDetector
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StandaloneInterruptionTester:
    """独立的麦克风打断测试器"""
    
    def __init__(self):
        # 音频设备管理 - 使用耳机的原生采样率
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200),
            output_config=AudioConfig(sample_rate=48000, channels=1, chunk=4800)
        )
        
        # 麦克风活动检测器
        self.mic_detector = MicrophoneActivityDetector(threshold=0.009, window_size=5)
        
        # 状态控制
        self.is_running = True
        self.is_recording = True
        self.is_playing = True
        
        # 播放控制
        self.is_playback_paused = False
        self.playback_lock = threading.Lock()
        
        # 音频播放队列和线程
        self.audio_queue = queue.Queue()
        self.output_stream = None
        self.player_thread = None
        self.microphone_thread = None
        
        # 测试音频生成
        self.audio_generator_thread = None
        
        # 信号处理
        signal.signal(signal.SIGINT, self._keyboard_signal)
        
    def _keyboard_signal(self, sig, frame):
        """处理键盘中断信号"""
        logger.info("收到 Ctrl+C 信号，正在停止...")
        self.is_recording = False
        self.is_playing = False
        self.is_running = False
    
    def pause_playback(self):
        """暂停播放"""
        with self.playback_lock:
            if not self.is_playback_paused:
                self.is_playback_paused = True
                logger.info("⏸️ 播放已暂停 (检测到麦克风输入)")
                
                # 清空播放队列
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        break
    
    def resume_playback(self):
        """恢复播放"""
        with self.playback_lock:
            if self.is_playback_paused:
                self.is_playback_paused = False
                logger.info("▶️ 播放已恢复")
    
    def _audio_player_thread(self):
        """音频播放线程"""
        logger.info("🎵 播放线程已启动")
        
        while self.is_playing:
            try:
                # 检查是否需要暂停播放
                with self.playback_lock:
                    if self.is_playback_paused:
                        time.sleep(0.1)
                        continue
                
                # 从队列获取音频数据
                try:
                    audio_data = self.audio_queue.get(timeout=1.0)
                    if audio_data is not None and self.output_stream:
                        # 再次检查播放状态
                        with self.playback_lock:
                            if not self.is_playback_paused:
                                self.output_stream.write(audio_data)
                except queue.Empty:
                    continue
                    
            except Exception as e:
                logger.error(f"音频播放错误: {e}")
                time.sleep(0.1)
                
        logger.info("🔇 播放线程结束")
    
    def _microphone_thread(self):
        """麦克风监听线程"""
        logger.info("🎤 麦克风监听线程已启动")
        
        try:
            input_stream = self.audio_device.open_input_stream(use_headphone=True)
            
            while self.is_recording:
                try:
                    # 读取麦克风数据
                    audio_chunk = input_stream.read(
                        self.audio_device.input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 检测麦克风活动
                    mic_active = self.mic_detector.update(audio_chunk)
                    
                    # 如果检测到麦克风活动，暂停播放
                    if mic_active and not self.is_playback_paused:
                        logger.info("🎤 检测到麦克风输入，暂停播放")
                        self.pause_playback()
                    elif not mic_active and self.is_playback_paused:
                        # 麦克风活动结束后稍等一下再恢复播放
                        if time.time() - self.mic_detector.last_activity_time > 1.0:  # 1秒后恢复
                            logger.info("🔊 麦克风静音，恢复播放")
                            self.resume_playback()
                    
                    time.sleep(0.01)  # 避免CPU过度使用
                    
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"麦克风监听失败: {e}")
            
        logger.info("🔇 麦克风监听线程结束")
    
    def _audio_generator_thread(self):
        """音频生成线程 - 生成测试音频"""
        import numpy as np
        
        logger.info("🎼 音频生成线程已启动")
        
        sample_rate = 48000  # 匹配耳机的原生采样率
        frequency = 440  # A4音符
        duration = 0.1   # 每次生成100ms音频
        samples_per_chunk = int(sample_rate * duration)
        
        t = 0
        while self.is_playing:
            try:
                # 生成正弦波音频
                time_array = np.linspace(t, t + duration, samples_per_chunk, False)
                # 使用不同频率的混合音调
                wave1 = np.sin(2 * np.pi * frequency * time_array) * 0.3
                wave2 = np.sin(2 * np.pi * (frequency * 1.5) * time_array) * 0.2
                wave3 = np.sin(2 * np.pi * (frequency * 2) * time_array) * 0.1
                
                combined_wave = wave1 + wave2 + wave3
                
                # 增加音量并转换为int16格式
                combined_wave = np.clip(combined_wave * 0.9, -1, 1)  # 增加音量到90%
                audio_data = (combined_wave * 32760).astype(np.int16).tobytes()
                
                # 添加到播放队列
                if not self.audio_queue.full():
                    self.audio_queue.put(audio_data)
                    # 每5秒显示一次生成状态
                    if int(t) % 5 == 0 and t > 0:
                        logger.info(f"🎼 持续生成音频中... ({int(t)}秒)")
                
                t += duration
                time.sleep(duration)  # 控制生成速度
                
            except Exception as e:
                logger.error(f"音频生成错误: {e}")
                time.sleep(0.1)
                
        logger.info("🔇 音频生成线程结束")
    
    def start_test(self):
        """启动测试"""
        print("🎵 麦克风打断播放功能独立测试")
        print("=" * 50)
        print("📋 测试说明:")
        print("  1. 程序会通过耳机播放测试音频 🎧")
        print("  2. 对着Mac内置麦克风说话 🎤")
        print("  3. 检测到麦克风输入时播放会暂停 ⏸️")
        print("  4. 停止说话1秒后播放会自动恢复 ▶️")
        print("  5. 按 Ctrl+C 结束测试")
        print()
        print("💡 戴上耳机，准备说话测试打断功能！")
        
        try:
            # 显示设备信息
            print(f"\n📱 检测到的设备信息:")
            print(f"   🎤 Mac内置麦克风: {self.audio_device.headphone_input_device_index}")
            print(f"   🎧 耳机输出: {self.audio_device.headphone_device_index}")
            print(f"   🔊 扬声器: {self.audio_device.speaker_device_index}")
            
            # 初始化音频输出流（直接使用耳机）
            self.output_stream = self.audio_device.open_output_stream(use_headphone=True)
            self.output_stream.start_stream()
            logger.info(f"🎧 音频输出流已启动 (耳机模式, 采样率: {self.audio_device.output_config.sample_rate}Hz)")
            
            # 验证输出设备
            if self.audio_device.headphone_device_index is not None:
                print(f"✅ 将通过耳机播放 (设备索引: {self.audio_device.headphone_device_index})")
            else:
                print(f"⚠️ 未找到耳机，将使用默认输出设备")
            
            # 启动各个线程
            self.player_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
            self.microphone_thread = threading.Thread(target=self._microphone_thread, daemon=True)
            self.audio_generator_thread = threading.Thread(target=self._audio_generator_thread, daemon=True)
            
            self.player_thread.start()
            self.microphone_thread.start()
            self.audio_generator_thread.start()
            
            logger.info("✅ 所有线程已启动，开始测试...")
            print("\n🎧 开始在耳机中播放测试音频...")
            print("🎤 现在对着Mac内置麦克风说话来测试打断功能！")
            
            # 主循环
            while self.is_running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"测试过程中出错: {e}")
        finally:
            # 清理资源
            self.is_playing = False
            self.is_recording = False
            self.is_running = False
            
            # 等待线程结束
            if self.player_thread and self.player_thread.is_alive():
                self.player_thread.join(timeout=2)
            if self.microphone_thread and self.microphone_thread.is_alive():
                self.microphone_thread.join(timeout=2)
            if self.audio_generator_thread and self.audio_generator_thread.is_alive():
                self.audio_generator_thread.join(timeout=2)
            
            self.audio_device.cleanup()
            logger.info("🧹 测试结束，资源已清理")

def main():
    """主函数"""
    print("开始独立的麦克风打断播放测试...")
    
    tester = StandaloneInterruptionTester()
    tester.start_test()

if __name__ == "__main__":
    main() 