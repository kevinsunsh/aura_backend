#!/usr/bin/env python3
"""
WebSocket音频流测试 - 简洁高效版本

🎵 新版本特性:
- 使用AudioDeviceManager统一管理音频输入输出
- 简洁的线程播放实现，无复杂缓冲逻辑
- 异步麦克风处理，防止CPU过度使用
- 改进的资源管理和错误处理
- 简化的配置接口

🎤 使用示例:
# 创建设备管理器
device_manager = AudioDeviceManager(
    input_config=AudioConfig(sample_rate=16000, chunk=6400),   # 麦克风
    output_config=AudioConfig(sample_rate=24000, chunk=2048)   # 播放器
)

# 创建播放器
audio_player = StreamingAudioPlayer()
audio_player.start()

# 添加音频数据
audio_player.add_audio_data(audio_bytes)

# 使用完毕后清理
audio_player.stop()
device_manager.cleanup()

📊 关键改进:
- 直接的音频流播放，无复杂预缓冲
- exception_on_overflow=False 防止麦克风溢出错误
- 异步处理减少CPU占用
- 统一的设备资源管理
"""
import asyncio
import websockets
import json
import logging
import time
import base64
import jieba
import os
import wave
import pyaudio
import io
import queue
import threading
from pydub import AudioSegment
from statistics import mean, median
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    """音频设备管理类，处理音频输入输出"""

    def __init__(self, input_config: AudioConfig = None, output_config: AudioConfig = None):
        self.input_config = input_config or AudioConfig(sample_rate=16000, chunk=6400)  # 麦克风配置
        self.output_config = output_config or AudioConfig(sample_rate=24000, chunk=2048)  # 播放配置
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None

    def open_input_stream(self):
        """打开音频输入流"""
        if self.input_stream is not None:
            return self.input_stream
            
        self.input_stream = self.pyaudio.open(
            format=self.input_config.bit_size,
            channels=self.input_config.channels,
            rate=self.input_config.sample_rate,
            input=True,
            frames_per_buffer=self.input_config.chunk
        )
        logger.info(f"🎤 麦克风输入流已打开: {self.input_config.sample_rate}Hz, {self.input_config.channels}声道")
        return self.input_stream

    def open_output_stream(self):
        """打开音频输出流"""
        if self.output_stream is not None:
            return self.output_stream
            
        self.output_stream = self.pyaudio.open(
            format=self.output_config.bit_size,
            channels=self.output_config.channels,
            rate=self.output_config.sample_rate,
            output=True,
            frames_per_buffer=self.output_config.chunk,
            start=False  # 由播放线程控制启动
        )
        
        logger.info(f"🔊 音频输出流已创建: {self.output_config.sample_rate}Hz, {self.output_config.channels}声道")
        return self.output_stream
        
    def cleanup(self):
        """清理音频设备资源"""
        logger.info("🧹 清理音频设备资源...")
        
        for stream_name, stream in [("输入", self.input_stream), ("输出", self.output_stream)]:
            if stream:
                try:
                    if stream.is_active():
                        stream.stop_stream()
                    stream.close()
                    logger.debug(f"✅ {stream_name}流已关闭")
                except Exception as e:
                    logger.warning(f"关闭{stream_name}流时出错: {e}")
                    
        if self.pyaudio:
            try:
                self.pyaudio.terminate()
                logger.debug("✅ PyAudio已终止")
            except Exception as e:
                logger.warning(f"终止PyAudio时出错: {e}")
        
        # 重置状态
        self.input_stream = None
        self.output_stream = None

