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
import signal
from pydub import AudioSegment
from statistics import mean, median
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 启用调试模式以便查看详细的MP3处理信息
DEBUG_MP3_PROCESSING = True
if DEBUG_MP3_PROCESSING:
    logger.setLevel(logging.DEBUG)

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
        self.output_config = output_config or AudioConfig(sample_rate=24000, chunk=6400)  # 播放配置
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

class WebSocketTestSession:
    """WebSocket测试会话管理类，参考audio_manager.py的设计"""
    
    def __init__(self, uri: str = "ws://localhost:5876/ws/stream/test_user_123"):
        self.uri = uri
        self.websocket = None
        
        # 音频设备管理
        self.audio_device = AudioDeviceManager(
            input_config=AudioConfig(sample_rate=16000, channels=1, chunk=3200),
            output_config=AudioConfig(sample_rate=24000, channels=1, chunk=3200, bit_size=pyaudio.paFloat32)
        )
        
        # 状态控制
        self.is_running = True
        self.is_recording = True
        self.is_playing = True
        self.response_completed = False
        
        # 音频播放队列和线程 - 一开始就初始化
        self.audio_queue = queue.Queue()
        self.output_stream = None
        self.player_thread = None
        self.tts_initialized = False  # 标记TTS播放是否已初始化
        
        # MP3数据缓冲 - 新增
        self.mp3_buffer = bytearray()
        self.mp3_buffer_lock = threading.Lock()
        self.min_mp3_buffer_size = 1024  # 最小缓冲区大小
        
        # 响应统计
        self.full_response = ""
        self.chunk_count = 0
        
        # 延迟统计
        self.audio_send_completed_time = None
        self.first_tts_audio_received_time = None
        
        # 音频录制 - 录制原始MP3数据
        self.is_recording_audio = False
        self.mp3_audio_buffer = bytearray()  # 存储原始MP3数据
        self.output_file = None
        
        # 信号处理
        signal.signal(signal.SIGINT, self._keyboard_signal)
        
        # 文件发送模式标记
        self.file_mode = False
    
    def _keyboard_signal(self, sig, frame):
        """处理键盘中断信号"""
        logger.info("收到 Ctrl+C 信号，正在停止...")
        self.is_recording = False
        self.is_playing = False
        self.is_running = False
        self.response_completed = True
    
    def _audio_player_thread(self):
        """音频播放线程，参考audio_manager.py的实现"""
        logger.info("🎵 播放线程已启动，等待音频数据...")
        
        while self.is_playing:
            try:
                # 从队列获取PCM音频数据
                pcm_data = self.audio_queue.get(timeout=1.0)
                if pcm_data is not None and self.output_stream:
                    self.output_stream.write(pcm_data)
                    
            except queue.Empty:
                # 队列为空时等待一小段时间
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"音频播放错误: {e}")
                time.sleep(0.1)
                
        logger.info("🔇 播放线程结束")
    
    def start_audio_recording(self, filename=None):
        """开始录制TTS音频（MP3格式）"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"websocket_tts_output_{timestamp}.mp3"
        
        os.makedirs("audio_output", exist_ok=True)
        self.output_file = os.path.join("audio_output", filename)
        self.mp3_audio_buffer.clear()
        self.is_recording_audio = True
        logger.info(f"🎵 开始录制TTS音频到: {self.output_file} (MP3格式)")
    
    def stop_audio_recording(self):
        """停止录制并保存MP3文件"""
        if not self.is_recording_audio:
            return None
            
        self.is_recording_audio = False
        
        if self.mp3_audio_buffer and self.output_file:
            with open(self.output_file, 'wb') as f:
                f.write(self.mp3_audio_buffer)
            
            file_size = len(self.mp3_audio_buffer)
            logger.info(f"💾 TTS音频文件已保存: {self.output_file} ({file_size} 字节, MP3格式)")
            return self.output_file
        else:
            logger.warning("没有录制到TTS音频数据")
            return None
    
    def process_mp3_audio_data(self, mp3_data: bytes) -> bytes:
        """处理MP3格式的TTS音频数据，转换为播放器需要的格式"""
        try:
            # 检查MP3数据是否为空
            if not mp3_data or len(mp3_data) < 10:
                logger.warning(f"接收到的MP3数据太小: {len(mp3_data)} 字节，跳过")
                return b""
            
            # 简单检查是否包含MP3头（以确保数据格式正确）
            if not self._is_valid_mp3_data(mp3_data):
                logger.warning("接收到的数据不是有效的MP3格式，跳过此片段")
                return b""
            
            # 使用pydub从内存中加载MP3数据
            audio_segment = AudioSegment.from_file(io.BytesIO(mp3_data), format="mp3")
            
            # 获取输出配置
            output_config = self.audio_device.output_config
            
            # 转换为目标格式
            if output_config.bit_size == pyaudio.paFloat32:
                # 转换为float32格式 (32位浮点)
                target_audio = audio_segment.set_frame_rate(output_config.sample_rate).set_channels(output_config.channels)
                # 导出为float32 PCM
                buffer = io.BytesIO()
                target_audio.export(buffer, format="f32le")  # 32位浮点，小端序
                pcm_data = buffer.getvalue()
            else:
                # 转换为int16格式 (16位整型)
                target_audio = audio_segment.set_frame_rate(output_config.sample_rate).set_channels(output_config.channels).set_sample_width(2)
                # 导出为int16 PCM
                buffer = io.BytesIO()
                target_audio.export(buffer, format="s16le")  # 16位有符号整型，小端序
                pcm_data = buffer.getvalue()
            
            logger.debug(f"MP3音频转换完成: {len(mp3_data)} 字节 MP3 → {len(pcm_data)} 字节 PCM")
            return pcm_data
            
        except Exception as e:
            logger.error(f"处理MP3音频数据失败: {e}")
            # 记录错误详情以便调试
            logger.debug(f"MP3数据长度: {len(mp3_data)}")
            if len(mp3_data) > 0:
                logger.debug(f"MP3数据前16字节: {mp3_data[:16].hex() if len(mp3_data) >= 16 else mp3_data.hex()}")
            
            # 备用方案：尝试直接保存原始MP3数据以便后续分析
            if DEBUG_MP3_PROCESSING and len(mp3_data) > 0:
                try:
                    timestamp = int(time.time() * 1000)
                    debug_file = f"debug_mp3_{timestamp}.mp3"
                    os.makedirs("debug_output", exist_ok=True)
                    with open(f"debug_output/{debug_file}", "wb") as f:
                        f.write(mp3_data)
                    logger.debug(f"已保存问题MP3数据到: debug_output/{debug_file}")
                except Exception as debug_e:
                    logger.debug(f"保存调试MP3文件失败: {debug_e}")
            
            return b""  # 返回空数据避免播放中断
    
    def _is_valid_mp3_data(self, data: bytes) -> bool:
        """检查数据是否包含有效的MP3头"""
        try:
            if len(data) < 4:
                return False
            
            # 查找MP3帧同步字节 (0xFF, 0xFB 或类似的MP3帧头)
            for i in range(len(data) - 1):
                if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                    return True
            
            # 也检查ID3标签 (以"ID3"开头)
            if data.startswith(b'ID3'):
                return True
                
            return False
        except Exception:
            return False
    
    def process_mp3_stream_data(self, mp3_data: bytes):
        """处理流式MP3数据，使用缓冲机制"""
        with self.mp3_buffer_lock:
            # 添加新数据到缓冲区
            self.mp3_buffer.extend(mp3_data)
            
            # 尝试处理缓冲区中的完整MP3片段
            while len(self.mp3_buffer) >= self.min_mp3_buffer_size:
                # 尝试处理当前缓冲区的数据
                success = self._try_process_buffered_mp3()
                if not success:
                    # 如果处理失败，等待更多数据
                    break
    
    def _try_process_buffered_mp3(self) -> bool:
        """尝试处理缓冲区中的MP3数据"""
        try:
            # 方法1: 尝试处理整个缓冲区
            pcm_data = self.process_mp3_audio_data(bytes(self.mp3_buffer))
            if pcm_data:
                self.audio_queue.put(pcm_data)
                self.mp3_buffer.clear()
                logger.debug(f"成功处理完整缓冲区: {len(self.mp3_buffer)} 字节")
                return True
            
            # 方法2: 如果整个缓冲区失败，尝试处理前半部分
            if len(self.mp3_buffer) > self.min_mp3_buffer_size * 2:
                half_size = len(self.mp3_buffer) // 2
                pcm_data = self.process_mp3_audio_data(bytes(self.mp3_buffer[:half_size]))
                if pcm_data:
                    self.audio_queue.put(pcm_data)
                    # 移除已处理的数据
                    self.mp3_buffer = self.mp3_buffer[half_size:]
                    logger.debug(f"成功处理部分缓冲区: {half_size} 字节")
                    return True
            
            # 方法3: 如果缓冲区太大，强制清理一部分
            if len(self.mp3_buffer) > 10240:  # 10KB
                logger.warning(f"MP3缓冲区过大 ({len(self.mp3_buffer)} 字节)，清理前1KB数据")
                self.mp3_buffer = self.mp3_buffer[1024:]
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"处理缓冲MP3数据失败: {e}")
            return False
    
    def flush_mp3_buffer(self):
        """在TTS结束时刷新MP3缓冲区"""
        with self.mp3_buffer_lock:
            if len(self.mp3_buffer) > 0:
                logger.info(f"刷新MP3缓冲区: {len(self.mp3_buffer)} 字节")
                # 尝试最后一次处理剩余数据
                pcm_data = self.process_mp3_audio_data(bytes(self.mp3_buffer))
                if pcm_data:
                    self.audio_queue.put(pcm_data)
                    logger.debug("成功处理缓冲区剩余数据")
                else:
                    logger.warning("无法处理缓冲区剩余数据")
                self.mp3_buffer.clear()
    
    def initialize_tts_player(self):
        """初始化TTS音频播放器 - 只在第一次调用时执行"""
        if self.tts_initialized:
            return
            
        try:
            # 创建音频输出流
            self.output_stream = self.audio_device.open_output_stream()
            self.output_stream.start_stream()
            
            # 启动播放线程
            self.player_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
            self.player_thread.start()
            
            # 开始录制第一个TTS音频文件
            self.start_audio_recording()
            
            self.tts_initialized = True
            logger.info(f"🎵 TTS音频播放器已初始化 (格式: {self.audio_device.output_config.sample_rate}Hz, Float32)")
            
        except Exception as e:
            logger.error(f"初始化TTS播放器失败: {e}")
            raise
    
    def handle_websocket_response(self, data: dict):
        """处理WebSocket响应，类似audio_manager.py的handle_server_response"""
        if data["type"] == "start":
            logger.info("开始处理麦克风音频消息...")
            
        elif data["type"] == "stream_chunk":
            self.chunk_count += 1
            content = data["content"]
            self.full_response += content
            logger.info(f"收到第{self.chunk_count}个内容片段: '{content}'")
            print(content, end="", flush=True)
            
        elif data["type"] == "tts_start":
            logger.info("TTS语音合成开始...")
            # TTS播放器已在会话开始时预先初始化，这里只需确保已初始化
            # self.initialize_tts_player()  # 如果已初始化会直接返回
            
        elif data["type"] == "tts_audio":
            # 记录第一个TTS音频收到的时间
            if self.first_tts_audio_received_time is None:
                self.first_tts_audio_received_time = time.time()
                if self.audio_send_completed_time is not None:
                    delay = self.first_tts_audio_received_time - self.audio_send_completed_time
                    logger.info(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {delay:.3f}秒")
            
            # 处理MP3格式的TTS音频数据
            mp3_data = base64.b64decode(data["audio_data"])
            logger.info(f"收到TTS音频数据: {len(mp3_data)} 字节 (MP3格式)")
            
            # 先将原始MP3数据存储到录制缓冲区
            if self.is_recording_audio:
                self.mp3_audio_buffer.extend(mp3_data)
            
            # 使用缓冲机制处理MP3数据
            self.process_mp3_stream_data(mp3_data)
            
        elif data["type"] == "tts_end":
            logger.info("当前句子TTS语音合成完成")
            # 刷新MP3缓冲区，处理剩余数据
            self.flush_mp3_buffer()
            # 每句话的TTS结束，但播放器继续运行等待下一句
            # 不做任何清理操作，保持播放器和录制继续
            
        elif data["type"] == "end":
            logger.info("服务器一次回复结束，等待用户继续说话...")
            # end只是一次回复结束，不是整个会话结束
            # 保持播放器和录制继续运行，等待下一轮对话
            
        elif data["type"] == "error":
            logger.error(f"发生错误: {data['message']}")
            self.response_completed = True
    
    async def receive_loop(self):
        """接收消息循环"""
        try:
            while self.is_running and not self.response_completed:
                try:
                    response = await self.websocket.recv()
                    data = json.loads(response)
                    logger.info(f"收到响应: {data['type']}")
                    self.handle_websocket_response(data)
                    
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket连接已关闭")
                    self.response_completed = True
                    break
                except Exception as e:
                    logger.error(f"接收消息时发生错误: {str(e)}")
                    break
                    
        except Exception as e:
            logger.error(f"接收任务异常: {str(e)}")
            self.response_completed = True
    
    async def microphone_input_loop(self):
        """麦克风输入循环，参考audio_manager.py的process_microphone_input"""
        try:
            input_stream = self.audio_device.open_input_stream()
            logger.info("🎤 已打开麦克风，请讲话...")
            
            while self.is_recording and not self.response_completed:
                try:
                    # 读取麦克风数据
                    audio_chunk = input_stream.read(
                        self.audio_device.input_config.chunk, 
                        exception_on_overflow=False
                    )
                    
                    # 转换为base64并发送
                    audio_base64 = base64.b64encode(audio_chunk).decode('utf-8')
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await self.websocket.send(json.dumps(audio_message))
                    await asyncio.sleep(0.01)  # 避免CPU过度使用
                    
                except Exception as e:
                    logger.error(f"读取麦克风数据出错: {e}")
                    await asyncio.sleep(0.1)
            
            logger.info("🔇 麦克风录制已停止")
            self.audio_send_completed_time = time.time()
            logger.info(f"📤 麦克风音频录制完成，时间戳: {self.audio_send_completed_time}")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            self.is_recording = False
    
    async def auto_stop_after_timeout(self, timeout_seconds=20):
        """自动停止录制的超时处理"""
        await asyncio.sleep(timeout_seconds)
        logger.info(f"录制时间达到{timeout_seconds}秒，自动停止...")
        self.is_recording = False
    
    async def start(self):
        """启动WebSocket测试会话"""
        try:
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                logger.info("已连接到WebSocket服务器")
                logger.info("=== 开始麦克风音频测试 ===")
                
                # 在会话开始时就初始化TTS播放器，准备接收音频
                self.initialize_tts_player()
                logger.info("🎵 TTS播放器已预先初始化，准备接收多轮对话...")
                
                # 创建异步任务
                receive_task = asyncio.create_task(self.receive_loop())
                microphone_task = asyncio.create_task(self.microphone_input_loop())
                # timeout_task = asyncio.create_task(self.auto_stop_after_timeout(20))
                
                # 等待任务完成（这里会一直运行直到用户中断或出错）
                await asyncio.gather(receive_task, microphone_task, return_exceptions=True)
                
                print(f"\n=== 麦克风音频会话结束，总共收到 {self.chunk_count} 个内容片段 ===")
                logger.info(f"完整响应内容: {self.full_response}")
                
                # 会话结束时停止录制并保存音频文件
                if self.is_recording_audio:
                    saved_file = self.stop_audio_recording()
                    if saved_file:
                        logger.info(f"💾 完整会话TTS音频已保存: {saved_file}")
                
                # 输出延迟统计结果（如果有的话）
                if (self.audio_send_completed_time is not None and 
                    self.first_tts_audio_received_time is not None):
                    delay = self.first_tts_audio_received_time - self.audio_send_completed_time
                    print(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {delay:.3f}秒")
                else:
                    print("⚠️ 未统计到完整的音频延迟数据")
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"连接WebSocket失败: {str(e)}")
        finally:
            # 清理资源
            self.is_playing = False
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
        """发送测试音频文件数据的任务"""
        try:
            # 测试音频文件列表
            test_audio_files = [
                "audio_test_data/converted_20250630_151526_你好.wav",
                "audio_test_data/converted_20250630_151540_我想了解一下.wav", 
                "audio_test_data/converted_20250630_151545_你的功能.wav",
                "audio_test_data/converted_20250630_151551_和特点.wav"
            ]
            
            for audio_file in test_audio_files:
                if not self.is_running:
                    break
                    
                logger.info(f"正在发送测试音频文件: {audio_file}")
                
                # 检查文件是否存在
                if not os.path.exists(audio_file):
                    logger.warning(f"音频文件不存在，跳过: {audio_file}")
                    continue
                
                # 读取音频文件数据
                audio_data = self.read_audio_file(audio_file)
                if audio_data is None:
                    logger.error(f"无法读取音频文件: {audio_file}")
                    continue
                
                # 模拟实时发送，将音频数据分片发送
                # 200ms音频块大小：16kHz × 1声道 × 2字节 × 0.2秒 = 6400字节
                CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
                total_chunks = len(audio_data) // CHUNK_SIZE + (1 if len(audio_data) % CHUNK_SIZE else 0)
                
                logger.info(f"开始分片发送音频数据，总共 {total_chunks} 个片段")
                
                for i in range(0, len(audio_data), CHUNK_SIZE):
                    if not self.is_running:
                        break
                        
                    chunk = audio_data[i:i + CHUNK_SIZE]
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await self.websocket.send(json.dumps(audio_message))
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.2)  # 200ms间隔，匹配音频块时长
                
                logger.info(f"音频文件 {audio_file} 发送完成")
                
                # 在音频文件之间添加停顿
                await asyncio.sleep(2)
            
            logger.info("所有测试音频文件发送完成")
            
            # 发送2秒的静音数据
            logger.info("正在发送2秒静音数据...")
            silence_data = self.generate_silence_audio(duration_ms=2000)  # 2秒静音
            if silence_data:
                # 模拟实时发送，将静音数据分片发送
                CHUNK_SIZE = 6400  # 每次发送200ms的音频数据
                
                for i in range(0, len(silence_data), CHUNK_SIZE):
                    if not self.is_running:
                        break
                        
                    chunk = silence_data[i:i + CHUNK_SIZE]
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await self.websocket.send(json.dumps(audio_message))
                    
                    # 控制发送频率，模拟真实音频流
                    await asyncio.sleep(0.2)  # 200ms间隔，匹配音频块时长
                
                logger.info("2秒静音数据发送完成")
            else:
                logger.error("生成静音数据失败")
            
            # 记录音频发送完成时间
            self.audio_send_completed_time = time.time()
            logger.info(f"📤 所有音频数据发送完成，时间戳: {self.audio_send_completed_time}")
                    
        except Exception as e:
            logger.error(f"发送音频文件失败: {str(e)}")
            self.is_running = False

    async def start_with_files(self):
        """启动WebSocket测试会话（文件模式）"""
        self.file_mode = True
        try:
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                logger.info("已连接到WebSocket服务器")
                logger.info("=== 开始音频文件测试 ===")
                
                # 在会话开始时就初始化TTS播放器，准备接收音频
                self.initialize_tts_player()
                logger.info("🎵 TTS播放器已预先初始化，准备接收音频...")
                
                # 创建异步任务
                receive_task = asyncio.create_task(self.receive_loop())
                file_send_task = asyncio.create_task(self.send_audio_files_loop())
                
                # 等待任务完成
                await asyncio.gather(receive_task, file_send_task, return_exceptions=True)
                
                print(f"\n=== 音频文件测试完成，总共收到 {self.chunk_count} 个内容片段 ===")
                logger.info(f"完整响应内容: {self.full_response}")
                
                # 会话结束时停止录制并保存音频文件
                if self.is_recording_audio:
                    saved_file = self.stop_audio_recording()
                    if saved_file:
                        logger.info(f"💾 完整会话TTS音频已保存: {saved_file}")
                
                # 输出延迟统计结果（如果有的话）
                if (self.audio_send_completed_time is not None and 
                    self.first_tts_audio_received_time is not None):
                    delay = self.first_tts_audio_received_time - self.audio_send_completed_time
                    print(f"⏱️ 音频发送完成到首个TTS音频接收延迟: {delay:.3f}秒")
                else:
                    print("⚠️ 未统计到完整的音频延迟数据")
                
        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"连接WebSocket失败: {str(e)}")
        finally:
            # 清理资源
            self.is_playing = False
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
