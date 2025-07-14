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

async def send_audio_task_request(websocket, audio: bytes, session_id: str = "test_user_123") -> None:
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

    def __init__(self, input_config: AudioConfig = None, output_config: AudioConfig = None):
        self.input_config = input_config or AudioConfig(sample_rate=16000, chunk=6400)  # 麦克风配置
        self.output_config = output_config or AudioConfig(sample_rate=24000, chunk=6400, bit_size=pyaudio.paInt32)  # 播放配置
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



class WebSocketTestSession:
    """WebSocket测试会话管理类 - 裸Opus流解码版本"""
    
    def __init__(self, uri: str = "ws://sd1jn2gk3k341ncbl2d5g.apigateway-cn-shanghai.volceapi.com/ws/stream"):
        self.uri = uri
        self.websocket = None
        # 音频设备管理 - 匹配服务器Float32 PCM格式
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=800),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paFloat32)
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
                self.asr_ended_time = time.time()
                logger.debug(f"⏱️ ASREnded时间戳: {self.asr_ended_time}")
            elif event_id == 350:  # TTSSentenceStart
                logger.info("🎵 TTS语音合成开始...")
                # 记录TTSSentenceStart时间戳
                self.tts_sentence_start_time = time.time()
                # logger.info(f"⏱️ TTSSentenceStart时间戳: {self.tts_sentence_start_time}")
                
                # 计算ASREnded到TTSSentenceStart的延迟（只计算第一个TTSSentenceStart）
                if self.asr_ended_time is not None:
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
                        logger.info(f"📊 延迟统计 (共{len(self.asr_to_tts_delays)}次): 平均={avg_delay:.3f}s, 最小={min_delay:.3f}s, 最大={max_delay:.3f}s")
                
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
        """接收消息循环"""
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
                    
                    # logger.info("🔍 开始接收消息")
                    # 添加短超时，让循环能定期检查退出条件
                    response_data = await asyncio.wait_for(self.websocket.recv(), timeout=0.5)
                    data = client_parse_response(response_data)
                    self.handle_websocket_response(data)
                    
                except asyncio.TimeoutError:
                    # 超时时检查退出条件和连接状态
                    if not self.is_running or self._is_websocket_closed():
                        break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭，尝试重连...")
                    if await self._reconnect_websocket():
                        logger.info("重连成功，继续接收消息")
                        continue
                    else:
                        logger.error("重连失败，停止接收")
                        self.response_completed = True
                        break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭，尝试重连...")
                    if await self._reconnect_websocket():
                        logger.info("重连成功，继续接收消息")
                        continue
                    else:
                        logger.error("重连失败，停止接收")
                        self.response_completed = True
                        break
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("WebSocket连接正常关闭")
                    self.response_completed = True
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection", "ping", "timeout"]):
                        logger.info("检测到连接断开相关错误，尝试重连...")
                        if await self._reconnect_websocket():
                            logger.info("重连成功，继续接收消息")
                            continue
                        else:
                            logger.error("重连失败，停止接收")
                            self.response_completed = True
                            break
                    # 其他错误则继续尝试
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            self.response_completed = True
    
    async def microphone_input_loop(self):
        """麦克风输入循环，纯音频录制和发送（打断由450事件控制）"""
        try:
            input_stream = self.audio_device.open_input_stream()
            logger.info("🎤 已打开麦克风，开始录制音频流...")
            
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
                    
                    # 🔥 使用简洁的task_request方式发送音频数据
                    await send_audio_task_request(self.websocket, audio_chunk, "test_user_123")
                    logger.debug(f"📤 发送音频块: {len(audio_chunk)} 字节")
                    
                    await asyncio.sleep(0.001)  # 1ms极低延迟
                    
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
            
            logger.info("🔇 麦克风录制已停止")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            pass
    
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
                session_id = "test_user_123"
                payload_data = {
                    "chat_info": {
                        "chat_id": "test_user_123",
                        "user_id": "test_user_123"
                    }
                }
                event_id = 100
            elif action == "end_session":
                session_id = "test_user_123"
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
    
    async def wait_for_server_response(self, expected_event_id: int, timeout: float = 5.0):
        """等待服务端特定响应 - 使用事件等待机制避免并发recv冲突"""
        try:
            # 创建一个事件来等待特定响应
            response_event = asyncio.Event()
            response_data = None
            
            # 临时保存原始的处理函数
            original_handler = self.handle_websocket_response
            
            def temp_handler(data: dict):
                """临时处理函数，检查是否是期望的响应"""
                nonlocal response_data, response_event
                if "event" in data and data["event"] == expected_event_id:
                    response_data = data
                    response_event.set()
                else:
                    # 调用原始处理函数处理其他消息
                    original_handler(data)
            
            # 替换处理函数
            self.handle_websocket_response = temp_handler
            
            try:
                # 等待响应事件
                await asyncio.wait_for(response_event.wait(), timeout=timeout)
                
                event_id = response_data.get("event", "unknown")
                logger.info(f"📥 收到服务端响应: 事件ID={event_id}")
                
                status = response_data.get("status", "unknown")
                message = response_data.get("message", "")
                logger.info(f"✅ 事件{expected_event_id} 成功: {status} - {message}")
                return True
                
            finally:
                # 恢复原始处理函数
                self.handle_websocket_response = original_handler
                
        except asyncio.TimeoutError:
            logger.error(f"❌ 等待事件ID {expected_event_id} 响应超时")
            return False
        except Exception as e:
            logger.error(f"❌ 等待服务端响应时出错: {e}")
            return False

    async def start_connection_handshake(self):
        """执行连接握手流程"""
        logger.info("🤝 开始连接握手流程...")
        
        # 第一步：发送开始连接消息
        if not await self.send_control_message("start_connection"):
            return False
            
        # 等待连接确认
        if not await self.wait_for_server_response(ServerEvent.ConnectionStarted):
            return False
        
        # 第二步：发送开始session消息
        if not await self.send_control_message("start_session"):
            return False
            
        # 等待session确认
        if not await self.wait_for_server_response(ServerEvent.SessionStarted):
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
                    await self.wait_for_server_response(ServerEvent.SessionFinished, timeout=3.0)
                else:
                    logger.warning("⚠️ 发送end_session消息失败")
            except Exception as e:
                logger.warning(f"⚠️ 结束session时出错: {e}")
            
            # 第二步：结束连接
            try:
                if await self.send_control_message("end_connection"):
                    await self.wait_for_server_response(ServerEvent.ConnectionFinished, timeout=3.0)
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
                ping_interval=30,      # 每30秒发送一次ping（更保守）
                ping_timeout=15,       # ping超时时间15秒（更宽松）
                close_timeout=10,      # 关闭超时时间10秒
                max_size=1000000000,   # 最大消息大小1GB
                compression=None,      # 禁用压缩避免问题
                max_queue=32
            ) as websocket:
                self.websocket = websocket
                logger.info("已连接到WebSocket服务器")
                logger.info("=== 开始麦克风音频测试 ===")
                
                # 先启动接收消息的任务，确保握手消息能被处理
                receive_task = asyncio.create_task(self.receive_loop())
                
                # 等待一小段时间确保receive_loop已启动
                await asyncio.sleep(0.1)
                
                # 执行连接和session握手
                if not await self.start_connection_handshake():
                    logger.error("❌ 连接握手失败，退出测试")
                    receive_task.cancel()
                    return
                
                # 初始化异步打断队列
                self.interrupt_queue = asyncio.Queue(maxsize=10)
                logger.info("🎛️ 异步打断控制系统已初始化")
                
                # 在会话开始时就初始化TTS播放器，准备接收音频
                self.initialize_tts_player()
                logger.info("🎵 TTS播放器已预先初始化，准备接收多轮对话...")
                
                # 创建其他异步任务
                microphone_task = asyncio.create_task(self.microphone_input_loop())
                interrupt_task = asyncio.create_task(self.interrupt_handler())
                # timeout_task = asyncio.create_task(self.auto_stop_after_timeout(20))
                
                # 等待任务完成或者程序停止
                tasks = [receive_task, microphone_task, interrupt_task]
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
            
            # 发送1秒静音（使用缓存的静音音频）
            await self._send_silence_audio()

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
                    await send_audio_task_request(self.websocket, chunk, "test_user_123")
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
                    await send_audio_task_request(self.websocket, chunk, "test_user_123")
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

