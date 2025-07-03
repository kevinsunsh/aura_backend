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

# 添加src路径以导入protocol模块
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === 二进制协议支持 ===
# 导入protocol模块和枚举
try:
    from agents.doubao_client import protocol
    from agents.configuration import ClientEventEnum, ServerEventEnum
except ImportError:
    print("⚠️ 无法导入protocol模块，将使用内置协议定义")
    # 内置协议定义作为备选
    class protocol:
        PROTOCOL_VERSION = 0b0001
        CLIENT_AUDIO_ONLY_REQUEST = 0b0010
        CLIENT_FULL_REQUEST = 0b0001
        NO_SERIALIZATION = 0b0000
        JSON = 0b0001
        GZIP = 0b0001
        NO_COMPRESSION = 0b0000
        MSG_WITH_EVENT = 0b0100
        
        @staticmethod
        def generate_header(message_type=0b0010, serial_method=0b0000):
            header = bytearray()
            header_size = 1
            header.append((0b0001 << 4) | header_size)  # version + header_size
            header.append((message_type << 4) | 0b0100)  # message_type + MSG_WITH_EVENT
            header.append((serial_method << 4) | 0b0001)  # serial_method + GZIP
            header.append(0x00)  # reserved
            return header
    
    # 内置枚举定义作为备选
    class ClientEventEnum:
        StartConnection = 1
        FinishConnection = 2
        StartSession = 100
        FinishSession = 102
    
    class ServerEventEnum:
        ConnectionStarted = 50
        ConnectionFailed = 51
        ConnectionFinished = 52
        SessionStarted = 150
        SessionFinished = 152
        SessionFailed = 153

async def send_audio_task_request(websocket, audio: bytes, session_id: str = "test_user_123") -> None:
    """发送音频数据，参考RealtimeDialogClient.task_request的简洁方式"""
    task_request = bytearray(
        protocol.generate_header(message_type=protocol.CLIENT_AUDIO_ONLY_REQUEST,
                                 serial_method=protocol.NO_SERIALIZATION))
    task_request.extend(int(200).to_bytes(4, 'big'))
    task_request.extend((len(session_id)).to_bytes(4, 'big'))
    task_request.extend(str.encode(session_id))
    payload_bytes = gzip.compress(audio)
    task_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # payload size(4 bytes)
    task_request.extend(payload_bytes)
    await websocket.send(task_request)

