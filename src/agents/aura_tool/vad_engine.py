import os
import numpy as np
from loguru import logger
from funasr_onnx import Fsmn_vad_online
from scipy import signal

class VADEngine:
    """基于FunASR的流式ASR引擎"""
    
    def __init__(self, input_sample_rate: int = 16000):
        self.audio_buffer = []
        self.sample_rate = 16000  # 目标采样率
        self.input_sample_rate = input_sample_rate  # 输入采样率
        self.chunk_size = 200
        self.model = None
        # 初始化流式识别参数
        self.chunk_stride = int(self.chunk_size * self.sample_rate / 1000)
        # 计算重采样比例
        self.resample_ratio = self.sample_rate / self.input_sample_rate
    
    def start(self):
        """启动ASR引擎"""
        self.model = Fsmn_vad_online(os.path.join(os.path.dirname(__file__), "model/vad"), quantize=True)
    
    def resample_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """将音频从输入采样率重采样到目标采样率"""
        if self.input_sample_rate == self.sample_rate:
            return audio_data
        
        # 计算重采样后的长度
        resampled_length = int(len(audio_data) * self.resample_ratio)
        
        # 使用scipy进行重采样
        resampled_audio = signal.resample(audio_data, resampled_length)
        
        return resampled_audio.astype(np.float32)
        
    def process_audio_chunk(self, audio_data: bytes):
        """处理音频数据块"""
        try:
            # 将音频数据添加到缓冲区
            # logger.info(f"音频数据长度: {len(audio_data)}")
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            self.audio_buffer.extend(audio_array)
            
            # 检查是否有足够的音频数据进行处理
            if len(self.audio_buffer) < self.chunk_stride:
                return None
            
            # 提取一个chunk进行处理
            speech_chunk = np.array(self.audio_buffer[:self.chunk_stride], dtype=np.float32) / 32767.0
            self.audio_buffer = self.audio_buffer[self.chunk_stride:]
            
            # 重采样音频数据
            speech_chunk = self.resample_audio(speech_chunk)
            
            try:
                # 使用FunASR流式识别
                if self.model is not None:
                    result = self.model(audio_in=speech_chunk)
                else:
                    logger.error("ASR模型未初始化")
                    return None
                
                # 解析结果
                if len(result) > 0:
                    return result
                return None
            except Exception as e:
                logger.error(f"FunASR识别失败: {e}")
                return None
        except Exception as e:
            logger.error(f"处理音频数据失败: {e}")
            return None
    
    def cleanup(self):
        """清理资源"""
        self.audio_buffer = []