class StreamingAudioPlayer:
    """
    流式音频播放器，支持实时播放音频片段
    基于AudioDeviceManager的现代化实现
    """
    
    def __init__(self, sample_rate=24000, channels=1, sample_width=2):
        # 创建输出配置
        output_config = AudioConfig(
            sample_rate=sample_rate,
            channels=channels,
            bit_size=pyaudio.paInt16 if sample_width == 2 else pyaudio.paInt32,
            chunk=2048
        )
        
        # 创建设备管理器
        self.device_manager = AudioDeviceManager(output_config=output_config)
        self.audio_queue = queue.Queue()
        self.is_playing = False
        self.play_thread = None
        
        # 音频文件录制
        self.is_recording = False
        self.audio_buffer = bytearray()
        self.output_file = None
        
        # 状态管理
        self.total_samples_played = 0
        
    def start(self):
        """启动音频播放"""
        if self.is_playing:
            return
            
        self.is_playing = True
        
        try:
            # 打开输出流
            self.device_manager.open_output_stream()
            
            # 启动播放线程
            self.play_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
            self.play_thread.start()
            
            logger.info("🎵 音频播放器已启动")
            
        except Exception as e:
            logger.error(f"启动音频播放器失败: {e}")
            self.is_playing = False
            raise
        
    def add_audio_data(self, audio_data: bytes):
        """添加音频数据到播放队列和录制缓冲区"""
        if self.is_playing:
            self.audio_queue.put(audio_data)
            
        if self.is_recording:
            self.audio_buffer.extend(audio_data)
        
    def _audio_player_thread(self):
        """音频播放线程"""
        logger.info("🎵 播放线程已启动，等待音频数据...")
        
        # 启动输出流
        output_stream = self.device_manager.output_stream
        if output_stream:
            output_stream.start_stream()
            logger.info("🔊 音频输出流已启动")
        
        while self.is_playing:
            try:
                # 从队列获取音频数据
                audio_data = self.audio_queue.get(timeout=1.0)
                if audio_data is not None and output_stream:
                    output_stream.write(audio_data)
                    self.total_samples_played += len(audio_data) // (
                        self.device_manager.output_config.channels * 
                        self.device_manager.output_config.sample_width
                    )
            except queue.Empty:
                # 队列为空时等待一小段时间
                import time
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"音频播放错误: {e}")
                import time
                time.sleep(0.1)
                
        logger.info("🔇 播放线程结束")
        
    def stop(self):
        """停止音频播放"""
        logger.info("🛑 正在停止音频播放器...")
        self.is_playing = False
        
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=3.0)
            
        # 停止录制
        self.stop_recording()
        
        # 清理设备资源
        self.device_manager.cleanup()
        
        total_time = self.total_samples_played / self.device_manager.output_config.sample_rate if self.device_manager.output_config.sample_rate > 0 else 0
        logger.info(f"🔇 音频播放器已停止 (播放时长: {total_time:.2f}秒)")
        
    def start_recording(self, filename=None):
        """开始录制音频到文件"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"websocket_tts_output_{timestamp}.mp3"
        
        os.makedirs("audio_output", exist_ok=True)
        self.output_file = os.path.join("audio_output", filename)
        self.audio_buffer.clear()
        self.is_recording = True
        logger.info(f"🎵 开始录制TTS音频到: {self.output_file}")
        
    def stop_recording(self):
        """停止录制并保存文件"""
        if not self.is_recording:
            return None
            
        self.is_recording = False
        
        if self.audio_buffer and self.output_file:
            with open(self.output_file, 'wb') as f:
                f.write(self.audio_buffer)
            
            file_size = len(self.audio_buffer)
            logger.info(f"💾 TTS音频文件已保存: {self.output_file} ({file_size} 字节)")
            
            # 尝试播放保存的文件
            try:
                import subprocess
                if os.name == 'posix':  # macOS/Linux
                    subprocess.run(['afplay', self.output_file], check=False)
                    logger.info("🔊 正在播放保存的TTS音频文件...")
                elif os.name == 'nt':  # Windows
                    os.system(f'start "" "{self.output_file}"')
                    logger.info("🔊 正在播放保存的TTS音频文件...")
            except Exception as e:
                logger.warning(f"无法播放保存的文件: {e}")
            
            return self.output_file
        else:
            logger.warning("没有录制到TTS音频数据")
            return None
        
    def get_status(self):
        """获取当前播放器状态"""
        return {
            "is_playing": self.is_playing,
            "is_recording": self.is_recording,
            "total_samples_played": self.total_samples_played,
            "sample_rate": self.device_manager.output_config.sample_rate,
            "channels": self.device_manager.output_config.channels
        }

async def test_audio_websocket_stream():
    """测试带预处理音频文件的WebSocket流式接口"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 响应处理状态
    response_completed = False
    full_response = ""
    chunk_count = 0
    
    # 延迟统计变量
    audio_send_completed_time = None
    first_tts_audio_received_time = None
    audio_to_tts_delay = None
    
    # 创建流式音频播放器
    audio_player = StreamingAudioPlayer()
    
    def play_audio_data(audio_data: bytes):
        """播放TTS音频数据片段"""
        try:
            logger.info(f"🔊 收到TTS音频片段: {len(audio_data)} 字节")
            # 直接添加到播放器队列，支持流式播放
            audio_player.add_audio_data(audio_data)
            
        except Exception as e:
            logger.error(f"处理TTS音频片段失败: {str(e)}")
    
    def read_audio_file(file_path):
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
    
    def generate_silence_audio(duration_ms=500):
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
    
    async def receive_messages(websocket):
        """异步接收消息的任务"""
        nonlocal response_completed, full_response, chunk_count
        nonlocal audio_send_completed_time, first_tts_audio_received_time, audio_to_tts_delay
        
        try:
            while not response_completed:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    logger.info(f"收到响应: {data['type']}")
                    
                    if data["type"] == "start":
                        logger.info("开始处理音频文件消息...")
                    elif data["type"] == "stream_chunk":
                        chunk_count += 1
                        content = data["content"]
                        full_response += content
                        logger.info(f"收到第{chunk_count}个内容片段: '{content}'")
                        print(content, end="", flush=True)
                    elif data["type"] == "tts_start":
                        logger.info("TTS语音合成开始...")
                        # 启动音频播放器和录制
                        audio_player.start()
                        audio_player.start_recording()
                        # 显示播放器状态
                        status = audio_player.get_status()
                        logger.info(f"🎵 播放器状态: {status}")
                    elif data["type"] == "tts_audio":
                        # 记录第一个TTS音频收到的时间
                        if first_tts_audio_received_time is None:
                            first_tts_audio_received_time = time.time()
                            if audio_send_completed_time is not None:
                                audio_to_tts_delay = first_tts_audio_received_time - audio_send_completed_time
                                logger.info(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {audio_to_tts_delay:.3f}秒")
                        
                        # 处理TTS音频数据 - 关键修改
                        audio_data = base64.b64decode(data["audio_data"])
                        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
                        
                        # 直接播放音频片段（流式播放）
                        play_audio_data(audio_data)
                    elif data["type"] == "tts_end":
                        logger.info("TTS语音合成完成")
                        # 显示最终播放器状态
                        status = audio_player.get_status()
                        logger.info(f"🎵 TTS完成时播放器状态: {status}")
                        # 等待一会儿确保音频播放完成
                        await asyncio.sleep(2)
                        # 停止音频播放器
                        audio_player.stop()
                    elif data["type"] == "end":
                        logger.info("音频文件处理完成")
                        response_completed = True
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        response_completed = True
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    response_completed = True
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    response_completed = True
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            response_completed = True
    
    async def send_audio_files(websocket):
        """异步发送测试音频文件数据的任务"""
        nonlocal audio_send_completed_time
        
        try:
            # 测试音频文件列表
            test_audio_files = [
                "audio_test_data/converted_20250630_151526_你好.wav",
                "audio_test_data/converted_20250630_151540_我想了解一下.wav", 
                "audio_test_data/converted_20250630_151545_你的功能.wav",
                "audio_test_data/converted_20250630_151551_和特点.wav"
            ]
            
            for audio_file in test_audio_files:
                logger.info(f"正在发送测试音频文件: {audio_file}")
                
                # 读取音频文件数据
                audio_data = read_audio_file(audio_file)
                if audio_data is None:
                    logger.error(f"无法读取音频文件: {audio_file}")
                    continue
                
                # 模拟实时发送，将音频数据分片发送
                # 200ms音频块大小：16kHz × 1声道 × 2字节 × 0.2秒 = 6400字节
                CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
                total_chunks = len(audio_data) // CHUNK_SIZE + (1 if len(audio_data) % CHUNK_SIZE else 0)
                
                logger.info(f"开始分片发送音频数据，总共 {total_chunks} 个片段")
                
                for i in range(0, len(audio_data), CHUNK_SIZE):
                    chunk = audio_data[i:i + CHUNK_SIZE]
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await websocket.send(json.dumps(audio_message))
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.1)  # 200ms间隔，匹配音频块时长
                
                logger.info(f"音频文件 {audio_file} 发送完成")
                
                # 在音频文件之间添加停顿
                await asyncio.sleep(2)
            
            logger.info("所有测试音频文件发送完成")
            
            # 发送2秒的静音数据
            logger.info("正在发送2秒静音数据...")
            silence_data = generate_silence_audio(duration_ms=2000)  # 2秒静音
            if silence_data:
                # 模拟实时发送，将静音数据分片发送
                CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
                
                for i in range(0, len(silence_data), CHUNK_SIZE):
                    chunk = silence_data[i:i + CHUNK_SIZE]
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await websocket.send(json.dumps(audio_message))
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.2)  # 200ms间隔，匹配音频块时长
                
                logger.info("2秒静音数据发送完成")
            else:
                logger.error("生成静音数据失败")
            
            # 记录音频发送完成时间
            audio_send_completed_time = time.time()
            logger.info(f"📤 所有音频数据发送完成，时间戳: {audio_send_completed_time}")
                    
        except Exception as e:
            logger.error(f"发送音频文件失败: {str(e)}")
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            
            # 启动接收消息的异步任务
            receive_task = asyncio.create_task(receive_messages(websocket))
            
            # 启动发送预处理音频文件的异步任务
            send_task = asyncio.create_task(send_audio_files(websocket))
            
            # 等待两个任务都完成
            await asyncio.gather(receive_task, send_task)
            
            print(f"\n=== 音频文件测试完成，总共收到 {chunk_count} 个内容片段 ===")
            logger.info(f"完整响应: {full_response}")
            
            # 输出延迟统计结果
            if audio_to_tts_delay is not None:
                print(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {audio_to_tts_delay:.3f}秒")
                logger.info(f"延迟统计 - 音频发送完成时间: {audio_send_completed_time}, 首个TTS音频收到时间: {first_tts_audio_received_time}")
            else:
                print("⚠️ 未能完整统计音频到TTS的延迟")
            
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")
    finally:
        # 确保音频播放器已停止
        audio_player.stop()

async def test_microphone_websocket_stream():
    """测试使用麦克风的WebSocket流式接口"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 响应处理状态
    response_completed = False
    full_response = ""
    chunk_count = 0
    recording_active = True
    
    # 延迟统计变量
    audio_send_completed_time = None
    first_tts_audio_received_time = None
    audio_to_tts_delay = None
    
    # 麦克风录音参数 - 现在使用AudioDeviceManager
    input_config = AudioConfig(sample_rate=16000, channels=1, chunk=6400)
    device_manager = AudioDeviceManager(input_config=input_config)
    
    # 创建流式音频播放器
    audio_player = StreamingAudioPlayer()
    
    def play_audio_data(audio_data: bytes):
        """播放TTS音频数据片段"""
        try:
            logger.info(f"🔊 收到TTS音频片段: {len(audio_data)} 字节")
            # 直接添加到播放器队列，支持流式播放
            audio_player.add_audio_data(audio_data)
            
        except Exception as e:
            logger.error(f"处理TTS音频片段失败: {str(e)}")
    
    async def receive_messages(websocket):
        """异步接收消息的任务"""
        nonlocal response_completed, full_response, chunk_count
        nonlocal audio_send_completed_time, first_tts_audio_received_time, audio_to_tts_delay
        
        try:
            while not response_completed:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    logger.info(f"收到响应: {data}")
                    
                    if data["type"] == "start":
                        logger.info("开始处理麦克风音频消息...")
                    elif data["type"] == "stream_chunk":
                        chunk_count += 1
                        content = data["content"]
                        full_response += content
                        logger.info(f"收到第{chunk_count}个内容片段: '{content}'")
                        print(content, end="", flush=True)
                    elif data["type"] == "tts_start":
                        logger.info("TTS语音合成开始...")
                        # 启动音频播放器和录制
                        audio_player.start()
                        audio_player.start_recording()
                    elif data["type"] == "tts_audio":
                        # 记录第一个TTS音频收到的时间
                        if first_tts_audio_received_time is None:
                            first_tts_audio_received_time = time.time()
                            if audio_send_completed_time is not None:
                                audio_to_tts_delay = first_tts_audio_received_time - audio_send_completed_time
                                logger.info(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {audio_to_tts_delay:.3f}秒")
                        
                        # 处理TTS音频数据 - 关键修改
                        audio_data = base64.b64decode(data["audio_data"])
                        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
                        
                        # 直接播放音频片段（流式播放）
                        play_audio_data(audio_data)
                    elif data["type"] == "tts_end":
                        logger.info("TTS语音合成完成")
                        # 显示最终播放器状态
                        status = audio_player.get_status()
                        logger.info(f"🎵 TTS完成时播放器状态: {status}")
                        # 等待一会儿确保音频播放完成
                        await asyncio.sleep(2)
                        # 停止音频播放器
                        audio_player.stop()
                    elif data["type"] == "end":
                        logger.info("麦克风音频处理完成")
                        response_completed = True
                        break
                    elif data["type"] == "error":
                        logger.error(f"发生错误: {data['message']}")
                        response_completed = True
                        break
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    response_completed = True
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    response_completed = True
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            response_completed = True
    
    async def record_and_send_audio(websocket):
        """异步录制麦克风音频并发送的任务"""
        nonlocal recording_active
        
        try:
            # 打开麦克风输入流
            input_stream = device_manager.open_input_stream()
            logger.info("🎤 已打开麦克风，请讲话...")
            
            while recording_active and not response_completed:
                try:
                    # 添加exception_on_overflow=False参数来忽略溢出错误
                    audio_chunk = input_stream.read(
                        input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(audio_chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await websocket.send(json.dumps(audio_message))
                    
                    # 避免CPU过度使用
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    await asyncio.sleep(0.1)  # 给系统一些恢复时间
            
            logger.info("🔇 麦克风录制已停止")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            recording_active = False
    
    async def handle_user_input():
        """处理用户输入，用于控制录制"""
        nonlocal recording_active, response_completed
        nonlocal audio_send_completed_time
        
        try:
            # 等待用户按键停止录制
            await asyncio.sleep(1)  # 给其他任务启动的时间
            
            # 这里可以添加更复杂的用户交互逻辑
            # 目前简单地录制20秒后自动停止
            await asyncio.sleep(300)  # 录制20秒
            
            logger.info("录制时间达到20秒，自动停止...")
            recording_active = False
            
            # 记录音频发送完成时间
            audio_send_completed_time = time.time()
            logger.info(f"📤 麦克风音频录制完成，时间戳: {audio_send_completed_time}")
            
        except Exception as e:
            logger.error(f"用户输入处理异常: {str(e)}")
            recording_active = False
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("已连接到WebSocket服务器")
            logger.info("=== 开始麦克风音频测试 ===")
            
            # 启动接收消息的异步任务
            receive_task = asyncio.create_task(receive_messages(websocket))
            
            # 启动录制和发送麦克风音频的异步任务
            record_task = asyncio.create_task(record_and_send_audio(websocket))
            
            # 启动用户输入处理任务
            input_task = asyncio.create_task(handle_user_input())
            
            # 等待任务完成
            await asyncio.gather(receive_task, record_task, input_task, return_exceptions=True)
            
            print(f"\n=== 麦克风音频测试完成，总共收到 {chunk_count} 个内容片段 ===")
            logger.info(f"完整响应: {full_response}")
            
            # 输出延迟统计结果
            if audio_to_tts_delay is not None:
                print(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {audio_to_tts_delay:.3f}秒")
                logger.info(f"延迟统计 - 音频发送完成时间: {audio_send_completed_time}, 首个TTS音频收到时间: {first_tts_audio_received_time}")
            else:
                print("⚠️ 未能完整统计音频到TTS的延迟")
            
    except KeyboardInterrupt:
        logger.info("用户中断测试")
        recording_active = False
        response_completed = True
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")
    finally:
        # 清理PyAudio资源
        device_manager.cleanup()
        # 确保音频播放器已停止
        audio_player.stop()

if __name__ == "__main__":
    # 测试预处理音频文件输入
    # print("=== 测试预处理音频文件输入 ===")
    # asyncio.run(test_audio_websocket_stream())
    
    # 测试麦克风输入
    print("=== 测试麦克风输入 ===")
    asyncio.run(test_microphone_websocket_stream())