async def send_text_message(websocket, text: str, session_id: str = "test_user_123") -> None:
    """发送文本消息"""
    payload_data = {"message": text}
    payload_bytes = str.encode(json.dumps(payload_data))
    payload_bytes = gzip.compress(payload_bytes)
    
    request = bytearray(protocol.generate_header(
        message_type=protocol.CLIENT_FULL_REQUEST,
        serial_method=protocol.JSON
    ))
    
    request.extend(int(300).to_bytes(4, 'big'))  # 文本事件ID
    request.extend((len(session_id)).to_bytes(4, 'big'))
    request.extend(str.encode(session_id))
    request.extend((len(payload_bytes)).to_bytes(4, 'big'))
    request.extend(payload_bytes)
    await websocket.send(request)

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
        self.output_config = output_config or AudioConfig(sample_rate=24000, chunk=6400)  # 播放配置
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
                    if "PortAudio" in error_msg or "Internal PortAudio error" in error_msg:
                        logger.warning(f"PortAudio错误，跳过{stream_name}流清理: {error_msg}")
                    else:
                        logger.warning(f"关闭{stream_name}流时出错: {error_msg}")
                    
        if self.pyaudio:
            try:
                # 添加延迟确保所有流都已正确关闭
                time.sleep(0.1)
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
    """WebSocket测试会话管理类 - 重构简化版本"""
    
    def __init__(self, uri: str = "ws://localhost:5876/ws/stream/test_user_123"):
        self.uri = uri
        self.websocket = None
        
        # 音频设备管理
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=800),
            output_config=AudioConfig(sample_rate=48000, channels=1, chunk=1200, bit_size=pyaudio.paInt16)
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

        # 信号处理
        signal.signal(signal.SIGINT, self._keyboard_signal)
        
        # 文件发送模式标记
        self.file_mode = False
    
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
                        if "PortAudio" in error_msg or "Internal PortAudio error" in error_msg:
                            logger.error(f"PortAudio错误: {error_msg}")
                            try:
                                logger.info("尝试重新初始化音频输出流...")
                                if self.output_stream:
                                    if self.output_stream.is_active():
                                        self.output_stream.stop_stream()
                                    self.output_stream.close()
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
            if event_id == 450:  # ASRInfo
                logger.info("🎤 收到ASRInfo事件(450)，触发AI播报打断")
                self.asr_info_received_time = time.time()
                self._clear_audio_buffers()
                logger.info("⏸️ 播放已暂停")
            elif event_id == 451:  # ASRResponse
                self.chunk_count += 1
                content = data.get("text", "")
                self.full_response += content
                logger.info(f"收到第{self.chunk_count}个内容片段: '{content}'")
            elif event_id == 350:  # TTSSentenceStart
                logger.info("🎵 TTS语音合成开始...")
                if self.first_tts_audio_received_time is None:
                    self.first_tts_audio_received_time = time.time()
                    self.first_asr_info_received_time = self.asr_info_received_time
                if self.interrupt_audio_send_time is not None:
                    if self.second_tts_audio_received_time is None:
                        self.second_tts_audio_received_time = time.time()
                        self.second_asr_info_received_time = self.asr_info_received_time
            elif event_id == 351:  # TTSSentenceEnd
                logger.info("当前句子TTS语音合成完成")
            elif event_id == 352:  # TTSResponse
                audio_data = data["audio_data"]
                self.audio_queue.put(audio_data)
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
                        logger.info("WebSocket连接已关闭，停止接收")
                        self.response_completed = True
                        break
                    
                    # logger.info("🔍 开始接收消息")
                    # 添加短超时，让循环能定期检查退出条件
                    response_data = await asyncio.wait_for(self.websocket.recv(), timeout=0.5)
                    # logger.info("🔍 接收消息完成")
                    # 解析响应数据
                    if isinstance(response_data, bytes):
                        # 二进制协议格式
                        data = await self.parse_server_response(response_data)
                        if "error" in data:
                            logger.error(f"解析二进制协议失败: {data['error']}")
                            continue
                        logger.info(f"收到二进制协议响应: 事件ID={data.get('event', 'unknown')}")
                    else:
                        # 文本格式，尝试JSON解析
                        data = json.loads(response_data)

                    self.handle_websocket_response(data)
                    
                except asyncio.TimeoutError:
                    # 超时时检查退出条件和连接状态
                    if not self.is_running or self._is_websocket_closed():
                        break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    self.response_completed = True
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭")
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
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止接收")
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
            
            while self.is_recording and not self.response_completed:
                try:
                    # 检查退出条件和WebSocket连接状态
                    if not self.is_running or self._is_websocket_closed():
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
                    logger.info("WebSocket连接关闭，停止麦克风录制")
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.info("WebSocket连接异常关闭，停止麦克风录制")
                    break
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    # 检查是否是连接相关的错误
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["disconnect", "closed", "connection"]):
                        logger.info("检测到连接断开相关错误，停止麦克风录制")
                        break
                    await asyncio.sleep(0.1)
            
            logger.info("🔇 麦克风录制已停止")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            self.is_recording = False
    
    async def auto_stop_after_timeout(self, timeout_seconds=20):
        """自动停止录制的超时处理"""
        await asyncio.sleep(timeout_seconds)
        logger.info(f"录制时间达到{timeout_seconds}秒，自动停止...")
        self.is_recording = False
    
    async def send_control_message(self, action: str, data: dict = None):
        """发送控制消息（连接、session等）"""
        try:
            # 根据action确定客户端事件ID
            if action == "start_connection":
                event_id = 1
            elif action == "end_connection":
                event_id = 2
            elif action == "start_session":
                event_id = 100
            elif action == "end_session":
                event_id = 102
            else:
                event_id = 1001  # 默认事件ID
            
            payload_data = {"event": event_id}  # 设置事件ID
            if data:
                payload_data.update(data)
            
            # JSON序列化并压缩
            payload_bytes = str.encode(json.dumps(payload_data))
            payload_bytes = gzip.compress(payload_bytes)
            
            # 构造协议头
            request = bytearray(protocol.generate_header(
                message_type=protocol.CLIENT_FULL_REQUEST,
                message_type_specific_flags=protocol.MSG_WITH_EVENT,
                serial_method=protocol.JSON,
                compression_type=protocol.GZIP
            ))
            
            # 添加事件ID (4 bytes)
            request.extend(int(event_id).to_bytes(4, 'big'))
            
            # 添加session ID
            session_id = "test_user_123"
            session_id_bytes = str.encode(session_id)
            request.extend((len(session_id_bytes)).to_bytes(4, 'big'))
            request.extend(session_id_bytes)
            
            # 添加payload
            request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            request.extend(payload_bytes)
            
            await self.websocket.send(bytes(request))
            logger.info(f"📤 发送控制消息: {action} (事件ID: {event_id})")
            
        except Exception as e:
            logger.error(f"发送控制消息失败: {e}")
            return False
        return True

    async def parse_server_response(self, data: bytes) -> dict:
        """解析服务端二进制协议响应"""
        try:
            if len(data) < 4:
                return {"error": "消息长度不足"}
                
            # 解析协议头
            header = data[:4]
            offset = 4
            
            # 解析事件ID
            if len(data) < offset + 4:
                return {"error": "消息长度不足以包含事件ID"}
            event_id = int.from_bytes(data[offset:offset+4], 'big')
            offset += 4
            
            # 解析Session ID
            if len(data) < offset + 4:
                return {"error": "消息长度不足以包含Session ID长度"}
            session_len = int.from_bytes(data[offset:offset+4], 'big')
            offset += 4
            
            if len(data) < offset + session_len:
                return {"error": "消息长度不足以包含Session ID数据"}
            session_id = data[offset:offset+session_len].decode('utf-8')
            offset += session_len
            
            # 解析Payload
            if len(data) < offset + 4:
                return {"error": "消息长度不足以包含Payload长度"}
            payload_len = int.from_bytes(data[offset:offset+4], 'big')
            offset += 4
            
            if len(data) < offset + payload_len:
                return {"error": "消息长度不足以包含Payload数据"}
            payload_bytes = data[offset:offset+payload_len]
            
            # 解析协议头 (4字节)
            header = data[:4]
            version = (header[0] >> 4) & 0x0F
            header_size = header[0] & 0x0F
            message_type = (header[1] >> 4) & 0x0F
            flags = header[1] & 0x0F
            serial_method = (header[2] >> 4) & 0x0F
            compression = header[2] & 0x0F
            
            # logger.debug(f"协议头解析: version={version}, type={message_type}, serial={serial_method}, compression={compression}")
            
            # 根据序列化方法和压缩方式解析payload
            if serial_method == protocol.NO_SERIALIZATION:
                # 音频数据，直接使用二进制数据
                audio_data = payload_bytes
                
                return {
                    "event": event_id,
                    "session_id": session_id,
                    "audio_data": audio_data
                }
            else:
                # JSON数据
                try:
                    if compression == protocol.GZIP:
                        payload_bytes = gzip.decompress(payload_bytes)
                    payload_data = json.loads(payload_bytes.decode('utf-8'))
                    payload_data.update({
                        "event": event_id,
                        "session_id": session_id
                    })
                    return payload_data
                except Exception as e:
                    return {"error": f"解析payload失败: {e}"}
                
        except Exception as e:
            return {"error": f"解析失败: {e}"}

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
        if not await self.wait_for_server_response(50):  # ServerEventEnum.ConnectionStarted.value
            return False
        
        # 第二步：发送开始session消息
        if not await self.send_control_message("start_session", {"chat_id": "test_user_123"}):
            return False
            
        # 等待session确认
        if not await self.wait_for_server_response(150):  # ServerEventEnum.SessionStarted.value
            return False
            
        logger.info("🎉 连接和Session握手完成！")
        return True

    async def end_session_handshake(self):
        """执行结束握手流程"""
        logger.info("👋 开始结束握手流程...")
        
        # 第一步：结束session
        if await self.send_control_message("end_session"):
            await self.wait_for_server_response(152, timeout=3.0)  # ServerEventEnum.SessionFinished.value
        
        # 第二步：结束连接
        if await self.send_control_message("end_connection"):
            await self.wait_for_server_response(52, timeout=3.0)  # ServerEventEnum.ConnectionFinished.value
            
        logger.info("✅ 结束握手完成！")

    async def start(self):
        """启动WebSocket测试会话"""
        try:
            async with websockets.connect(self.uri) as websocket:
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

                # 执行结束握手
                await self.end_session_handshake()
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"连接WebSocket失败: {str(e)}")
        finally:
            # 设置停止标志
            self.is_running = False
            self.is_recording = False
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
            
            # 等待一小段时间让TTS开始播放
            await asyncio.sleep(3.0)
            
            # 第二步：发送打断音频（确保已收到第一个TTS）
            logger.info("📤 第二步：发送打断音频 (interrupt_audio)")
            if not await self._send_audio_file(test_audio_files["interrupt_audio"]):
                logger.error("发送打断音频失败")
                return
            
            # 记录打断音频发送完成时间
            self.interrupt_audio_send_time = time.time()
            logger.info(f"⏱️ 打断音频发送完成时间: {self.interrupt_audio_send_time}")
            
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
            async with websockets.connect(self.uri) as websocket:
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
            self.is_recording = False  
            self.is_playing = False
            # 清理资源
            self.audio_device.cleanup()

async def test_audio_websocket_stream():
    """测试带预处理音频文件的WebSocket流式接口"""
    session = WebSocketTestSession()
    await session.start_with_files()

async def test_microphone_websocket_stream():
    """测试使用麦克风的WebSocket流式接口 - 重构简化版本"""
    session = WebSocketTestSession()
    await session.start()

if __name__ == "__main__":
    import sys
    
    # 检查命令行参数选择测试模式
    mode = "file"  # 默认文件模式
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
