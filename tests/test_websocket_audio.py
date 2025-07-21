#!/usr/bin/env python3
"""
WebSocket音频流测试 - 重构简化版本

🎵 核心特性:
- 三个异步循环：接收循环、发送循环、播放循环
- 支持麦克风输入和文件输入两种模式
- 使用二进制协议发送音频数据
- 基于450事件的播放打断机制
- 统一的音频设备管理

🎤 使用示例:
# 麦克风模式
session = WebSocketTestSession()
await session.start()

# 文件模式
session = WebSocketTestSession()
await session.start_with_files()
"""
import asyncio
import websockets
import json
import logging
import time
import gzip
import os
import wave
import pyaudio
import io
import queue
import threading
import signal
import numpy as np
from pydub import AudioSegment
from statistics import mean, median
from datetime import datetime
import sys
import tempfile
import struct
import multiprocessing as mp
import ctypes
# import opuslib

# 配置日志（提前）
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 添加OGG/Opus解码支持
try:
    import pyogg
    PYOGG_AVAILABLE = True
    logger.info("✅ PyOgg流式解码库已加载")
except ImportError:
    PYOGG_AVAILABLE = False
    logger.warning("⚠️ 未找到PyOgg库，将尝试使用pydub处理OGG音频")
except Exception as e:
    PYOGG_AVAILABLE = False
    logger.warning(f"⚠️ PyOgg库加载失败: {e}，将使用pydub处理OGG音频")

# 添加src路径以导入protocol模块
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

# === 二进制协议支持 ===
# 导入protocol模块和枚举
from api_protocol.constant import *
from api_protocol.client_protocol import client_generate_request, client_parse_response

async def send_audio_task_request(websocket, audio: bytes, session_id: str = "test_user_123444") -> None:
    """发送音频数据，参考RealtimeDialogClient.task_request的简洁方式"""
    task_request = client_generate_request(
        payload_data=audio,
        message_type=CLIENT_AUDIO_ONLY_REQUEST,
        message_type_specific_flags=MSG_WITH_EVENT,
        serial_method=NO_SERIALIZATION,
        compression_type=GZIP,
        event=ClientEvent.TaskRequest,
        session_id=session_id
    )
    await websocket.send(task_request)

class AudioConfig:
    """音频配置类"""
    def __init__(self, 
                 sample_rate: int = 24000,
                 channels: int = 1,
                 bit_size: int = pyaudio.paInt16,
                 chunk: int = 1024):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bit_size = bit_size
        self.chunk = chunk
        self.sample_width = pyaudio.get_sample_size(bit_size)

class AudioDeviceManager:
    """音频设备管理类，处理音频输入输出，支持耳机检测和切换"""

    def __init__(self, input_config: AudioConfig, output_config: AudioConfig):
        self.input_config = input_config
        self.output_config = output_config
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        
        # 音频设备信息
        self.headphone_device_index = None
        self.speaker_device_index = None
        self.headphone_input_device_index = None  # 耳机麦克风设备索引
        self.current_output_device = None
        self.current_input_device = None
        
        # 检测并设置音频设备
        self._detect_audio_devices()

    def _detect_audio_devices(self):
        """检测可用的音频输入输出设备，优先选择耳机"""
        logger.info("🎧 正在检测音频输入输出设备...")
        
        device_count = self.pyaudio.get_device_count()
        # 更全面的关键词列表，包含品牌名称
        headphone_keywords = [
            'headphone', 'headset', 'earphone', 'airpods', 'bluetooth', 'usb',
            'beats', 'sony', 'bose', 'sennheiser', 'audio-technica', 'jbl',
            'skullcandy', 'plantronics', 'jabra', 'wireless', 'stereo'
        ]
        speaker_keywords = ['speaker', 'built-in', 'internal', 'macbook', 'imac']
        
        headphone_output_devices = []
        headphone_input_devices = []
        speaker_devices = []
        all_output_devices = []
        all_input_devices = []
        
        for i in range(device_count):
            try:
                device_info = self.pyaudio.get_device_info_by_index(i)
                device_name = device_info['name'].lower()
                
                # 检查是否为耳机设备（更智能的匹配）
                is_headphone = any(keyword in device_name for keyword in headphone_keywords)
                is_speaker = any(keyword in device_name for keyword in speaker_keywords)
                
                # 检测输出设备
                if device_info['maxOutputChannels'] > 0:
                    all_output_devices.append((i, device_info))
                    logger.debug(f"检测到输出设备 {i}: {device_info['name']} (输出通道: {device_info['maxOutputChannels']})")
                    
                    if is_headphone and not is_speaker:
                        headphone_output_devices.append((i, device_info))
                        logger.info(f"🎧 发现耳机输出设备: {device_info['name']} (索引: {i})")
                    elif is_speaker:
                        speaker_devices.append((i, device_info))
                        logger.info(f"🔊 发现扬声器设备: {device_info['name']} (索引: {i})")
                    elif not is_speaker and i > 0:  # 非默认设备且不是明显的扬声器，可能是耳机
                        headphone_output_devices.append((i, device_info))
                        logger.info(f"🎧 推测耳机输出设备: {device_info['name']} (索引: {i})")
                
                # 检测输入设备
                if device_info['maxInputChannels'] > 0:
                    all_input_devices.append((i, device_info))
                    logger.debug(f"检测到输入设备 {i}: {device_info['name']} (输入通道: {device_info['maxInputChannels']})")
                    
                    # 优先使用Mac内置麦克风，而不是耳机麦克风
                    if 'macbook' in device_name or 'imac' in device_name or 'built-in' in device_name:
                        headphone_input_devices.insert(0, (i, device_info))  # 插到前面，优先级最高
                        logger.info(f"🎤 发现Mac内置麦克风设备: {device_info['name']} (索引: {i})")
                    elif is_headphone:
                        headphone_input_devices.append((i, device_info))
                        logger.info(f"🎤 发现耳机麦克风设备: {device_info['name']} (索引: {i})")
                        
            except Exception as e:
                logger.debug(f"检测设备 {i} 时出错: {e}")
        
        # 优先选择耳机输出设备
        if headphone_output_devices:
            self.headphone_device_index = headphone_output_devices[0][0]
            logger.info(f"✅ 选择耳机输出设备: {headphone_output_devices[0][1]['name']} (索引: {self.headphone_device_index})")
        
        # 优先选择麦克风设备（Mac内置麦克风优先）
        if headphone_input_devices:
            self.headphone_input_device_index = headphone_input_devices[0][0]
            device_name = headphone_input_devices[0][1]['name']
            if 'macbook' in device_name.lower() or 'imac' in device_name.lower() or 'built-in' in device_name.lower():
                logger.info(f"✅ 选择Mac内置麦克风设备: {device_name} (索引: {self.headphone_input_device_index})")
            else:
                logger.info(f"✅ 选择耳机麦克风设备: {device_name} (索引: {self.headphone_input_device_index})")
        
        # 选择扬声器设备作为备选
        if speaker_devices:
            self.speaker_device_index = speaker_devices[0][0]
            logger.info(f"✅ 选择扬声器设备: {speaker_devices[0][1]['name']} (索引: {self.speaker_device_index})")
        elif all_output_devices and len(all_output_devices) > 1:
            # 如果没有明显的扬声器，选择第一个设备作为扬声器
            self.speaker_device_index = all_output_devices[0][0]
            logger.info(f"✅ 使用默认扬声器设备: {all_output_devices[0][1]['name']} (索引: {self.speaker_device_index})")
        
        # 设备检测结果总结
        logger.info("=== 设备检测结果总结 ===")
        logger.info(f"🎧 耳机输出: {'索引 ' + str(self.headphone_device_index) if self.headphone_device_index is not None else '未检测到'}")
        
        # 显示选择的麦克风设备类型
        if self.headphone_input_device_index is not None:
            # 获取设备名称来判断类型
            try:
                device_info = self.pyaudio.get_device_info_by_index(self.headphone_input_device_index)
                device_name = device_info['name'].lower()
                if 'macbook' in device_name or 'imac' in device_name or 'built-in' in device_name:
                    logger.info(f"🎤 Mac内置麦克风: 索引 {self.headphone_input_device_index}")
                else:
                    logger.info(f"🎤 耳机麦克风: 索引 {self.headphone_input_device_index}")
            except:
                logger.info(f"🎤 麦克风设备: 索引 {self.headphone_input_device_index}")
        else:
            logger.info(f"🎤 麦克风设备: 未检测到")
            
        logger.info(f"🔊 扬声器: {'索引 ' + str(self.speaker_device_index) if self.speaker_device_index is not None else '未检测到'}")
        
        # 如果都没有找到，记录所有设备供调试
        if not self.headphone_device_index and not self.speaker_device_index:
            logger.warning("⚠️ 未检测到特定的耳机或扬声器设备")
            logger.info("所有输出设备列表:")
            for i, (idx, info) in enumerate(all_output_devices):
                logger.info(f"  {idx}: {info['name']} (输出通道: {info['maxOutputChannels']})")
            # 使用第一个可用设备作为默认
            if all_output_devices:
                self.speaker_device_index = all_output_devices[0][0]
                logger.info(f"🔊 使用第一个可用设备: {all_output_devices[0][1]['name']}")
            else:
                self.speaker_device_index = None  # 使用系统默认
                logger.info("🔊 使用系统默认音频输出设备")
        
        if not self.headphone_input_device_index:
            logger.warning("⚠️ 未检测到耳机麦克风设备")
            logger.info("所有输入设备列表:")
            for i, (idx, info) in enumerate(all_input_devices):
                logger.info(f"  {idx}: {info['name']} (输入通道: {info['maxInputChannels']})")

    def open_input_stream(self, use_headphone=True):
        """打开音频输入流，优先使用耳机麦克风"""
        if self.input_stream is not None:
            return self.input_stream
        
        # 选择输入设备
        if use_headphone and self.headphone_input_device_index is not None:
            device_index = self.headphone_input_device_index
            # 判断设备类型
            try:
                device_info = self.pyaudio.get_device_info_by_index(device_index)
                device_name = device_info['name'].lower()
                if 'macbook' in device_name or 'imac' in device_name or 'built-in' in device_name:
                    device_type = "Mac内置麦克风"
                else:
                    device_type = "耳机麦克风"
            except:
                device_type = "麦克风设备"
        else:
            device_index = None
            device_type = "默认麦克风"
        
        try:
            self.input_stream = self.pyaudio.open(
                format=self.input_config.bit_size,
                channels=self.input_config.channels,
                rate=self.input_config.sample_rate,
                input=True,
                frames_per_buffer=self.input_config.chunk,
                input_device_index=device_index
            )
            
            self.current_input_device = device_index
            logger.info(f"🎤 麦克风输入流已打开: {self.input_config.sample_rate}Hz, {self.input_config.channels}声道, 设备: {device_type}")
            return self.input_stream
            
        except Exception as e:
            logger.error(f"打开音频输入流失败 (设备: {device_type}): {e}")
            # 尝试使用默认设备
            if device_index is not None:
                try:
                    self.input_stream = self.pyaudio.open(
                        format=self.input_config.bit_size,
                        channels=self.input_config.channels,
                        rate=self.input_config.sample_rate,
                        input=True,
                        frames_per_buffer=self.input_config.chunk
                    )
                    self.current_input_device = None
                    logger.info(f"🎤 使用默认麦克风设备")
                    return self.input_stream
                except Exception as e2:
                    logger.error(f"打开默认麦克风设备也失败: {e2}")
                    raise
            else:
                raise

    def open_output_stream(self, use_headphone=True):
        """打开音频输出流，可选择耳机或扬声器"""
        if self.output_stream is not None:
            return self.output_stream
        
        # 选择输出设备
        if use_headphone and self.headphone_device_index is not None:
            device_index = self.headphone_device_index
            device_type = "耳机"
        elif self.speaker_device_index is not None:
            device_index = self.speaker_device_index
            device_type = "扬声器"
        else:
            device_index = None
            device_type = "默认"
        
        try:
            self.output_stream = self.pyaudio.open(
                format=self.output_config.bit_size,
                channels=self.output_config.channels,
                rate=self.output_config.sample_rate,
                output=True,
                frames_per_buffer=self.output_config.chunk,
                start=False,  # 由播放线程控制启动
                output_device_index=device_index
            )
            
            self.current_output_device = device_index
            logger.info(f"🔊 音频输出流已创建: {self.output_config.sample_rate}Hz, {self.output_config.channels}声道, 设备: {device_type}")
            return self.output_stream
            
        except Exception as e:
            logger.error(f"打开音频输出流失败 (设备: {device_type}): {e}")
            # 尝试使用默认设备
            if device_index is not None:
                try:
                    self.output_stream = self.pyaudio.open(
                        format=self.output_config.bit_size,
                        channels=self.output_config.channels,
                        rate=self.output_config.sample_rate,
                        output=True,
                        frames_per_buffer=self.output_config.chunk,
                        start=False
                    )
                    self.current_output_device = None
                    logger.info(f"🔊 使用默认音频输出设备")
                    return self.output_stream
                except Exception as e2:
                    logger.error(f"打开默认音频输出流也失败: {e2}")
                    raise
            else:
                raise
    
    def switch_to_headphone(self):
        """切换到耳机输出"""
        if self.output_stream and self.current_output_device != self.headphone_device_index:
            logger.info("🎧 切换到耳机输出...")
            # 关闭当前输出流
            if self.output_stream.is_active():
                self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
            
            # 重新打开耳机输出流
            self.open_output_stream(use_headphone=True)
            if self.output_stream:
                self.output_stream.start_stream()
                logger.info("✅ 已切换到耳机输出")
            return True
        return False
        
    def cleanup(self):
        """清理音频设备资源"""
        logger.info("🧹 清理音频设备资源...")
        
        for stream_name, stream in [("输入", self.input_stream), ("输出", self.output_stream)]:
            if stream:
                try:
                    # 检查流是否仍然有效
                    if hasattr(stream, 'is_active') and stream.is_active():
                        stream.stop_stream()
                        logger.debug(f"✅ {stream_name}流已停止")
                    
                    if hasattr(stream, 'close'):
                        stream.close()
                        logger.debug(f"✅ {stream_name}流已关闭")
                        
                except Exception as e:
                    error_msg = str(e)
                    if "PortAudio" in error_msg or "Internal PortAudio error" in error_msg or "Stream not open" in error_msg:
                        logger.warning(f"PortAudio错误，跳过{stream_name}流清理: {error_msg}")
                    else:
                        logger.warning(f"关闭{stream_name}流时出错: {error_msg}")
                    
        if self.pyaudio:
            try:
                # 添加延迟确保所有流都已正确关闭
                time.sleep(0.2)  # 增加延迟时间
                self.pyaudio.terminate()
                logger.debug("✅ PyAudio已终止")
            except Exception as e:
                error_msg = str(e)
                if "PortAudio" in error_msg or "Internal PortAudio error" in error_msg:
                    logger.warning(f"PortAudio错误，跳过PyAudio终止: {error_msg}")
                else:
                    logger.warning(f"终止PyAudio时出错: {error_msg}")
        
        # 重置状态
        self.input_stream = None
        self.output_stream = None