if __name__ == "__main__":
    import sys
    
    # 检查命令行参数选择测试模式
    mode = "mic"  # 默认文件模式
    if len(sys.argv) > 1:
        if sys.argv[1].lower() in ["mic", "microphone", "麦克风"]:
            mode = "microphone"
        elif sys.argv[1].lower() in ["file", "files", "文件"]:
            mode = "file"
        else:
            print("使用方法: python test_websocket_audio.py [file|mic]")
            print("  file/文件: 测试预处理音频文件输入 (默认)")
            print("  mic/microphone/麦克风: 测试麦克风输入")
            sys.exit(1)
    
    if mode == "file":
        # 测试预处理音频文件输入
        print("=== 测试预处理音频文件输入 ===")
        print("📁 将发送 audio_test_data/ 目录下的测试音频文件")
        print("🎵 使用新的 AudioDeviceManager 播放TTS音频")
        asyncio.run(test_audio_websocket_stream())
    else:
        # 测试麦克风输入
        print("=== 测试麦克风输入 ===")
        print("🎤 请准备好麦克风，程序将实时录制并发送音频")
        print("🎵 使用新的 AudioDeviceManager 播放TTS音频")
        print("💡 提示: 按 Ctrl+C 停止录制")
        asyncio.run(test_microphone_websocket_stream())
