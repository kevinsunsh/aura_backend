#!/usr/bin/env python3
"""
简单的耳机音频测试工具
直接测试耳机音频输出功能
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import pyaudio
import numpy as np
import time
import threading

class SimpleHeadphoneTest:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.is_playing = True
        
    def list_devices(self):
        """列出所有音频设备"""
        print("可用的音频设备:")
        print("=" * 50)
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            device_type = "输出" if info["maxOutputChannels"] > 0 else "输入"
            if info["maxOutputChannels"] > 0 and info["maxInputChannels"] > 0:
                device_type = "输入/输出"
            print(f"{i}: {info['name']} ({device_type}) - 采样率: {info['defaultSampleRate']}")
        print("=" * 50)
    
    def test_device(self, device_index=None, test_duration=3):
        """测试指定设备的音频输出"""
        print(f"\n🎵 开始测试音频设备 {device_index if device_index else '(默认)'}...")
        
        # 生成测试音频 - 使用多种格式测试
        sample_rate = 44100
        frequency = 440  # A4音符
        
        t = np.linspace(0, test_duration, int(sample_rate * test_duration), False)
        audio = np.sin(2 * np.pi * frequency * t) * 0.7  # 70%音量
        
        # 测试不同的音频格式
        formats_to_test = [
            (pyaudio.paInt16, (audio * 32767).astype(np.int16), "16位整数"),
            (pyaudio.paFloat32, audio.astype(np.float32), "32位浮点"),
        ]
        
        for format_type, audio_data, format_name in formats_to_test:
            print(f"  📊 测试格式: {format_name}")
            try:
                # 打开音频流
                stream = self.p.open(
                    format=format_type,
                    channels=1,
                    rate=sample_rate,
                    output=True,
                    frames_per_buffer=1024,
                    output_device_index=device_index
                )
                
                print(f"  ▶️ 播放440Hz测试音调{test_duration}秒...")
                
                # 分段播放
                chunk_size = 1024
                audio_bytes = audio_data.tobytes()
                bytes_per_sample = audio_data.dtype.itemsize
                
                for i in range(0, len(audio_bytes), chunk_size * bytes_per_sample):
                    if not self.is_playing:
                        break
                    chunk = audio_bytes[i:i + chunk_size * bytes_per_sample]
                    stream.write(chunk)
                
                stream.stop_stream()
                stream.close()
                print(f"  ✅ {format_name}格式播放完成")
                time.sleep(1)  # 格式间暂停
                
            except Exception as e:
                print(f"  ❌ {format_name}格式播放失败: {e}")
        
        return True
    
    def test_beats_headphone(self):
        """专门测试Beats耳机"""
        print("\n🎧 专门测试Beats耳机...")
        
        # 查找Beats设备
        beats_device = None
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            if "beats" in info['name'].lower() and info["maxOutputChannels"] > 0:
                beats_device = i
                print(f"找到Beats设备: {info['name']} (索引: {i})")
                break
        
        if beats_device is None:
            print("❌ 未找到Beats设备")
            return False
        
        return self.test_device(beats_device, test_duration=5)
    
    def cleanup(self):
        """清理资源"""
        self.is_playing = False
        self.p.terminate()

def main():
    print("🎧 耳机音频测试工具")
    print("=" * 50)
    
    tester = SimpleHeadphoneTest()
    
    try:
        # 列出设备
        tester.list_devices()
        
        while True:
            print("\n选择测试选项:")
            print("1. 测试默认设备")
            print("2. 测试Beats耳机")
            print("3. 测试指定设备")
            print("4. 退出")
            
            choice = input("\n请输入选择 (1-4): ").strip()
            
            if choice == "1":
                tester.test_device()
            elif choice == "2":
                tester.test_beats_headphone()
            elif choice == "3":
                device_id = input("请输入设备ID: ")
                try:
                    device_id = int(device_id)
                    tester.test_device(device_id)
                except ValueError:
                    print("❌ 无效的设备ID")
            elif choice == "4":
                break
            else:
                print("❌ 无效选择")
    
    except KeyboardInterrupt:
        print("\n用户中断测试")
    finally:
        tester.cleanup()
        print("🧹 测试结束")

if __name__ == "__main__":
    main() 