class VoiceActivityDetector:
    """语音活动检测器"""
    
    def __init__(self, 
                 sample_rate=16000,
                 frame_duration_ms=20,
                 silence_threshold_db=-45,
                 speech_threshold_db=-35,
                 silence_duration_ms=500,
                 speech_duration_ms=100):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.silence_threshold_db = silence_threshold_db
        self.speech_threshold_db = speech_threshold_db
        self.silence_duration_ms = silence_duration_ms
        self.speech_duration_ms = speech_duration_ms
        
        # 计算帧大小
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        
        # 状态跟踪
        self.is_speaking = False
        self.speech_start_time = None
        self.silence_start_time = None
        self.last_volume_db = -100
        self.volume_history = []
        self.max_history_size = 10
        
        # 音量统计
        self.min_volume_db = -100
        self.max_volume_db = -100
        self.avg_volume_db = -100
        
        # 实时音量可视化
        self.volume_bar_length = 30
        self.last_volume_bar = ""
        
        logger.info(f"🎤 VAD初始化: 静音阈值={silence_threshold_db}dB, 语音阈值={speech_threshold_db}dB")
    
    def calculate_volume_db(self, audio_data):
        """计算音频数据的音量分贝值"""
        try:
            # 将字节数据转换为numpy数组
            if len(audio_data) == 0:
                return -100
            
            # 假设是16位PCM数据
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if len(audio_array) == 0:
                return -100
            
            # 计算RMS值
            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            
            # 转换为分贝值 (参考值: 16位PCM的最大值32767)
            if rms > 0:
                db = 20 * np.log10(rms / 32767.0)
            else:
                db = -100
            
            return db
            
        except Exception as e:
            logger.debug(f"计算音量失败: {e}")
            return -100
    
    def calculate_energy(self, audio_data):
        """计算音频能量"""
        try:
            if len(audio_data) == 0:
                return 0
            
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return 0
            
            # 计算能量
            energy = np.sum(audio_array.astype(np.float32) ** 2)
            return energy
            
        except Exception as e:
            logger.debug(f"计算能量失败: {e}")
            return 0
    
    def calculate_zero_crossing_rate(self, audio_data):
        """计算过零率"""
        try:
            if len(audio_data) == 0:
                return 0
            
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return 0
            
            # 计算过零率
            zero_crossings = np.sum(np.diff(np.sign(audio_array)) != 0)
            rate = zero_crossings / len(audio_array)
            return rate
            
        except Exception as e:
            logger.debug(f"计算过零率失败: {e}")
            return 0
    
    def update_volume_history(self, volume_db):
        """更新音量历史记录"""
        self.volume_history.append(volume_db)
        if len(self.volume_history) > self.max_history_size:
            self.volume_history.pop(0)
        
        # 更新统计值
        if self.volume_history:
            self.min_volume_db = min(self.volume_history)
            self.max_volume_db = max(self.volume_history)
            self.avg_volume_db = sum(self.volume_history) / len(self.volume_history)
    
    def detect_speech_start(self, audio_data):
        """检测语音开始 - 增强版，结合能量和过零率"""
        current_time = time.time()
        volume_db = self.calculate_volume_db(audio_data)
        energy = self.calculate_energy(audio_data)
        zero_crossing_rate = self.calculate_zero_crossing_rate(audio_data)
        
        self.last_volume_db = volume_db
        self.update_volume_history(volume_db)
        
        # 动态阈值调整（基于历史音量）
        if len(self.volume_history) >= 5:
            recent_avg = sum(self.volume_history[-5:]) / 5
            dynamic_speech_threshold = max(self.speech_threshold_db, recent_avg + 5)
            dynamic_silence_threshold = min(self.silence_threshold_db, recent_avg - 5)
        else:
            dynamic_speech_threshold = self.speech_threshold_db
            dynamic_silence_threshold = self.silence_threshold_db
        
        # 检测语音开始 - 使用多个特征
        speech_detected = False
        if not self.is_speaking:
            # 音量检测
            volume_ok = volume_db > dynamic_speech_threshold
            # 能量检测（降低阈值）
            energy_ok = energy > 100000  # 降低能量阈值从100万到10万
            # 过零率检测（放宽条件）
            zcr_ok = 0.05 < zero_crossing_rate < 0.5  # 放宽过零率范围
            
            # 调试信息
            if volume_db > -50:  # 只在音量较高时打印调试信息
                logger.debug(f"🔍 VAD调试: 音量={volume_db:.1f}dB(阈值={dynamic_speech_threshold:.1f}dB) 能量={energy:.0f}(阈值=100000) 过零率={zero_crossing_rate:.3f}(范围=0.05-0.5)")
                logger.debug(f"🔍 检测结果: 音量={volume_ok} 能量={energy_ok} 过零率={zcr_ok}")
            
            # 放宽检测条件：只需要满足音量或能量条件
            if (volume_ok or energy_ok) and zcr_ok:
                if self.speech_start_time is None:
                    self.speech_start_time = current_time
                
                if current_time - self.speech_start_time >= self.speech_duration_ms / 1000.0:
                    self.is_speaking = True
                    self.silence_start_time = None
                    logger.info(f"🎤 检测到语音开始! 音量: {volume_db:.1f}dB, 能量: {energy:.0f}, 过零率: {zero_crossing_rate:.3f}")
                    speech_detected = True
            else:
                self.speech_start_time = None
        elif self.is_speaking:
            # 检测语音结束
            if volume_db < dynamic_silence_threshold or energy < 500000:
                if self.silence_start_time is None:
                    self.silence_start_time = current_time
                
                if current_time - self.silence_start_time >= self.silence_duration_ms / 1000.0:
                    self.is_speaking = False
                    self.speech_start_time = None
                    logger.info(f"🔇 检测到语音结束! 音量: {volume_db:.1f}dB, 能量: {energy:.0f}")
            else:
                self.silence_start_time = None
        
        return speech_detected
    
    def get_volume_info(self):
        """获取音量信息"""
        return {
            'current_db': self.last_volume_db,
            'avg_db': self.avg_volume_db,
            'min_db': self.min_volume_db,
            'max_db': self.max_volume_db,
            'is_speaking': self.is_speaking
        }
    
    def get_volume_bar(self, volume_db):
        """生成音量可视化条"""
        try:
            # 将分贝值映射到0-1范围 (-60dB到0dB)
            normalized_volume = max(0, min(1, (volume_db + 60) / 60))
            
            # 计算填充长度
            filled_length = int(normalized_volume * self.volume_bar_length)
            
            # 生成音量条
            if self.is_speaking:
                # 说话时使用红色
                bar = "█" * filled_length + "░" * (self.volume_bar_length - filled_length)
                return f"\033[91m{bar}\033[0m"  # 红色
            else:
                # 静音时使用绿色
                bar = "█" * filled_length + "░" * (self.volume_bar_length - filled_length)
                return f"\033[92m{bar}\033[0m"  # 绿色
                
        except Exception as e:
            logger.debug(f"生成音量条失败: {e}")
            return "░" * self.volume_bar_length
    
    def print_volume_bar(self, volume_db):
        """打印音量可视化条"""
        volume_bar = self.get_volume_bar(volume_db)
        status_emoji = "🎤" if self.is_speaking else "🔇"
        print(f"\r{status_emoji} 音量: {volume_db:6.1f}dB [{volume_bar}]", end="", flush=True)

