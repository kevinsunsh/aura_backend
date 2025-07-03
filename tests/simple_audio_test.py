#!/usr/bin/env python3
"""
最简单的音频测试 - 直接播放到Beats耳机
"""
import pyaudio
import numpy as np
import time

def main():
    print("🎧 最简单的Beats耳机音频测试")
    
    # 初始化PyAudio
    p = pyaudio.PyAudio()
    
    try:
        # 查找Beats设备
        beats_device = None
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if "beats" in info['name'].lower() and info["maxOutputChannels"] > 0:
                beats_device = i
                print(f"找到Beats设备: {info['name']} (索引: {i})")
                print(f"  默认采样率: {info['defaultSampleRate']}")
                print(f"  输出通道数: {info['maxOutputChannels']}")
                break
        
        if beats_device is None:
            print("❌ 未找到Beats设备")
            return
        
        # 使用设备的原生采样率
        sample_rate = 48000  # Beats设备的原生采样率
        duration = 3  # 3秒
        frequency = 440  # A4音符
        
        print(f"\n🎵 生成测试音频: {frequency}Hz, {sample_rate}Hz采样率, {duration}秒")
        
        # 生成正弦波
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio = np.sin(2 * np.pi * frequency * t) * 0.8  # 80%音量
        
        # 转换为16位整数
        audio_int16 = (audio * 32767).astype(np.int16)
        
        print(f"📊 音频数据: {len(audio_int16)} 个样本, 峰值: {np.max(np.abs(audio_int16))}")
        
        # 打开音频流
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            output=True,
            frames_per_buffer=1024,
            output_device_index=beats_device
        )
        
        print("\n▶️ 开始播放到Beats耳机...")
        print("   请戴上耳机，应该能听到440Hz的音调")
        
        # 播放音频
        chunk_size = 1024
        audio_bytes = audio_int16.tobytes()
        
        for i in range(0, len(audio_bytes), chunk_size * 2):  # *2 因为int16是2字节
            chunk = audio_bytes[i:i + chunk_size * 2]
            stream.write(chunk)
        
        # 清理
        stream.stop_stream()
        stream.close()
        
        print("✅ 播放完成!")
        print("\n你听到声音了吗？如果没有，可能是:")
        print("1. 耳机音量设置太低")
        print("2. 耳机没有正确连接")
        print("3. macOS音频设置问题")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
    finally:
        p.terminate()

if __name__ == "__main__":
    main() 