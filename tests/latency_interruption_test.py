#!/usr/bin/env python3
"""
低延迟打断测试工具
专门测试麦克风打断播放的延迟性能
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import time
import threading
import queue
import logging
import signal
import numpy as np
from test_websocket_audio import AudioConfig, AudioDeviceManager, MicrophoneActivityDetector

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LatencyInterruptionTester:
    """延迟打断测试器"""
    
    def __init__(self):
        # 使用低延迟配置
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=800),  # 50ms chunks，极低延迟
            output_config=AudioConfig(sample_rate=48000, channels=1, chunk=1200)  # 25ms chunks，极低延迟
        )
        
        # 麦克风活动检测器 - 极敏感模式
        self.mic_detector = MicrophoneActivityDetector(threshold=0.008, window_size=1)  # 单样本检测
        
        # 状态控制
        self.is_running = True
        self.is_recording = True
        self.is_playing = True
        
        # 播放控制
        self.is_playback_paused = False
        self.playback_lock = threading.Lock()
        
        # 音频队列
        self.audio_queue = queue.Queue(maxsize=10)  # 减小队列大小降低缓冲延迟
        
        # 延迟统计
        self.interruption_times = []
        self.resume_times = []
        self.mic_detect_time = None
        self.playback_pause_time = None
        
        # 线程
        self.output_stream = None
        self.player_thread = None
        self.microphone_thread = None
        self.audio_generator_thread = None
        
        # 信号处理
        signal.signal(signal.SIGINT, self._keyboard_signal)
        
    def _keyboard_signal(self, sig, frame):
        """处理键盘中断信号"""
        logger.info("收到 Ctrl+C 信号，正在停止...")
        self.is_recording = False
        self.is_playing = False
        self.is_running = False
        
        # 输出延迟统计
        self._print_latency_stats()
    
    def _print_latency_stats(self):
        """输出延迟统计结果"""
        print("\n" + "="*60)
        print("📊 延迟统计结果")
        print("="*60)
        
        if self.interruption_times:
            avg_interruption = sum(self.interruption_times) / len(self.interruption_times)
            min_interruption = min(self.interruption_times)
            max_interruption = max(self.interruption_times)
            
            print(f"🔇 打断延迟统计 ({len(self.interruption_times)} 次):")
            print(f"   平均延迟: {avg_interruption*1000:.1f}ms")
            print(f"   最小延迟: {min_interruption*1000:.1f}ms") 
            print(f"   最大延迟: {max_interruption*1000:.1f}ms")
            
            # 延迟分布
            fast_count = sum(1 for t in self.interruption_times if t < 0.1)  # <100ms
            medium_count = sum(1 for t in self.interruption_times if 0.1 <= t < 0.2)  # 100-200ms
            slow_count = sum(1 for t in self.interruption_times if t >= 0.2)  # >200ms
            
            print(f"   延迟分布:")
            print(f"     <100ms: {fast_count} 次 ({fast_count/len(self.interruption_times)*100:.1f}%)")
            print(f"     100-200ms: {medium_count} 次 ({medium_count/len(self.interruption_times)*100:.1f}%)")
            print(f"     >200ms: {slow_count} 次 ({slow_count/len(self.interruption_times)*100:.1f}%)")
        
        if self.resume_times:
            avg_resume = sum(self.resume_times) / len(self.resume_times)
            print(f"\n▶️ 恢复延迟统计 ({len(self.resume_times)} 次):")
            print(f"   平均恢复时间: {avg_resume*1000:.1f}ms")
        
        print("\n💡 优化建议:")
        if self.interruption_times and sum(self.interruption_times) / len(self.interruption_times) > 0.15:
            print("   - 打断延迟较高，建议减小音频缓冲区大小")
            print("   - 降低麦克风检测阈值或减小窗口大小")
        else:
            print("   - 打断延迟表现良好！")
    
    def pause_playback(self):
        """暂停播放并记录时间"""
        with self.playback_lock:
            if not self.is_playback_paused:
                self.playback_pause_time = time.time()
                self.is_playback_paused = True
                
                # 计算打断延迟
                if self.mic_detect_time:
                    latency = self.playback_pause_time - self.mic_detect_time
                    self.interruption_times.append(latency)
                    logger.info(f"⏸️ 播放已暂停 - 打断延迟: {latency*1000:.1f}ms")
                else:
                    logger.info("⏸️ 播放已暂停")
                
                # 清空播放队列减少延迟
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        break
    
    def resume_playback(self):
        """恢复播放并记录时间"""
        with self.playback_lock:
            if self.is_playback_paused:
                resume_time = time.time()
                self.is_playback_paused = False
                
                # 计算恢复延迟
                if self.playback_pause_time:
                    resume_latency = resume_time - self.playback_pause_time
                    self.resume_times.append(resume_latency)
                    logger.info(f"▶️ 播放已恢复 - 恢复用时: {resume_latency*1000:.1f}ms")
                else:
                    logger.info("▶️ 播放已恢复")
    
    def _audio_player_thread(self):
        """低延迟音频播放线程"""
        logger.info("🎵 播放线程已启动 (低延迟模式)")
        
        while self.is_playing:
            try:
                # 检查是否需要暂停播放
                with self.playback_lock:
                    if self.is_playback_paused:
                        time.sleep(0.001)  # 1ms检查间隔，极低延迟
                        continue
                
                # 从队列获取音频数据
                try:
                    audio_data = self.audio_queue.get(timeout=0.1)  # 减少超时等待
                    if audio_data is not None and self.output_stream:
                        # 再次检查播放状态
                        with self.playback_lock:
                            if not self.is_playback_paused:
                                self.output_stream.write(audio_data)
                except queue.Empty:
                    continue
                    
            except Exception as e:
                logger.error(f"音频播放错误: {e}")
                time.sleep(0.001)
                
        logger.info("🔇 播放线程结束")
    
    def _microphone_thread(self):
        """低延迟麦克风监听线程"""
        logger.info("🎤 麦克风监听线程已启动 (低延迟模式)")
        
        try:
            input_stream = self.audio_device.open_input_stream(use_headphone=True)
            
            while self.is_recording:
                try:
                    # 读取麦克风数据 (小缓冲区)
                    audio_chunk = input_stream.read(
                        self.audio_device.input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 检测麦克风活动
                    mic_active = self.mic_detector.update(audio_chunk)
                    
                    # 如果检测到麦克风活动，立即暂停播放
                    if mic_active and not self.is_playback_paused:
                        self.mic_detect_time = time.time()
                        logger.info("🎤 检测到麦克风输入，立即暂停播放")
                        self.pause_playback()
                    elif not mic_active and self.is_playback_paused:
                        # 麦克风活动结束后快速恢复播放
                        if time.time() - self.mic_detector.last_activity_time > 0.3:  # 300ms后恢复
                            logger.info("🔊 麦克风静音，快速恢复播放")
                            self.resume_playback()
                    
                    time.sleep(0.001)  # 1ms间隔，最小延迟
                    
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    time.sleep(0.001)
                    
        except Exception as e:
            logger.error(f"麦克风监听失败: {e}")
            
        logger.info("🔇 麦克风监听线程结束")
    
    def _audio_generator_thread(self):
        """低延迟音频生成线程"""
        logger.info("🎼 音频生成线程已启动 (低延迟模式)")
        
        sample_rate = 48000
        frequency = 440  # A4音符
        duration = 0.025   # 25ms音频块，极低延迟
        samples_per_chunk = int(sample_rate * duration)
        
        t = 0
        while self.is_playing:
            try:
                # 生成正弦波音频
                time_array = np.linspace(t, t + duration, samples_per_chunk, False)
                # 使用不同频率的混合音调，便于听觉识别
                wave1 = np.sin(2 * np.pi * frequency * time_array) * 0.4
                wave2 = np.sin(2 * np.pi * (frequency * 1.5) * time_array) * 0.3
                wave3 = np.sin(2 * np.pi * (frequency * 2) * time_array) * 0.2
                
                combined_wave = wave1 + wave2 + wave3
                
                # 转换为int16格式
                combined_wave = np.clip(combined_wave * 0.9, -1, 1)
                audio_data = (combined_wave * 32760).astype(np.int16).tobytes()
                
                # 添加到播放队列（非阻塞）
                try:
                    self.audio_queue.put_nowait(audio_data)
                except queue.Full:
                    # 队列满时跳过这个块，避免积累延迟
                    pass
                
                t += duration
                time.sleep(duration * 0.8)  # 稍微快一点避免播放中断
                
            except Exception as e:
                logger.error(f"音频生成错误: {e}")
                time.sleep(0.001)
                
        logger.info("🔇 音频生成线程结束")
    
    def start_test(self):
        """启动延迟测试"""
        print("⚡ 低延迟麦克风打断测试")
        print("=" * 60)
        print("📋 测试说明:")
        print("  1. 程序会通过耳机播放测试音频 🎧")
        print("  2. 对着Mac内置麦克风说话 🎤")
        print("  3. 测量打断延迟和恢复时间 ⏱️")
        print("  4. 按 Ctrl+C 查看延迟统计")
        print()
        print("🎯 目标: 打断延迟 < 100ms")
        print("💡 戴上耳机，准备测试！")
        
        try:
            # 显示设备信息
            print(f"\n📱 设备配置:")
            print(f"   🎤 Mac内置麦克风: {self.audio_device.headphone_input_device_index}")
            print(f"   🎧 耳机输出: {self.audio_device.headphone_device_index}")
            print(f"   📊 音频缓冲: {self.audio_device.input_config.chunk}样本 (输入), {self.audio_device.output_config.chunk}样本 (输出)")
            
            # 初始化音频输出流
            self.output_stream = self.audio_device.open_output_stream(use_headphone=True)
            self.output_stream.start_stream()
            logger.info(f"🎧 音频输出流已启动 (采样率: {self.audio_device.output_config.sample_rate}Hz)")
            
            # 启动各个线程
            self.player_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
            self.microphone_thread = threading.Thread(target=self._microphone_thread, daemon=True)
            self.audio_generator_thread = threading.Thread(target=self._audio_generator_thread, daemon=True)
            
            self.player_thread.start()
            self.microphone_thread.start()
            self.audio_generator_thread.start()
            
            logger.info("✅ 所有线程已启动，开始延迟测试...")
            print("\n🎧 开始在耳机中播放测试音频...")
            print("🎤 对着Mac内置麦克风说话来测试打断延迟！")
            print("📈 每次打断都会显示延迟时间...")
            
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
            for thread in [self.player_thread, self.microphone_thread, self.audio_generator_thread]:
                if thread and thread.is_alive():
                    thread.join(timeout=1)
            
            self.audio_device.cleanup()
            logger.info("🧹 测试结束，资源已清理")

def main():
    """主函数"""
    print("开始低延迟麦克风打断测试...")
    
    tester = LatencyInterruptionTester()
    tester.start_test()

if __name__ == "__main__":
    main() 