class AudioProcessor:
    """音频处理进程类 - 在独立进程中处理音频和语音检测"""
    
    def __init__(self, 
                 sample_rate=16000,
                 silence_threshold_db=-35,
                 speech_threshold_db=-25,
                 silence_duration_ms=300,
                 speech_duration_ms=50,
                 shared_variables=None):
        
        # 音频队列
        self.mp_audio_queue = mp.Queue()  # 音频数据队列
        
        # 共享变量（由主进程传入）
        if shared_variables is None:
            # 如果没有传入，创建默认的共享变量
            self.last_speech_end_time = mp.Value(ctypes.c_double, 0.0)
            self.is_speaking = mp.Value(ctypes.c_bool, False)
        else:
            # 使用主进程传入的共享变量
            self.last_speech_end_time = shared_variables['last_speech_end_time']
            self.is_speaking = shared_variables['is_speaking']
        
        # 进程锁（仅在写入时使用）
        self.process_lock = mp.Lock()
        
        # 语音检测器（在子进程中创建）
        self.vad = None
        self.vad_config = {
            'sample_rate': sample_rate,
            'silence_threshold_db': silence_threshold_db,
            'speech_threshold_db': speech_threshold_db,
            'silence_duration_ms': silence_duration_ms,
            'speech_duration_ms': speech_duration_ms
        }
        
        # 进程控制
        self.process = None
        self.is_running = False
        
        # 统计信息
        self.speech_detection_count = 0
        self.last_speech_start_time = None
        
        logger.info("🎤 音频处理器已初始化")
    
    def start(self):
        """启动音频处理进程"""
        if self.process is not None:
            logger.warning("音频处理进程已在运行")
            return
        
        self.is_running = True
        self.process = mp.Process(target=self._audio_processing_worker, daemon=True)
        self.process.start()
        logger.info("🎤 音频处理进程已启动")
    
    def stop(self):
        """停止音频处理进程"""
        if self.process is None:
            return
        
        self.is_running = False
        
        # 清空队列
        while not self.mp_audio_queue.empty():
            try:
                self.mp_audio_queue.get_nowait()
            except:
                break
        
        # 等待进程结束
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
        
        self.process = None
        logger.info("🎤 音频处理进程已停止")
    
    def put_audio_data(self, audio_data, timestamp):
        """向音频队列添加音频数据"""
        try:
            if not self.mp_audio_queue.full():
                self.mp_audio_queue.put((audio_data, timestamp), timeout=0.1)
                return True
            else:
                # 队列满了，丢弃最旧的数据
                try:
                    self.mp_audio_queue.get_nowait()
                    self.mp_audio_queue.put((audio_data, timestamp), timeout=0.1)
                    return True
                except:
                    return False
        except Exception as e:
            logger.debug(f"添加音频数据到队列失败: {e}")
            return False
    
    def get_last_speech_end_time(self):
        """获取最后说话结束时间（读取不需要加锁）"""
        return self.last_speech_end_time.value
    
    def get_is_speaking(self):
        """获取当前说话状态（读取不需要加锁）"""
        return self.is_speaking.value
    
    def _audio_processing_worker(self):
        """音频处理工作进程"""
        logger.info("🎤 音频处理工作进程已启动")
        
        # 在子进程中创建VAD对象
        self.vad = VoiceActivityDetector(**self.vad_config)
        logger.info("🎤 VAD对象已在子进程中创建")
        
        try:
            while self.is_running:
                try:
                    # 从队列获取音频数据
                    audio_data, timestamp = self.mp_audio_queue.get(timeout=0.1)
                    
                    # 语音检测
                    speech_detected = self.vad.detect_speech_start(audio_data)
                    
                    if speech_detected:
                        self.speech_detection_count += 1
                        self.last_speech_start_time = timestamp
                        logger.info(f"🎤 第{self.speech_detection_count}次检测到语音开始! 时间: {timestamp}")
                    
                    # 更新共享状态
                    if self.is_speaking.value != self.vad.is_speaking:
                        if self.vad.is_speaking == False:
                            self.last_speech_end_time.value = timestamp
                        with self.process_lock:
                            self.is_speaking.value = self.vad.is_speaking
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"音频处理出错: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"音频处理工作进程异常: {e}")
        finally:
            logger.info("🎤 音频处理工作进程已结束")

