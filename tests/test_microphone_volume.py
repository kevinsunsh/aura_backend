#!/usr/bin/env python3
"""
麦克风音量调试工具

用于测试和调试麦克风音量检测，帮助找到合适的检测阈值。
特别适用于调试耳机麦克风的音量检测问题。

使用方法:
python test_microphone_volume.py

功能:
1. 实时显示麦克风音量
2. 显示推荐的阈值设置
3. 测试不同的音频格式
4. 帮助调试耳机麦克风
"""

import asyncio
import logging
import time
import numpy as np
from test_websocket_audio import AudioConfig, AudioDeviceManager, MicrophoneActivityDetector

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MicrophoneVolumeDebugger:
    """麦克风音量调试器"""
    
    def __init__(self):
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=1600),  # 100ms chunks
            output_config=None  # 不需要输出
        )
        
        self.volume_history = []
        self.max_volume = 0
        self.avg_volume = 0
        self.running = True
        
    def analyze_volume(self, audio_data):
        """分析音频数据的音量"""
        try:
            # 将音频数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 计算不同的音量指标
            rms_volume = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            normalized_rms = rms_volume / 32768.0  # 16位音频的最大值
            
            peak_volume = np.max(np.abs(audio_array.astype(np.float32)))
            normalized_peak = peak_volume / 32768.0
            
            # 记录历史数据
            self.volume_history.append(normalized_rms)
            if len(self.volume_history) > 100:  # 保留最近100个样本
                self.volume_history.pop(0)
            
            self.max_volume = max(self.max_volume, normalized_rms)
            self.avg_volume = sum(self.volume_history) / len(self.volume_history)
            
            return {
                'rms': normalized_rms,
                'peak': normalized_peak,
                'avg': self.avg_volume,
                'max': self.max_volume
            }
            
        except Exception as e:
            logger.error(f"音量分析出错: {e}")
            return None
    
    def get_recommended_threshold(self):
        """根据当前音量历史推荐阈值"""
        if len(self.volume_history) < 10:
            return 0.005  # 默认值
        
        # 计算音量的统计信息
        volumes = np.array(self.volume_history)
        mean_vol = np.mean(volumes)
        std_vol = np.std(volumes)
        max_vol = np.max(volumes)
        
        # 推荐阈值：平均值 + 2倍标准差，但不超过最大值的50%
        recommended = min(mean_vol + 2 * std_vol, max_vol * 0.5)
        
        # 确保阈值不会太小
        recommended = max(recommended, 0.001)
        
        return recommended
    
    async def run_volume_test(self, duration=30):
        """运行音量测试"""
        print("🎤 麦克风音量调试工具")
        print("=" * 50)
        print(f"测试时长: {duration}秒")
        print("请对着麦克风说话，观察音量变化...")
        print("按 Ctrl+C 可提前结束测试")
        print()
        
        try:
            # 打开麦克风输入流
            input_stream = self.audio_device.open_input_stream(use_headphone=True)
            
            start_time = time.time()
            last_update = 0
            
            while self.running and (time.time() - start_time) < duration:
                try:
                    # 读取麦克风数据
                    audio_chunk = input_stream.read(
                        self.audio_device.input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 分析音量
                    volume_info = self.analyze_volume(audio_chunk)
                    
                    if volume_info and time.time() - last_update > 0.5:  # 每0.5秒更新一次显示
                        last_update = time.time()
                        
                        # 获取推荐阈值
                        recommended_threshold = self.get_recommended_threshold()
                        
                        # 检查是否活跃
                        is_active = volume_info['rms'] > recommended_threshold
                        
                        # 清屏并显示当前状态
                        print(f"\r实时音量: {volume_info['rms']:.6f} | "
                              f"峰值: {volume_info['peak']:.6f} | "
                              f"平均: {volume_info['avg']:.6f} | "
                              f"最大: {volume_info['max']:.6f} | "
                              f"推荐阈值: {recommended_threshold:.6f} | "
                              f"状态: {'🎤活跃' if is_active else '🔇静音'}", end='', flush=True)
                    
                    await asyncio.sleep(0.01)  # 避免CPU过度使用
                    
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    await asyncio.sleep(0.1)
                    
        except KeyboardInterrupt:
            print("\n\n用户中断测试")
            self.running = False
        except Exception as e:
            logger.error(f"音量测试失败: {e}")
        finally:
            self.audio_device.cleanup()
            
        # 显示测试结果
        self.show_test_results()
    
    def show_test_results(self):
        """显示测试结果和建议"""
        print("\n\n" + "=" * 50)
        print("🎤 麦克风音量测试结果")
        print("=" * 50)
        
        if len(self.volume_history) > 0:
            volumes = np.array(self.volume_history)
            
            print(f"📊 音量统计:")
            print(f"  最大音量: {self.max_volume:.6f}")
            print(f"  平均音量: {np.mean(volumes):.6f}")
            print(f"  标准差: {np.std(volumes):.6f}")
            print(f"  最小音量: {np.min(volumes):.6f}")
            
            print(f"\n🎯 建议设置:")
            recommended = self.get_recommended_threshold()
            print(f"  推荐检测阈值: {recommended:.6f}")
            
            # 不同敏感度的阈值建议
            conservative = recommended * 1.5
            sensitive = recommended * 0.5
            very_sensitive = recommended * 0.3
            
            print(f"  保守阈值 (不易触发): {conservative:.6f}")
            print(f"  敏感阈值 (容易触发): {sensitive:.6f}")
            print(f"  极敏感阈值: {very_sensitive:.6f}")
            
            print(f"\n💡 使用建议:")
            if self.max_volume < 0.001:
                print("  ⚠️  检测到的音量很小，可能需要:")
                print("     - 检查麦克风是否正常工作")
                print("     - 调高系统麦克风音量")
                print("     - 确认耳机麦克风已启用")
                print("     - 使用极敏感阈值设置")
            elif self.max_volume < 0.01:
                print("  💡 音量较小，建议:")
                print("     - 使用敏感阈值设置")
                print("     - 确认麦克风位置正确")
            else:
                print("  ✅ 音量正常，可以使用推荐阈值")
            
            print(f"\n🔧 代码配置:")
            print(f"  MicrophoneActivityDetector(threshold={recommended:.6f}, window_size=5)")
            
        else:
            print("❌ 未检测到音频数据，请检查麦克风连接")

async def main():
    """主函数"""
    debugger = MicrophoneVolumeDebugger()
    await debugger.run_volume_test(duration=30)

if __name__ == "__main__":
    asyncio.run(main()) 