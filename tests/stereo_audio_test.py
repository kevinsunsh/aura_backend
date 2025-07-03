#!/usr/bin/env python3
"""
立体声音频测试 - 双声道播放到Beats耳机
"""
import pyaudio
import numpy as np
import time

def main():
    print("🎧 立体声Beats耳机音频测试")
    
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
        
        # 使用立体声配置
        sample_rate = 48000
        duration = 5  # 5秒
        channels = 2  # 立体声
        
        print(f"\n🎵 生成立体声测试音频:")
        print(f"  采样率: {sample_rate}Hz")
        print(f"  通道数: {channels} (立体声)")
        print(f"  时长: {duration}秒")
        
        # 生成立体声测试音频
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        
        # 左声道: 440Hz (A4)
        left_audio = np.sin(2 * np.pi * 440 * t) * 0.8
        # 右声道: 554Hz (C#5) 
        right_audio = np.sin(2 * np.pi * 554 * t) * 0.8
        
        # 交替组合成立体声
        stereo_audio = np.zeros((len(t), 2), dtype=np.float32)
        stereo_audio[:, 0] = left_audio   # 左声道
        stereo_audio[:, 1] = right_audio  # 右声道
        
        # 转换为int16格式
        stereo_int16 = (stereo_audio * 32767).astype(np.int16)
        
        print(f"📊 音频数据: {stereo_int16.shape} (样本数, 声道数)")
        print(f"📊 峰值: {np.max(np.abs(stereo_int16))}")
        
        # 打开立体声音频流
        stream = p.open(
            format=pyaudio.paInt16,
            channels=2,  # 立体声
            rate=sample_rate,
            output=True,
            frames_per_buffer=1024,
            output_device_index=beats_device
        )
        
        print("\n▶️ 开始播放立体声音频到Beats耳机...")
        print("   左耳应该听到440Hz音调")
        print("   右耳应该听到554Hz音调")
        print("   请戴上耳机仔细听!")
        
        # 播放音频
        chunk_size = 1024
        audio_bytes = stereo_int16.tobytes()
        
        for i in range(0, len(audio_bytes), chunk_size * 4):  # *4 因为2通道*2字节
            chunk = audio_bytes[i:i + chunk_size * 4]
            stream.write(chunk)
        
        # 清理
        stream.stop_stream()
        stream.close()
        
        print("✅ 立体声播放完成!")
        
        # 再测试单声道版本
        print("\n" + "="*50)
        print("🔄 现在测试单声道版本...")
        
        # 单声道测试
        mono_audio = np.sin(2 * np.pi * 440 * t) * 0.9
        mono_int16 = (mono_audio * 32767).astype(np.int16)
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,  # 单声道
            rate=sample_rate,
            output=True,
            frames_per_buffer=1024,
            output_device_index=beats_device
        )
        
        print("▶️ 播放单声道440Hz音调...")
        
        mono_bytes = mono_int16.tobytes()
        for i in range(0, len(mono_bytes), chunk_size * 2):  # *2 因为int16是2字节
            chunk = mono_bytes[i:i + chunk_size * 2]
            stream.write(chunk)
        
        stream.stop_stream()
        stream.close()
        
        print("✅ 单声道播放完成!")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        p.terminate()

if __name__ == "__main__":
    main() 