class WebSocketTestSession:
    """WebSocket测试会话管理类 - 裸Opus流解码版本"""
    
    def __init__(self, uri: str = "ws://sd1qv76k2fg6tnkffhdug.apigateway-cn-beijing.volceapi.com/ws/stream"):
        self.uri = uri
        self.websocket = None
        # 音频设备管理 - 匹配服务器Float32 PCM格式
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200, bit_size=pyaudio.paInt16),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paInt16)
            # output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paFloat32)
        )
        
        # 创建共享变量（由主进程管理）
        self.shared_variables = {
            'last_speech_end_time': mp.Value(ctypes.c_double, 0.0),
            'is_speaking': mp.Value(ctypes.c_bool, False)
        }
        
        # 音频处理器（多进程）
        self.audio_processor = AudioProcessor(
            sample_rate=16000,
            silence_threshold_db=-40,  # 静音阈值（更宽松）
            speech_threshold_db=-35,   # 语音阈值（更宽松）
            silence_duration_ms=300,   # 静音持续时间
            speech_duration_ms=50,     # 语音持续时间
            shared_variables=self.shared_variables
        )
        
        # 状态控制
        self.is_running = True
        self.is_playing = True
        self.response_completed = False
        # 音频播放队列和线程
        self.audio_queue = queue.Queue(maxsize=20)
        self.output_stream = None
        self.player_thread = None
        self.tts_initialized = False
        # 响应统计
        self.full_response = ""
        self.chunk_count = 0
        # 延迟统计
        self.first_tts_audio_received_time = None
        self.second_tts_audio_received_time = None
        self.asr_info_received_time = None
        self.first_asr_info_received_time = None
        self.second_asr_info_received_time = None
        self.interrupt_audio_send_time = None
        self.first_request_send_time = None
        # ASREnded和TTSSentenceStart之间的延迟统计
        self.asr_ended_time = None
        self.tts_sentence_start_time = None
        self.asr_to_tts_delays = []  # 存储所有ASREnded到TTSSentenceStart的延迟
        # 信号处理
        signal.signal(signal.SIGINT, self._keyboard_signal)
        # 文件发送模式标记
        self.file_mode = False
        # 预生成的静音音频缓存
        self.silence_audio_cache = None
        # 异步打断队列
        self.interrupt_queue = None
        # 重连配置
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 2.0
        self.reconnect_attempts = 0
        # 初始化Opus解码器（24kHz, 单声道）- 匹配服务器音频格式
        # self.opus_decoder = opuslib.Decoder(fs=24000, channels=1)
        
        # TTS音频录制相关
        self.is_recording_tts = False
        self.current_tts_audio_data = bytearray()
        self.tts_recording_start_time = None
        
        # 多进程语音检测统计
        self.last_speech_end_time = 0.0
        
        # VAD到TTS延迟监测
        self.vad_to_tts_delays = []  # 存储VAD结束到TTS开始的延迟
        self.last_vad_end_time = None  # 最后一次VAD检测到语音结束的时间
        self.vad_end_count = 0  # VAD结束次数统计
        
        # 性能监控
        self.receive_loop_start_time = None
        self.microphone_loop_start_time = None
        self.performance_stats = {
            'receive_messages': 0,
            'microphone_frames': 0,
            'last_stats_time': time.time()
        }
        
    # 直接访问共享变量的方法
    def get_shared_last_speech_end_time(self):
        """直接获取共享的最后说话结束时间（无锁读取）"""
        return self.shared_variables['last_speech_end_time'].value
    
    def get_shared_is_speaking(self):
        """直接获取共享的说话状态（无锁读取）"""
        return self.shared_variables['is_speaking'].value
    
    def monitor_vad_end_time(self):
        """监测VAD结束时间，用于计算VAD到TTS的延迟"""
        current_vad_end_time = self.get_shared_last_speech_end_time()
        
        # 检查是否有新的VAD结束时间
        if current_vad_end_time > self.last_speech_end_time:
            self.last_vad_end_time = current_vad_end_time
            self.vad_end_count += 1
            self.last_speech_end_time = current_vad_end_time
            
            logger.info(f"🎤 VAD检测到语音结束 #{self.vad_end_count}: {datetime.fromtimestamp(current_vad_end_time).strftime('%H:%M:%S.%f')[:-3]}")
            
            return current_vad_end_time
        
        return None
    
    def update_performance_stats(self, task_name: str, count: int = 1):
        """更新性能统计"""
        if task_name == "receive":
            self.performance_stats['receive_messages'] += count
        elif task_name == "microphone":
            self.performance_stats['microphone_frames'] += count
        
        # 每5秒输出一次性能统计
        current_time = time.time()
        if current_time - self.performance_stats['last_stats_time'] > 5.0:
            logger.info(f"📊 性能统计: 接收消息={self.performance_stats['receive_messages']}, 麦克风帧数={self.performance_stats['microphone_frames']}")
            self.performance_stats['last_stats_time'] = current_time

    def _save_tts_audio_file(self):
        """保存录制的TTS音频文件 - 三个版本测试"""
        try:
            if not self.current_tts_audio_data:
                logger.warning("⚠️ 没有录制的TTS音频数据")
                return
            
            # 生成时间戳
            timestamp = datetime.fromtimestamp(self.tts_recording_start_time).strftime('%Y%m%d_%H%M%S_%f')[:-3]
            
            # 确保输出目录存在
            output_dir = "audio_output"
            os.makedirs(output_dir, exist_ok=True)
            
            # 音频参数
            sample_rate = 24000
            channels = 1
            
            # 版本1: 保存原始Float32二进制数据
            filename1 = f"tts_audio_{timestamp}_float32.bin"
            filepath1 = os.path.join(output_dir, filename1)
            with open(filepath1, 'wb') as bin_file:
                bin_file.write(self.current_tts_audio_data)
            logger.info(f"💾 版本1 - Float32二进制: {filepath1}")
            
            # 版本2: 转换为Int16并保存为WAV
            filename2 = f"tts_audio_{timestamp}_int16.wav"
            filepath2 = os.path.join(output_dir, filename2)
            
            # 将Float32转换为Int16
            import struct
            float32_data = self.current_tts_audio_data
            int16_data = bytearray()
            
            for i in range(0, len(float32_data), 4):
                if i + 4 <= len(float32_data):
                    float_val = struct.unpack('f', float32_data[i:i+4])[0]
                    # 将Float32转换为Int16，范围限制在-32768到32767
                    int16_val = max(-32768, min(32767, int(float_val * 32767)))
                    int16_data.extend(struct.pack('h', int16_val))
            
            # 保存Int16 WAV文件
            with wave.open(filepath2, 'wb') as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(2)  # Int16 = 2字节
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(int16_data)
            logger.info(f"💾 版本2 - Int16 WAV: {filepath2}")
            
            # 版本3: 保存Int16二进制数据
            filename3 = f"tts_audio_{timestamp}_int16.bin"
            filepath3 = os.path.join(output_dir, filename3)
            with open(filepath3, 'wb') as bin_file:
                bin_file.write(int16_data)
            logger.info(f"💾 版本3 - Int16二进制: {filepath3}")
            
            # 计算音频时长
            total_bytes = len(self.current_tts_audio_data)
            sample_width = 4  # Float32 = 4字节
            total_samples = total_bytes // sample_width
            duration_seconds = total_samples / sample_rate
            
            logger.info(f"📊 音频信息: {total_bytes} 字节, {duration_seconds:.3f} 秒, {sample_rate}Hz, {channels}声道")
            logger.info(f"📊 转换后Int16: {len(int16_data)} 字节")
            
            # 清空录制数据
            self.current_tts_audio_data = bytearray()
            self.tts_recording_start_time = None
            
        except Exception as e:
            logger.error(f"❌ 保存TTS音频文件失败: {e}")

    def _keyboard_signal(self, sig, frame):
        """处理键盘中断信号"""
        logger.info("收到 Ctrl+C 信号，正在停止...")
        self.is_playing = False
        self.is_running = False
        
        # 强制退出保护机制
        def force_exit():
            logger.warning("程序停止超时，强制退出...")
            os._exit(1)
        
        # 3秒后强制退出
        threading.Timer(3.0, force_exit).start()
    
    def _audio_player_thread(self):
        """唯一的TTS音频播放线程，支持打断和恢复"""
        logger.info("🎵 播放线程已启动，等待音频数据...")
        while self.is_playing:
            try:
                # 从队列获取PCM音频数据
                pcm_data = self.audio_queue.get(timeout=0.01)
                if pcm_data is not None and self.output_stream:
                    try:
                        if self.output_stream.is_active():
                            self.output_stream.write(pcm_data)
                        else:
                            logger.warning("音频输出流未激活，跳过播放")
                            time.sleep(0.01)
                    except Exception as audio_error:
                        error_msg = str(audio_error)
                        if "PortAudio" in error_msg or "Internal PortAudio error" in error_msg or "Stream not open" in error_msg:
                            logger.error(f"PortAudio错误: {error_msg}")
                            try:
                                logger.info("尝试重新初始化音频输出流...")
                                if self.output_stream:
                                    try:
                                        if self.output_stream.is_active():
                                            self.output_stream.stop_stream()
                                        self.output_stream.close()
                                    except Exception as close_error:
                                        logger.warning(f"关闭音频流时出错: {close_error}")
                                self.output_stream = self.audio_device.open_output_stream()
                                self.output_stream.start_stream()
                                logger.info("音频输出流重新初始化成功")
                            except Exception as reinit_error:
                                logger.error(f"重新初始化音频输出流失败: {reinit_error}")
                                time.sleep(0.1)
                        else:
                            logger.error(f"音频播放错误: {error_msg}")
                            time.sleep(0.01)
                self.audio_queue.task_done()
            except queue.Empty:
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"音频播放线程错误: {e}")
                time.sleep(0.01)
        logger.info("🔇 播放线程结束")

    def _clear_audio_buffers(self):
        """清空音频缓冲区"""
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

    def initialize_tts_player(self):
        """初始化TTS音频播放器"""
        if self.tts_initialized:
            return
            
        try:
            self.output_stream = self.audio_device.open_output_stream()
            self.output_stream.start_stream()
            
            self.player_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
            self.player_thread.start()
            
            self.tts_initialized = True
            logger.info(f"🎵 TTS音频播放器已初始化")
            
        except Exception as e:
            logger.error(f"初始化TTS播放器失败: {e}")
            raise
    
    def handle_websocket_response(self, data: dict):
        """处理WebSocket响应"""
        if "event" in data:
            event_id = data["event"]
            payload_msg = data.get("payload_msg", {})
            if event_id == 450:  # ASRInfo
                logger.info("🎤 收到ASRInfo事件(450)，触发AI播报打断")
                self.asr_info_received_time = time.time()
                self._clear_audio_buffers()
                logger.debug("⏸️ 播放已暂停")
            elif event_id == 451:  # ASRResponse
                self.chunk_count += 1
                content = payload_msg.get("results", [{}])[0].get("text", "")
                self.full_response += content
                logger.info(f"ASR收到第{self.chunk_count}个内容片段: '{content}'")
            elif event_id == 459:  # ASREnded
                logger.info("🎤 ASR结束")
                if self.first_request_send_time is not None:
                    delay = time.time() - self.first_request_send_time
                    self.asr_to_tts_delays.append(delay)
                    logger.info(f"⏱️ ASR结束到第一个request发送完成延迟: {delay:.3f}秒")
                self.asr_ended_time = time.time()
                logger.debug(f"⏱️ ASREnded时间戳: {self.asr_ended_time}")
            elif event_id == 350:  # TTSSentenceStart
                logger.info("🎵 TTS语音合成开始...")
                # 记录TTSSentenceStart时间戳
                self.tts_sentence_start_time = time.time()
                # logger.info(f"⏱️ TTSSentenceStart时间戳: {self.tts_sentence_start_time}")
                
                # 计算ASREnded到TTSSentenceStart的延迟（只计算第一个TTSSentenceStart）
                if self.asr_ended_time is not None:
                    total_delay = self.tts_sentence_start_time - self.get_shared_last_speech_end_time()
                    self.vad_to_tts_delays.append(total_delay)
                    logger.info(f"⏱️ VAD到TTSSentenceStart总延迟: {total_delay:.3f}秒")
                    asr_delay = self.asr_ended_time - self.get_shared_last_speech_end_time()
                    self.asr_to_tts_delays.append(asr_delay)
                    logger.info(f"⏱️ VAD到ASREnded延迟: {asr_delay:.3f}秒")
                    delay = self.tts_sentence_start_time - self.asr_ended_time
                    self.asr_to_tts_delays.append(delay)
                    logger.info(f"⏱️ ASREnded到第一个TTSSentenceStart延迟: {delay:.3f}秒")
                    
                    # 清除asr_ended_time，避免后续TTSSentenceStart重复计算
                    self.asr_ended_time = None
                    
                    # 输出延迟统计信息
                    if len(self.asr_to_tts_delays) > 1:
                        avg_delay = sum(self.asr_to_tts_delays) / len(self.asr_to_tts_delays)
                        min_delay = min(self.asr_to_tts_delays)
                        max_delay = max(self.asr_to_tts_delays)
                        logger.info(f"📊 ASR到TTS延迟统计 (共{len(self.asr_to_tts_delays)}次): 平均={avg_delay:.3f}s, 最小={min_delay:.3f}s, 最大={max_delay:.3f}s")
                
                # 开始录制TTS音频
                self.is_recording_tts = False
                self.current_tts_audio_data = bytearray()
                self.tts_recording_start_time = time.time()
                logger.debug(f"🎙️ 开始录制TTS音频，时间戳: {datetime.fromtimestamp(self.tts_recording_start_time).strftime('%Y%m%d_%H%M%S_%f')[:-3]}")
                
                if self.first_tts_audio_received_time is None:
                    self.first_tts_audio_received_time = time.time()
                    self.first_asr_info_received_time = self.asr_info_received_time
                if self.interrupt_audio_send_time is not None:
                    if self.second_tts_audio_received_time is None:
                        self.second_tts_audio_received_time = time.time()
                        self.second_asr_info_received_time = self.asr_info_received_time
            elif event_id == 351:  # TTSSentenceEnd
                logger.debug("当前句子TTS语音合成完成")
                # 结束录制并保存文件
                if self.is_recording_tts and self.tts_recording_start_time is not None:
                    self.is_recording_tts = False
                    self._save_tts_audio_file()
            elif event_id == 352:  # TTSResponse
                # 处理TTS音频数据 - 可能是PCM格式，不是Opus
                audio_data = payload_msg
                logger.debug(f"🎵 收到TTS音频数据: {len(audio_data)} 字节")
                
                # 如果正在录制，保存音频数据
                if self.is_recording_tts:
                    self.current_tts_audio_data.extend(audio_data)
                    logger.debug(f"🎙️ 录制TTS音频数据: {len(audio_data)} 字节 (累计: {len(self.current_tts_audio_data)} 字节)")
                
                # 尝试多种音频格式处理
                try:
                    # 方法1: 尝试作为PCM数据直接播放
                    if len(audio_data) > 0:
                        self.audio_queue.put(audio_data)
                        logger.debug(f"✅ 直接播放PCM音频: {len(audio_data)} 字节")
                    else:
                        logger.warning("⚠️ 收到空的音频数据")
                        
                except Exception as e:
                    logger.error(f"❌ 处理TTS音频数据失败: {e}")
                    
                # 注释掉Opus解码，因为服务器返回的是Float32 PCM格式
                # try:
                #     # 20ms帧，24kHz单声道，frame_size=480
                #     pcm_data = self.opus_decoder.decode(audio_data, frame_size=480)
                #     self.audio_queue.put(pcm_data)
                #     logger.debug(f"🎵 Opus解码成功: {len(audio_data)} -> {len(pcm_data)} 字节")
                # except Exception as e:
                #     logger.error(f"❌ Opus解码失败: {e}")
            elif event_id == ServerEvent.ChatResponse:  # ChatResponse
                logger.info(f"🎵 收到ChatResponse事件:{payload_msg.get("content", "")}")
            elif event_id == 353:  # ChatEnded
                logger.info("服务器一次回复结束，等待用户继续说话...")
            elif event_id == 999:  # Error
                logger.error(f"发生错误: {data.get('message', '未知错误')}")
                # 发生错误时也设置响应完成标志
                self.response_completed = True

    def _is_websocket_closed(self) -> bool:
        """检查WebSocket是否已关闭，兼容不同版本的websockets库"""
        try:
            if self.websocket is None:
                return True
            
            # 检查是否有state属性 (新版websockets)
            if hasattr(self.websocket, 'state'):
                try:
                    from websockets.protocol import State
                    return self.websocket.state != State.OPEN
                except ImportError:
                    pass
            
            # 检查是否有closed属性 (某些版本websockets)
            if hasattr(self.websocket, 'closed'):
                return self.websocket.closed
            
            # 检查是否有open属性 (某些版本)
            if hasattr(self.websocket, 'open'):
                return not self.websocket.open
            
            # 检查是否有close_code属性，如果有且不为None，说明连接已关闭
            if hasattr(self.websocket, 'close_code'):
                return self.websocket.close_code is not None
            
            # 最后的兜底方案，假设连接未关闭
            return False
            
        except Exception as e:
            logger.debug(f"检查WebSocket关闭状态时出错: {e}")
            return True  # 出错时假设连接已关闭

    async def receive_loop(self):
        """接收消息循环 - 使用run_in_executor避免阻塞"""
        logger.info("🔄 receive_loop 已启动，开始监听WebSocket消息...")
        try:
            while self.is_running and not self.response_completed:
                try:
                    # 检查WebSocket连接状态
                    if self._is_websocket_closed():
                        logger.info("WebSocket连接已关闭，尝试重连...")
                        if await self._reconnect_websocket():
                            logger.info("重连成功，继续接收消息")
                            continue
                        else:
                            logger.error("重连失败，停止接收")
                            self.response_completed = True
                            break
                    else:
                        logger.debug(f"🔍 WebSocket连接状态正常")
                    
                    # 使用run_in_executor来处理websocket.recv()，避免阻塞事件循环
                    try:
                        # 使用run_in_executor来处理websocket.recv()
                        response_data = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
                        data = client_parse_response(response_data)
                        self.handle_websocket_response(data)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.error(f"🔍 receive_loop 接收消息时出错: {e}")
                        continue
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            self.response_completed = True
        finally:
            logger.info("🔄 receive_loop 已结束")
    
    async def microphone_input_loop(self):
        """麦克风输入循环，带多进程语音活动检测"""
        logger.info("🎤 microphone_input_loop 已启动，开始录制音频...")
        try:
            input_stream = self.audio_device.open_input_stream()
            logger.info("🎤 已打开麦克风，开始录制音频流...")
            logger.info("🎤 多进程语音检测已启用，将实时监测说话开始瞬间")
            
            # 启动音频处理进程
            self.audio_processor.start()
            logger.info("🎤 音频处理进程已启动")
            
            # 音量显示计数器
            volume_display_counter = 0
            last_speech_end_time = 0.0
            
            while self.is_running and not self.response_completed:
                try:
                    # 检查退出条件和WebSocket连接状态
                    if not self.is_running or self._is_websocket_closed():
                        logger.info("检测到连接断开，尝试重连...")
                        if await self._reconnect_websocket():
                            logger.info("重连成功，继续录制")
                            continue
                        else:
                            logger.error("重连失败，停止录制")
                            break
                    
                    # 读取麦克风数据
                    audio_chunk = input_stream.read(
                        self.audio_device.input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 获取当前时间戳
                    current_timestamp = time.time()
                    # 🔥 使用简洁的task_request方式发送音频数据
                    await send_audio_task_request(self.websocket, audio_chunk, "test_user_123444")
                    
                    # 向音频处理进程发送音频数据
                    self.audio_processor.put_audio_data(audio_chunk, current_timestamp)
                    await asyncio.sleep(0.01)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接关闭，尝试重连...")
                    if await self._reconnect_websocket():
                        logger.info("重连成功，继续录制")
                        continue
                    else:
                        logger.error("重连失败，停止录制")
                        break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭，尝试重连...")
                    if await self._reconnect_websocket():
                        logger.info("重连成功，继续录制")
                        continue
                    else:
                        logger.error("重连失败，停止录制")
                        break
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection", "ping", "timeout"]):
                        logger.info("检测到连接断开相关错误，尝试重连...")
                        if await self._reconnect_websocket():
                            logger.info("重连成功，继续录制")
                            continue
                        else:
                            logger.error("重连失败，停止录制")
                            break
                    await asyncio.sleep(0.1)
            
            # 停止音频处理进程
            self.audio_processor.stop()
            
            # 显示多进程语音检测统计
            logger.info(f"🎤 多进程语音检测统计: 最后语音结束时间: {last_speech_end_time:.3f}")
            if last_speech_end_time > 0:
                logger.info(f"🎤 最后语音结束时间: {datetime.fromtimestamp(last_speech_end_time).strftime('%H:%M:%S.%f')[:-3]}")
            
            # 显示VAD到TTS延迟统计
            if self.vad_to_tts_delays:
                avg_delay = sum(self.vad_to_tts_delays) / len(self.vad_to_tts_delays)
                min_delay = min(self.vad_to_tts_delays)
                max_delay = max(self.vad_to_tts_delays)
                logger.info(f"📊 VAD到TTS延迟统计 (共{len(self.vad_to_tts_delays)}次):")
                logger.info(f"  平均延迟: {avg_delay:.3f}秒")
                logger.info(f"  最小延迟: {min_delay:.3f}秒")
                logger.info(f"  最大延迟: {max_delay:.3f}秒")
                logger.info(f"  VAD结束次数: {self.vad_end_count}")
            else:
                logger.info("📊 未检测到VAD到TTS延迟数据")
            
            logger.info("🔇 麦克风录制已停止")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            # 确保停止音频处理进程
            self.audio_processor.stop()
        finally:
            logger.info("🎤 microphone_input_loop 已结束")
    
    async def auto_stop_after_timeout(self, timeout_seconds=20):
        """自动停止录制的超时处理"""
        await asyncio.sleep(timeout_seconds)
        logger.info(f"录制时间达到{timeout_seconds}秒，自动停止...")
        self.is_running = False
    
    async def send_control_message(self, action: str):
        """发送控制消息（连接、session等）"""
        try:
            # 根据action确定客户端事件ID
            session_id = None
            payload_data = {}  # 设置事件ID
            if action == "start_connection":
                event_id = 1
            elif action == "end_connection":
                event_id = 2
            elif action == "start_session":
                session_id = "test_user_123444"
                payload_data = {
                    "chat_info": {
                        "chat_id": "test_user_123444",
                        "user_id": "test_user_123444"
                    }
                }
                event_id = 100
            elif action == "end_session":
                session_id = "test_user_123444"
                event_id = 102
            else:
                event_id = 1001  # 默认事件ID
            
            
            request = client_generate_request(
                payload_data=payload_data,
                message_type=CLIENT_FULL_REQUEST,
                message_type_specific_flags=MSG_WITH_EVENT,
                serial_method=JSON,
                compression_type=GZIP,
                event=event_id,
                session_id=session_id
            )
            await self.websocket.send(bytes(request))
            logger.info(f"📤 发送控制消息: {action} (事件ID: {event_id})")
            
        except Exception as e:
            logger.error(f"发送控制消息失败: {e}")
            return False
        return True

    async def start_connection_handshake(self):
        """执行连接握手流程"""
        logger.info("🤝 开始连接握手流程...")
        
        # 第一步：发送开始连接消息
        if not await self.send_control_message("start_connection"):
            return False
            
        # 等待连接确认
        logger.info("⏳ 等待连接确认消息...")
        response_data = await self.websocket.recv()
        logger.info(f"📥 握手收到消息: {len(response_data)} 字节")
        data = client_parse_response(response_data)
        logger.info(f"📋 握手消息: event={data.get('event', 'N/A')}")
        if data.get("event") != ServerEvent.ConnectionStarted:
            logger.error(f"❌ 连接确认失败，期望事件: {ServerEvent.ConnectionStarted}, 实际: {data.get('event')}")
            return False
        
        # 第二步：发送开始session消息
        if not await self.send_control_message("start_session"):
            return False
            
        # 等待session确认
        logger.info("⏳ 等待session确认消息...")
        response_data = await self.websocket.recv()
        logger.info(f"📥 握手收到消息: {len(response_data)} 字节")
        data = client_parse_response(response_data)
        logger.info(f"📋 握手消息: event={data.get('event', 'N/A')}")
        if data.get("event") != ServerEvent.SessionStarted:
            logger.error(f"❌ session确认失败，期望事件: {ServerEvent.SessionStarted}, 实际: {data.get('event')}")
            return False
            
        logger.info("🎉 连接和Session握手完成！")
        return True

    async def end_session_handshake(self):
        """执行结束握手流程"""
        logger.info("👋 开始结束握手流程...")
        
        try:
            # 检查WebSocket连接状态
            if self._is_websocket_closed():
                logger.warning("⚠️ WebSocket连接已关闭，跳过结束握手")
                return
            
            # 第一步：结束session
            try:
                if await self.send_control_message("end_session"):
                    data = client_parse_response(await self.websocket.recv())
                    if data.get("event") != ServerEvent.SessionFinished:
                        logger.warning("⚠️ 结束session失败")
                        return
                else:
                    logger.warning("⚠️ 发送end_session消息失败")
            except Exception as e:
                logger.warning(f"⚠️ 结束session时出错: {e}")
            
            # 第二步：结束连接
            try:
                if await self.send_control_message("end_connection"):
                    data = client_parse_response(await self.websocket.recv())
                    if data.get("event") != ServerEvent.ConnectionFinished:
                        logger.warning("⚠️ 结束connection失败")
                        return
                else:
                    logger.warning("⚠️ 发送end_connection消息失败")
            except Exception as e:
                logger.warning(f"⚠️ 结束connection时出错: {e}")
                
        except Exception as e:
            logger.warning(f"⚠️ 结束握手流程时出错: {e}")
        finally:
            logger.info("✅ 结束握手完成！")

    async def start(self):
        """启动WebSocket测试会话"""
        try:
            # 添加WebSocket连接配置，解决ping timeout问题
            async with websockets.connect(
                self.uri,
                ping_interval=120,      # 每120秒发送一次ping（更保守）
                ping_timeout=60,       # ping超时时间60秒（更宽松）
                close_timeout=10,      # 关闭超时时间10秒
                max_size=1000000000,   # 最大消息大小1GB
                compression=None,      # 禁用压缩避免问题
                max_queue=32
            ) as websocket:
                self.websocket = websocket
                logger.info("已连接到WebSocket服务器")
                logger.info("=== 开始麦克风音频测试 ===")
                
                # 执行连接和session握手
                if not await self.start_connection_handshake():
                    logger.error("❌ 连接握手失败，退出测试")
                    return
                
                # 在会话开始时就初始化TTS播放器，准备接收音频
                self.initialize_tts_player()
                logger.info("🎵 TTS播放器已预先初始化，准备接收多轮对话...")
                
                # 等待任务完成或者程序停止
                try:
                    logger.info("🚀 开始高并发异步任务执行...")
                    
                    # 创建任务，使用更高效的方式
                    tasks = [
                        asyncio.create_task(self.receive_loop(), name="receive_loop"),
                        asyncio.create_task(self.microphone_input_loop(), name="microphone_loop")
                    ]
                    
                    logger.info(f"📋 已创建 {len(tasks)} 个并发任务")
                    
                    # 使用asyncio.gather进行高并发执行
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # 检查任务执行结果
                    task_names = ["receive_loop", "microphone_loop"]
                    for i, (name, result) in enumerate(zip(task_names, results)):
                        if isinstance(result, Exception):
                            logger.error(f"❌ 任务 {name} 执行出错: {result}")
                        else:
                            logger.info(f"✅ 任务 {name} 执行完成")
                    
                    logger.info("🎉 所有高并发任务执行完成")
                except Exception as e:
                    logger.error(f"❌ 任务执行出错: {e}")
                        
                except asyncio.CancelledError:
                    logger.info("任务被取消")
                
                finally:
                    # 确保清理资源
                    logger.info("🧹 开始清理资源...")
                    self.is_running = False
                    self.response_completed = True
                    
                    # 停止音频处理进程
                    if hasattr(self, 'audio_processor'):
                        self.audio_processor.stop()
                    
                    # 清理音频设备
                    if hasattr(self, 'audio_device'):
                        self.audio_device.cleanup()
                    
                    # 关闭WebSocket连接
                    if self.websocket and not self._is_websocket_closed():
                        await self.websocket.close()
                    
                    logger.info("✅ 资源清理完成")
                
                print(f"\n=== 麦克风音频会话结束，总共收到 {self.chunk_count} 个内容片段 ===")
                logger.info(f"完整响应内容: {self.full_response}")
                
                # 输出ASREnded到第一个TTSSentenceStart延迟统计总结
                if self.asr_to_tts_delays:
                    print("\n" + "="*50)
                    print("🎯 ASREnded到第一个TTSSentenceStart延迟统计总结")
                    print("="*50)
                    print(f"📊 总延迟次数: {len(self.asr_to_tts_delays)}")
                    print(f"⏱️ 平均延迟: {sum(self.asr_to_tts_delays) / len(self.asr_to_tts_delays):.3f}秒")
                    print(f"⚡ 最小延迟: {min(self.asr_to_tts_delays):.3f}秒")
                    print(f"🐌 最大延迟: {max(self.asr_to_tts_delays):.3f}秒")
                    print("📈 详细延迟列表:")
                    for i, delay in enumerate(self.asr_to_tts_delays, 1):
                        print(f"  第{i}次: {delay:.3f}秒")
                    print("="*50)
                else:
                    print("\n⚠️ 未检测到ASREnded到第一个TTSSentenceStart的延迟数据")

                # 执行结束握手
                await self.end_session_handshake()
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"连接WebSocket失败: {str(e)}")
        finally:
            # 设置停止标志
            self.is_running = False
            self.is_playing = False
            # 清理资源
            self.audio_device.cleanup()

    def read_audio_file(self, file_path):
        """读取音频文件并返回符合input_audio_config格式的字节数据"""
        try:
            # 检查文件扩展名
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # 使用pydub加载音频文件
            if file_ext in ['.wav', '.mp3']:
                audio = AudioSegment.from_file(file_path)
            else:
                logger.error(f"不支持的音频格式: {file_ext}")
                return None
            
            # 转换为符合input_audio_config的格式
            # 目标格式: PCM, 16kHz, 单声道, 16位
            target_audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            
            # 导出为PCM格式的字节数据
            buffer = io.BytesIO()
            target_audio.export(buffer, format="s16le")
            pcm_data = buffer.getvalue()
            
            logger.info(f"音频转换完成: {len(pcm_data)} 字节, 16kHz, 单声道, 16位PCM")
            return pcm_data
                
        except Exception as e:
            logger.error(f"读取音频文件 {file_path} 失败: {str(e)}")
            return None
    
    def generate_silence_audio(self, duration_ms=500):
        """生成指定时长的静音音频"""
        try:
            # 创建静音音频段，16kHz, 单声道, 16位
            silence = AudioSegment.silent(duration=duration_ms)
            silence = silence.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            
            # 导出为PCM格式的字节数据
            buffer = io.BytesIO()
            silence.export(buffer, format="s16le")
            pcm_data = buffer.getvalue()
            
            logger.info(f"生成静音音频: {len(pcm_data)} 字节, {duration_ms}ms, 16kHz, 单声道, 16位PCM")
            return pcm_data
            
        except Exception as e:
            logger.error(f"生成静音音频失败: {str(e)}")
            return None
    
    def get_or_create_silence_audio(self, duration_ms=1000):
        """获取或创建指定时长的静音音频缓存"""
        if self.silence_audio_cache is None:
            self.silence_audio_cache = self.generate_silence_audio(duration_ms)
            logger.info(f"创建并缓存 {duration_ms}ms 静音音频")
        return self.silence_audio_cache

    async def send_audio_files_loop(self):
        """发送测试音频文件数据的任务 - 打断测试模式"""
        try:
            # 测试音频文件列表
            test_audio_files = {
                "interrupt_audio": "/Users/zhipengsun/workspace/aura_backend/audio_test_data/20250702_221100_停一下_converted.wav", 
                "request_audio_1": "/Users/zhipengsun/workspace/aura_backend/audio_test_data/20250702_221026_介绍一下你的功能和特_converted.wav",
                "request_audio_2": "/Users/zhipengsun/workspace/aura_backend/audio_test_data/20250702_221046_介绍一下你的兴趣和爱_converted.wav"
            }
            
            logger.info("🎯 开始打断测试模式")
            
            # 第一步：发送第一个请求音频
            logger.info("📤 第一步：发送第一个请求音频 (request_audio_1)")
            if not await self._send_audio_file(test_audio_files["request_audio_1"]):
                logger.error("发送第一个请求音频失败")
                return
            
            # 记录第一个request发送完成时间
            self.first_request_send_time = time.time()
            logger.info(f"⏱️ 第一个request发送完成时间: {self.first_request_send_time}")

            # 等待TTS回复开始
            logger.info("⏳ 等待TTS回复开始...")
            await self._wait_for_tts_start()
            
            # # 等待一小段时间让TTS开始播放
            await asyncio.sleep(3.0)
            
            # 第二步：发送打断音频（确保已收到第一个TTS）
            logger.info("📤 第二步：发送打断音频 (interrupt_audio)")
            if not await self._send_audio_file(test_audio_files["interrupt_audio"]):
                logger.error("发送打断音频失败")
                return
            
            # 记录打断音频发送完成时间
            self.interrupt_audio_send_time = time.time()
            logger.info(f"⏱️ 打断音频发送完成时间: {self.interrupt_audio_send_time}")
            
            # 发送1秒静音（使用缓存的静音音频）
            await self._send_silence_audio()

            while True:
                if self.second_tts_audio_received_time is not None and self.second_asr_info_received_time is not None:
                    break
                await asyncio.sleep(0.1)
            
            # 等待一段时间观察后续行为
            await asyncio.sleep(3.0)
            
            logger.info("✅ 打断测试完成")
                    
        except Exception as e:
            logger.error(f"发送音频文件失败: {str(e)}")
            self.is_running = False
    
    async def _send_audio_file(self, audio_file_path: str) -> bool:
        """发送单个音频文件"""
        try:
            logger.info(f"正在发送音频文件: {audio_file_path}")
            
            # 检查文件是否存在
            if not os.path.exists(audio_file_path):
                logger.warning(f"音频文件不存在: {audio_file_path}")
                return False
            
            # 读取音频文件数据
            audio_data = self.read_audio_file(audio_file_path)
            if audio_data is None:
                logger.error(f"无法读取音频文件: {audio_file_path}")
                return False
            
            # 模拟实时发送，将音频数据分片发送
            # 200ms音频块大小：16kHz × 1声道 × 2字节 × 0.2秒 = 6400字节
            CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
            total_chunks = len(audio_data) // CHUNK_SIZE + (1 if len(audio_data) % CHUNK_SIZE else 0)
            
            logger.info(f"开始分片发送音频数据，总共 {total_chunks} 个片段")
            
            for i in range(0, len(audio_data), CHUNK_SIZE):
                if not self.is_running or self._is_websocket_closed():
                    break
                    
                chunk = audio_data[i:i + CHUNK_SIZE]
                
                try:
                    # 🔥 使用简洁的task_request方式发送音频数据
                    await send_audio_task_request(self.websocket, chunk, "test_user_123444")
                    logger.debug(f"📤 发送音频文件块: {len(chunk)} 字节")
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.2)  # 200ms间隔，匹配音频块时长
                    
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接关闭，停止文件发送")
                    return False
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭，停止文件发送")
                    return False
                except Exception as e:
                    logger.error(f"发送音频文件块失败: {e}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止文件发送")
                        return False
                    await asyncio.sleep(0.1)
            
            logger.info(f"音频文件发送完成: {audio_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"发送音频文件失败: {e}")
            return False
    
    async def _send_silence_audio(self) -> bool:
        """发送缓存的静音音频"""
        try:
            logger.info("正在发送1秒静音音频...")
            
            # 获取缓存的静音音频
            silence_data = self.get_or_create_silence_audio(1000)  # 1000ms = 1秒
            if silence_data is None:
                logger.error("无法生成静音音频")
                return False
            
            # 模拟实时发送，将音频数据分片发送
            # 200ms音频块大小：16kHz × 1声道 × 2字节 × 0.2秒 = 6400字节
            CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
            total_chunks = len(silence_data) // CHUNK_SIZE + (1 if len(silence_data) % CHUNK_SIZE else 0)
            
            logger.info(f"开始分片发送静音音频数据，总共 {total_chunks} 个片段")
            
            for i in range(0, len(silence_data), CHUNK_SIZE):
                if not self.is_running or self._is_websocket_closed():
                    break
                    
                chunk = silence_data[i:i + CHUNK_SIZE]
                
                try:
                    # 🔥 使用简洁的task_request方式发送音频数据
                    await send_audio_task_request(self.websocket, chunk, "test_user_123444")
                    logger.debug(f"📤 发送静音音频块: {len(chunk)} 字节")
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.2)  # 200ms间隔，匹配音频块时长
                    
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接关闭，停止静音音频发送")
                    return False
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭，停止静音音频发送")
                    return False
                except Exception as e:
                    logger.error(f"发送静音音频块失败: {e}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止静音音频发送")
                        return False
                    await asyncio.sleep(0.1)
            
            logger.info("静音音频发送完成")
            return True
            
        except Exception as e:
            logger.error(f"发送静音音频失败: {e}")
            return False
    
    async def _wait_for_tts_start(self):
        """等待TTS开始"""
        while True:
            if self.first_tts_audio_received_time is not None:
                logger.info("✅ 检测到TTS开始")
                return
            await asyncio.sleep(0.1)
    
    async def start_with_files(self):
        """启动WebSocket测试会话（文件模式）- 打断测试"""
        self.file_mode = True
        try:
            # 添加WebSocket连接配置，解决ping timeout问题
            async with websockets.connect(
                self.uri,
                ping_interval=30,      # 每30秒发送一次ping（更保守）
                ping_timeout=15,       # ping超时时间15秒（更宽松）
                close_timeout=10,      # 关闭超时时间10秒
                max_size=1000000000,   # 最大消息大小1GB
                compression=None,      # 禁用压缩避免问题
                max_queue=32
            ) as websocket:
                self.websocket = websocket
                logger.info("已连接到WebSocket服务器")
                logger.info("=== 开始打断测试模式 ===")
                
                # 先启动接收消息的任务，确保握手消息能被处理
                receive_task = asyncio.create_task(self.receive_loop())
                
                # 等待一小段时间确保receive_loop已启动
                await asyncio.sleep(0.1)
                
                # 执行连接和session握手
                if not await self.start_connection_handshake():
                    logger.error("❌ 连接握手失败，退出测试")
                    receive_task.cancel()
                    return
                
                # 在会话开始时就初始化TTS播放器，准备接收音频
                self.initialize_tts_player()
                logger.info("🎵 TTS播放器已预先初始化，准备接收音频...")
                
                # 创建其他异步任务
                file_send_task = asyncio.create_task(self.send_audio_files_loop())
                
                # 等待任务完成或者程序停止
                tasks = [receive_task, file_send_task]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    
                    # 如果程序需要停止，取消所有待处理的任务
                    if not self.is_running:
                        for task in pending:
                            task.cancel()
                        # 等待任务真正取消
                        await asyncio.gather(*pending, return_exceptions=True)
                        
                except asyncio.CancelledError:
                    logger.info("任务被取消")
                
                print(f"\n=== 打断测试完成，总共收到 {self.chunk_count} 个内容片段 ===")
                logger.info(f"完整响应内容: {self.full_response}")
                
                # 输出ASREnded到第一个TTSSentenceStart延迟统计总结
                if self.asr_to_tts_delays:
                    print("\n" + "="*50)
                    print("🎯 ASREnded到第一个TTSSentenceStart延迟统计总结")
                    print("="*50)
                    print(f"📊 总延迟次数: {len(self.asr_to_tts_delays)}")
                    print(f"⏱️ 平均延迟: {sum(self.asr_to_tts_delays) / len(self.asr_to_tts_delays):.3f}秒")
                    print(f"⚡ 最小延迟: {min(self.asr_to_tts_delays):.3f}秒")
                    print(f"🐌 最大延迟: {max(self.asr_to_tts_delays):.3f}秒")
                    print("📈 详细延迟列表:")
                    for i, delay in enumerate(self.asr_to_tts_delays, 1):
                        print(f"  第{i}次: {delay:.3f}秒")
                    print("="*50)
                else:
                    print("\n⚠️ 未检测到ASREnded到第一个TTSSentenceStart的延迟数据")
                
                # 输出打断测试的延迟统计结果
                print("\n" + "="*50)
                print("🎯 打断测试延迟统计结果")
                print("="*50)
                
                if (self.first_request_send_time is not None and 
                    self.first_tts_audio_received_time is not None):
                    delay0 = self.first_tts_audio_received_time - self.first_request_send_time
                    print(f"⏱️ 延迟0 - 第一个request发送完成到第一个TTS开始: {delay0:.3f}秒")
                else:
                    print("⚠️ 未统计到延迟0数据")
                
                if (self.interrupt_audio_send_time is not None and 
                    self.second_asr_info_received_time is not None):
                    delay1 = self.second_asr_info_received_time - self.interrupt_audio_send_time
                    print(f"⏱️ 延迟1 - 打断音频发送完成到ASRInfo接收: {delay1:.3f}秒")
                else:
                    print("⚠️ 未统计到延迟1数据")
                
                if (self.second_asr_info_received_time is not None and 
                    self.second_tts_audio_received_time is not None):
                    delay2 = self.second_tts_audio_received_time - self.second_asr_info_received_time
                    print(f"⏱️ 延迟2 - ASRInfo接收到下一个TTS开始: {delay2:.3f}秒")
                else:
                    print("⚠️ 未统计到延迟2数据")
                
                if (self.interrupt_audio_send_time is not None and 
                    self.second_tts_audio_received_time is not None):
                    total_delay = self.second_tts_audio_received_time - self.interrupt_audio_send_time
                    print(f"⏱️ 总延迟 - 打断音频发送完成到下一个TTS开始: {total_delay:.3f}秒")
                else:
                    print("⚠️ 未统计到总延迟数据")
                
                print("="*50)
   
                # 执行结束握手
                await self.end_session_handshake()
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"连接WebSocket失败: {str(e)}")
        finally:
            # 设置停止标志
            self.is_running = False
            self.is_playing = False
            # 清理资源
            self.audio_device.cleanup()

    async def interrupt_handler(self):
        """异步打断处理"""
        logger.info("🎛️ 异步打断控制系统已启动")
        while self.is_running:
            try:
                # 从队列获取打断信号
                interrupt_signal = await self.interrupt_queue.get()
                if interrupt_signal:
                    logger.info("🎤 收到打断信号，暂停播放...")
                    self.is_playing = False
                    await asyncio.sleep(interrupt_signal)
                    logger.info("🎤 已恢复播放")
                    self.is_playing = True
            except asyncio.CancelledError:
                logger.info("异步打断任务被取消")
                break
            except Exception as e:
                logger.error(f"异步打断处理时发生错误: {e}")
                await asyncio.sleep(0.1)
        logger.info("🔇 异步打断控制系统已停止")

    async def _reconnect_websocket(self):
        """重连WebSocket连接"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"❌ 重连次数已达上限 ({self.max_reconnect_attempts})，停止重连")
            return False
        
        self.reconnect_attempts += 1
        logger.info(f"🔄 尝试重连WebSocket (第{self.reconnect_attempts}次)...")
        
        try:
            # 等待一段时间后重连
            await asyncio.sleep(self.reconnect_delay)
            
            # 重新建立连接
            self.websocket = await websockets.connect(
                self.uri,
                open_timeout=5,
                ping_interval=30,      # 每30秒发送一次ping（更保守）
                ping_timeout=15,       # ping超时时间15秒（更宽松）
                close_timeout=10,      # 关闭超时时间10秒
                max_size=1000000000,   # 最大消息大小1GB
                compression=None,      # 禁用压缩避免问题
                max_queue=32,          # 限制队列大小
                write_limit=2**16      # 限制写入缓冲区
            )
            
            logger.info("✅ WebSocket重连成功")
            
            # 重新执行握手
            if await self.start_connection_handshake():
                logger.info("✅ 重连后握手成功")
                self.reconnect_attempts = 0  # 重置重连计数
                return True
            else:
                logger.error("❌ 重连后握手失败")
                return False
                
        except Exception as e:
            logger.error(f"❌ WebSocket重连失败: {e}")
            return False

async def test_audio_websocket_stream():
    """测试带预处理音频文件的WebSocket流式接口"""
    session = WebSocketTestSession(uri="ws://localhost:5876/ws/stream")
    await session.start_with_files()

async def test_microphone_websocket_stream():
    """测试使用麦克风的WebSocket流式接口 - 重构简化版本"""
    session = WebSocketTestSession(uri="ws://localhost:5876/ws/stream")
    # session = WebSocketTestSession()
    await session.start()

async def test_voice_detection_only():
    """仅测试语音检测功能，不连接WebSocket"""
    logger.info("🎤 开始语音检测测试...")
    logger.info("💡 请对着麦克风说话，程序将检测语音开始瞬间")
    logger.info("💡 按 Ctrl+C 停止测试")
    
    try:
        # 创建音频设备管理器
        audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200, bit_size=pyaudio.paInt16),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paInt16)
        )
        
        # 创建语音检测器
        vad = VoiceActivityDetector(
            sample_rate=16000,
            silence_threshold_db=-35,
            speech_threshold_db=-25,
            silence_duration_ms=300,
            speech_duration_ms=50
        )
        
        # 打开麦克风
        input_stream = audio_device.open_input_stream()
        logger.info("🎤 麦克风已打开，开始检测语音...")
        
        speech_count = 0
        frame_count = 0
        
        while True:
            try:
                # 读取音频数据
                audio_chunk = input_stream.read(
                    audio_device.input_config.chunk,
                    exception_on_overflow=False
                )
                
                frame_count += 1
                
                # 语音检测
                speech_detected = vad.detect_speech_start(audio_chunk)
                if speech_detected:
                    speech_count += 1
                    logger.info(f"🎤 第{speech_count}次检测到语音开始!")
                
                # 实时显示音量条
                volume_info = vad.get_volume_info()
                current_db = volume_info['current_db']
                vad.print_volume_bar(current_db)
                
                # 每200帧显示一次详细信息
                if frame_count % 200 == 0:
                    print()  # 换行
                    logger.info(f"📊 帧数: {frame_count}, 语音检测次数: {speech_count}")
                
            except KeyboardInterrupt:
                logger.info("用户中断测试")
                break
            except Exception as e:
                logger.error(f"语音检测测试出错: {e}")
                break
        
        # 显示统计信息
        logger.info(f"🎤 语音检测测试结束")
        logger.info(f"📊 总帧数: {frame_count}")
        logger.info(f"🎤 语音检测次数: {speech_count}")
        
        # 清理资源
        audio_device.cleanup()
        
    except Exception as e:
        logger.error(f"语音检测测试失败: {e}")
        if 'audio_device' in locals():
            audio_device.cleanup()

async def test_multiprocess_voice_detection():
    """测试多进程语音检测功能"""
    logger.info("🎤 开始多进程语音检测测试...")
    logger.info("💡 请对着麦克风说话，程序将在独立进程中检测语音")
    logger.info("💡 按 Ctrl+C 停止测试")
    
    try:
        # 创建音频设备管理器
        audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200, bit_size=pyaudio.paInt16),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paInt16)
        )
        
        # 创建音频处理器
        audio_processor = AudioProcessor(
            sample_rate=16000,
            silence_threshold_db=-35,
            speech_threshold_db=-25,
            silence_duration_ms=300,
            speech_duration_ms=50
        )
        
        # 打开麦克风
        input_stream = audio_device.open_input_stream()
        logger.info("🎤 麦克风已打开，开始多进程语音检测...")
        
        # 启动音频处理进程
        audio_processor.start()
        logger.info("🎤 音频处理进程已启动")
        
        frame_count = 0
        last_speech_end_time = 0.0
        
        while True:
            try:
                # 读取音频数据
                audio_chunk = input_stream.read(
                    audio_device.input_config.chunk,
                    exception_on_overflow=False
                )
                
                frame_count += 1
                current_timestamp = time.time()
                
                # 向音频处理进程发送音频数据
                audio_processor.put_audio_data(audio_chunk, current_timestamp)
                
                # 检查共享的语音结束时间
                shared_speech_end_time = audio_processor.get_last_speech_end_time()
                if shared_speech_end_time > last_speech_end_time:
                    last_speech_end_time = shared_speech_end_time
                    logger.info(f"🎤 检测到语音结束! 时间: {datetime.fromtimestamp(shared_speech_end_time).strftime('%H:%M:%S.%f')[:-3]}")
                
                # 获取当前说话状态
                is_speaking = audio_processor.get_is_speaking()
                
                # 实时显示状态
                status_emoji = "🎤" if is_speaking else "🔇"
                print(f"\r{status_emoji} 多进程语音检测 - 说话状态: {'是' if is_speaking else '否'} | 帧数: {frame_count}", end="", flush=True)
                
                # 每200帧显示一次详细信息
                if frame_count % 200 == 0:
                    print()  # 换行
                    logger.info(f"📊 帧数: {frame_count}, 最后语音结束时间: {last_speech_end_time:.3f}")
                
            except KeyboardInterrupt:
                logger.info("用户中断测试")
                break
            except Exception as e:
                logger.error(f"多进程语音检测测试出错: {e}")
                break
        
        # 停止音频处理进程
        audio_processor.stop()
        
        # 显示统计信息
        logger.info(f"🎤 多进程语音检测测试结束")
        logger.info(f"📊 总帧数: {frame_count}")
        logger.info(f"🎤 最后语音结束时间: {last_speech_end_time:.3f}")
        
        # 清理资源
        audio_device.cleanup()
        
    except Exception as e:
        logger.error(f"多进程语音检测测试失败: {e}")
        if 'audio_device' in locals():
            audio_device.cleanup()
        if 'audio_processor' in locals():
            audio_processor.stop()

async def test_vad_to_tts_delay():
    """测试VAD到TTS延迟监测"""
    logger.info("🎤 开始VAD到TTS延迟监测测试")
    logger.info("💡 请对着麦克风说话，程序将监测从VAD检测到语音结束到TTS开始的时间间隔")
    logger.info("💡 按 Ctrl+C 停止测试")
    
    # 创建测试会话
    session = WebSocketTestSession()
    
    try:
        # 启动音频处理器
        session.audio_processor.start()
        logger.info("🎤 音频处理器已启动")
        
        # 等待一段时间让用户说话
        logger.info("🎤 请说话测试VAD到TTS延迟监测（15秒）...")
        await asyncio.sleep(15)
        
        # 检查结果
        speech_end_time = session.get_shared_last_speech_end_time()
        is_speaking = session.get_shared_is_speaking()
        
        logger.info(f"🎤 检测结果: 说话状态={is_speaking}, 最后说话结束时间={speech_end_time}")
        
        # 显示VAD到TTS延迟统计
        if session.vad_to_tts_delays:
            avg_delay = sum(session.vad_to_tts_delays) / len(session.vad_to_tts_delays)
            min_delay = min(session.vad_to_tts_delays)
            max_delay = max(session.vad_to_tts_delays)
            logger.info(f"📊 VAD到TTS延迟统计 (共{len(session.vad_to_tts_delays)}次):")
            logger.info(f"  平均延迟: {avg_delay:.3f}秒")
            logger.info(f"  最小延迟: {min_delay:.3f}秒")
            logger.info(f"  最大延迟: {max_delay:.3f}秒")
            logger.info(f"  VAD结束次数: {session.vad_end_count}")
        else:
            logger.info("📊 未检测到VAD到TTS延迟数据")
        
    except Exception as e:
        logger.error(f"VAD到TTS延迟测试出错: {e}")
    finally:
        # 停止音频处理器
        session.audio_processor.stop()
        logger.info("🎤 音频处理器已停止")

async def test_receive_loop_only():
    """仅测试receive_loop功能"""
    logger.info("🔍 开始仅测试receive_loop功能...")
    session = WebSocketTestSession()
    
    try:
        # 添加WebSocket连接配置
        async with websockets.connect(
            session.uri,
            ping_interval=120,
            ping_timeout=60,
            close_timeout=10,
            max_size=1000000000,
            compression=None,
            max_queue=32
        ) as websocket:
            session.websocket = websocket
            logger.info("✅ 已连接到WebSocket服务器")
            
            # 执行连接握手
            if not await session.start_connection_handshake():
                logger.error("❌ 连接握手失败")
                return
            
            logger.info("🎉 握手完成，开始测试receive_loop...")
            
            # 只运行receive_loop
            try:
                await session.receive_loop()
            except Exception as e:
                logger.error(f"receive_loop执行出错: {e}")
                
    except Exception as e:
        logger.error(f"测试失败: {e}")

if __name__ == "__main__":
    import sys
    
    # 检查命令行参数选择测试模式
    mode = "mic"  # 默认麦克风模式
    if len(sys.argv) > 1:
        if sys.argv[1].lower() in ["mic", "microphone", "麦克风"]:
            mode = "microphone"
        elif sys.argv[1].lower() in ["file", "files", "文件"]:
            mode = "file"
        elif sys.argv[1].lower() in ["vad", "voice", "语音检测"]:
            mode = "voice_detection"
        elif sys.argv[1].lower() in ["mp", "multiprocess", "多进程"]:
            mode = "multiprocess"
        elif sys.argv[1].lower() in ["vad2tts", "vad-tts", "延迟"]:
            mode = "vad_to_tts"
        elif sys.argv[1].lower() in ["receive", "接收", "接收测试"]:
            mode = "receive_only"
        else:
            print("使用方法: python test_websocket_audio.py [file|mic|vad|mp|vad2tts|receive]")
            print("  file/文件: 测试预处理音频文件输入")
            print("  mic/microphone/麦克风: 测试麦克风输入 (默认)")
            print("  vad/voice/语音检测: 仅测试语音检测功能")
            print("  mp/multiprocess/多进程: 测试多进程语音检测功能")
            print("  vad2tts/vad-tts/延迟: 测试VAD到TTS延迟监测")
            print("  receive/接收测试: 仅测试receive_loop功能")
            sys.exit(1)
    
    if mode == "file":
        # 测试预处理音频文件输入
        print("=== 测试预处理音频文件输入 ===")
        print("📁 将发送 audio_test_data/ 目录下的测试音频文件")
        print("🎵 使用新的 AudioDeviceManager 播放TTS音频")
        asyncio.run(test_audio_websocket_stream())
    elif mode == "voice_detection":
        # 仅测试语音检测功能
        print("=== 语音检测测试 ===")
        print("🎤 仅测试语音检测功能，不连接WebSocket")
        print("💡 请对着麦克风说话，程序将检测语音开始瞬间")
        print("💡 按 Ctrl+C 停止测试")
        asyncio.run(test_voice_detection_only())
    elif mode == "multiprocess":
        # 测试多进程语音检测功能
        print("=== 多进程语音检测测试 ===")
        print("🎤 测试多进程语音检测功能，音频数据在独立进程中处理")
        print("💡 请对着麦克风说话，程序将检测语音结束时刻")
        print("💡 按 Ctrl+C 停止测试")
        asyncio.run(test_multiprocess_voice_detection())
    elif mode == "vad_to_tts":
        # 测试VAD到TTS延迟监测
        print("=== VAD到TTS延迟监测测试 ===")
        print("🎤 测试VAD检测到语音结束到TTS开始的时间间隔")
        print("💡 请对着麦克风说话，程序将监测延迟时间")
        print("💡 按 Ctrl+C 停止测试")
        asyncio.run(test_vad_to_tts_delay())
    elif mode == "receive_only":
        # 仅测试receive_loop功能
        print("=== 仅测试receive_loop功能 ===")
        print("🔍 仅测试WebSocket消息接收功能，不发送音频")
        print("💡 按 Ctrl+C 停止测试")
        asyncio.run(test_receive_loop_only())
    else:
        # 测试麦克风输入
        print("=== 测试麦克风输入 ===")
        print("🎤 请准备好麦克风，程序将实时录制并发送音频")
        print("🎵 使用新的 AudioDeviceManager 播放TTS音频")
        print("🎤 多进程语音检测已启用，将实时监测说话结束时刻")
        print("💡 提示: 按 Ctrl+C 停止录制")
        asyncio.run(test_microphone_websocket_stream())
