#!/usr/bin/env python3
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

class StreamingAudioPlayer:
    """流式音频播放器，支持实时播放音频片段"""
    
    def __init__(self, sample_rate=24000, channels=1, sample_width=2):
        self.sample_rate = sample_rate
        self.channels = channels 
        self.sample_width = sample_width
        self.audio_queue = queue.Queue()
        self.is_playing = False
        self.play_thread = None
        self.pyaudio_instance = None
        self.stream = None
        
        # 音频文件录制
        self.is_recording = False
        self.audio_buffer = bytearray()
        self.output_file = None
        
    def start(self):
        """启动音频播放"""
        if self.is_playing:
            return
            
        self.is_playing = True
        self.pyaudio_instance = pyaudio.PyAudio()
        
        # 创建音频流 - 根据TTS配置使用24kHz
        self.stream = self.pyaudio_instance.open(
            format=self.pyaudio_instance.get_format_from_width(self.sample_width),
            channels=self.channels,
            rate=self.sample_rate,
            output=True
        )
        
        # 启动播放线程
        self.play_thread = threading.Thread(target=self._play_loop)
        self.play_thread.daemon = True
        self.play_thread.start()
        
        logger.info(f"🔊 音频播放器已启动 ({self.sample_rate}Hz, {self.channels}声道)")
        
    def start_recording(self, filename=None):
        """开始录制音频到文件"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"websocket_tts_output_{timestamp}.mp3"
        
        os.makedirs("audio_output", exist_ok=True)
        self.output_file = os.path.join("audio_output", filename)
        self.audio_buffer.clear()
        self.is_recording = True
        logger.info(f"🎤 开始录制TTS音频到: {self.output_file}")
        
    def add_audio_data(self, audio_data: bytes):
        """添加音频数据到播放队列和录制缓冲区"""
        if self.is_playing:
            self.audio_queue.put(audio_data)
            
        if self.is_recording:
            self.audio_buffer.extend(audio_data)
            
    def _play_loop(self):
        """音频播放循环"""
        while self.is_playing:
            try:
                # 获取音频数据，超时1秒
                audio_data = self.audio_queue.get(timeout=1.0)
                if audio_data:
                    # 直接播放音频数据（假设是正确格式的PCM数据）
                    self.stream.write(audio_data)
                    logger.info(f"🎵 播放音频数据: {len(audio_data)} 字节")
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"播放音频失败: {e}")
                
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
                
    def stop(self):
        """停止音频播放"""
        self.is_playing = False
        
        if self.play_thread:
            self.play_thread.join(timeout=2.0)
            
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
            
        # 停止录制
        self.stop_recording()
            
        logger.info("🔇 音频播放器已停止")

async def test_audio_websocket_stream():
    """测试带预处理音频文件的WebSocket流式接口"""
    uri = "ws://localhost:5876/ws/stream/test_user_123"
    
    # 响应处理状态
    response_completed = False
    full_response = ""
    chunk_count = 0
    
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
                    elif data["type"] == "tts_audio":
                        # 处理TTS音频数据 - 关键修改
                        audio_data = base64.b64decode(data["audio_data"])
                        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
                        
                        # 直接播放音频片段（流式播放）
                        play_audio_data(audio_data)
                    elif data["type"] == "tts_end":
                        logger.info("TTS语音合成完成")
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
                CHUNK_SIZE = 1024  # 每次发送1024字节
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
                    await asyncio.sleep(0.05)  # 50ms间隔，模拟实时音频流
                
                logger.info(f"音频文件 {audio_file} 发送完成")
                
                # 在音频文件之间添加停顿
                await asyncio.sleep(2)
            
            logger.info("所有测试音频文件发送完成")
                    
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
    
    # 麦克风录音参数
    SAMPLE_RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    CHUNK_SIZE = 1024
    
    # 初始化PyAudio
    p = pyaudio.PyAudio()
    
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
                        # 处理TTS音频数据 - 关键修改
                        audio_data = base64.b64decode(data["audio_data"])
                        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
                        
                        # 直接播放音频片段（流式播放）
                        play_audio_data(audio_data)
                    elif data["type"] == "tts_end":
                        logger.info("TTS语音合成完成")
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
            # 打开麦克风音频流
            mic_stream = p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE
            )
            
            logger.info(f"开始录制麦克风音频: {SAMPLE_RATE}Hz, {CHANNELS}声道, 16位")
            logger.info("请开始说话，按 Ctrl+C 停止录制...")
            
            while recording_active and not response_completed:
                try:
                    # 从麦克风读取音频数据
                    audio_chunk = mic_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    # 将音频数据转换为base64编码
                    audio_base64 = base64.b64encode(audio_chunk).decode('utf-8')
                    
                    # 发送音频消息
                    audio_message = {
                        "audio": audio_base64,
                        "audio_format": "pcm"
                    }
                    
                    await websocket.send(json.dumps(audio_message))
                    
                    # 短暂等待，避免过于频繁的发送
                    await asyncio.sleep(0.01)  # 10ms间隔
                    
                except Exception as e:
                    logger.error(f"录制或发送音频时发生错误: {str(e)}")
                    break
            
            # 关闭麦克风流
            mic_stream.stop_stream()
            mic_stream.close()
            logger.info("麦克风录制已停止")
                    
        except Exception as e:
            logger.error(f"麦克风录制失败: {str(e)}")
            recording_active = False
    
    async def handle_user_input():
        """处理用户输入，用于控制录制"""
        nonlocal recording_active, response_completed
        
        try:
            # 等待用户按键停止录制
            await asyncio.sleep(1)  # 给其他任务启动的时间
            
            # 这里可以添加更复杂的用户交互逻辑
            # 目前简单地录制20秒后自动停止
            await asyncio.sleep(20)  # 录制20秒
            
            logger.info("录制时间达到20秒，自动停止...")
            recording_active = False
            
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
            
    except KeyboardInterrupt:
        logger.info("用户中断测试")
        recording_active = False
        response_completed = True
    except Exception as e:
        logger.error(f"连接WebSocket失败: {str(e)}")
    finally:
        # 清理PyAudio资源
        p.terminate()
        # 确保音频播放器已停止
        audio_player.stop()

if __name__ == "__main__":
    # 测试预处理音频文件输入
    print("=== 测试预处理音频文件输入 ===")
    asyncio.run(test_audio_websocket_stream())
    
    # 测试麦克风输入
    # print("=== 测试麦克风输入 ===")
    # asyncio.run(test_microphone_websocket_stream()) 