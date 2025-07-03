#!/usr/bin/env python3
"""使用真实音频文件测试新的ASR客户端"""
import asyncio
import sys
import os
import wave
import logging
from pathlib import Path

# 添加src路径
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def read_audio_file(file_path):
    """读取音频文件（支持WAV和MP3）"""
    try:
        # 首先读取完整的文件数据
        with open(file_path, 'rb') as f:
            audio_data = f.read()
        
        # 然后尝试解析WAV文件参数
        try:
            with wave.open(file_path, 'rb') as wav_file:
                # 获取音频参数
                params = wav_file.getparams()
                nchannels = params.nchannels
                sampwidth = params.sampwidth
                framerate = params.framerate
                nframes = params.nframes
                
                logger.info(f"WAV音频文件信息: {file_path}")
                logger.info(f"  声道数: {nchannels}")
                logger.info(f"  采样宽度: {sampwidth} bytes")
                logger.info(f"  采样率: {framerate} Hz")
                logger.info(f"  帧数: {nframes}")
                logger.info(f"  时长: {nframes/framerate:.2f} 秒")
                logger.info(f"  完整WAV文件大小: {len(audio_data)} bytes")
                
                return audio_data, "wav", params
        except:
            # 如果不是WAV文件，仍然返回完整数据
            logger.info(f"非WAV音频文件信息: {file_path}")
            logger.info(f"  数据大小: {len(audio_data)} bytes")
            
            # 对于非WAV文件，我们返回None作为params
            return audio_data, "other", None
            
    except Exception as e:
        logger.error(f"读取音频文件失败: {e}")
        return None, None, None

async def test_asr_with_file(file_path):
    """使用指定音频文件测试ASR客户端"""
    try:
        from agents.doubao_client.asr_client import AsrClient
        
        # 读取音频文件
        audio_data, audio_format, params = read_audio_file(file_path)
        if audio_data is None:
            logger.error(f"无法读取音频文件: {file_path}")
            return
        
        # 根据文件格式设置配置
        if audio_format == "wav" and params:
            # 检查WAV音频格式
            logger.info(f"WAV音频参数: {params.framerate}Hz, {params.sampwidth*8}bit, {params.nchannels}声道")
            
            # 使用WAV格式配置（与原始demo保持一致）
            asr_config = {
                "format": "wav",
                "rate": 16000,    # ASR API只支持16kHz
                "bits": 16,       # ASR API默认16bit
                "channel": 1,     # ASR API默认单声道
                "codec": "raw"    # 原始数据编码
            }
        else:
            # 使用默认配置
            logger.info("检测到非标准WAV格式，使用默认配置")
            asr_config = {
                "format": "wav",  # 使用WAV格式
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "codec": "raw"
            }
        
        # 定义回调函数
        result_text = ""
        
        async def asr_start_callback():
            logger.info("🎤 ASR开始识别")
            
        async def asr_end_callback(text: str):
            nonlocal result_text
            result_text = text
            logger.info(f"✅ ASR识别完成: {text}")
            
        # 创建ASR客户端，使用检测到的音频格式
        asr_client = AsrClient(
            asr_start_callback=asr_start_callback,
            asr_end_callback=asr_end_callback,
            **asr_config
        )
        
        logger.info("📡 启动ASR客户端...")
        await asr_client.start()
        logger.info("✅ ASR客户端启动成功")
        
        # 根据格式设置分片大小（双向流式模式推荐200ms分包以获得最优性能）
        if audio_format == "wav":
            # WAV文件：计算每200ms的数据大小（16000Hz * 2bytes * 0.2s = 6400 bytes）
            chunk_size = 6400  
        else:
            # 其他格式使用200ms分片大小
            chunk_size = 6400
        
        total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
        
        logger.info(f"📤 开始发送音频数据，总共 {total_chunks} 个分片...")
        
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await asr_client.process_audio_chunk(chunk)
            logger.debug(f"发送分片 {i//chunk_size + 1}/{total_chunks}, 大小: {len(chunk)} bytes")
            
            # 模拟实时发送，按200ms间隔
            await asyncio.sleep(0.2)  # 每200ms发送一个分片
        
        # 等待ASR处理完成
        logger.info("⏳ 等待ASR处理完成...")
        await asyncio.sleep(3)  # 等待处理完成
        
        logger.info("🧹 清理资源...")
        await asr_client.cleanup()
        
        return result_text
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_all_audio_files():
    """测试所有音频文件"""
    audio_dir = Path("audio_test_data")
    
    # 查找所有转换后的wav文件
    wav_files = list(audio_dir.glob("converted_*.wav"))
    
    if not wav_files:
        logger.error("未找到音频文件")
        return
    
    logger.info(f"找到 {len(wav_files)} 个音频文件")
    
    results = {}
    
    for wav_file in sorted(wav_files):
        logger.info(f"\n{'='*60}")
        logger.info(f"测试文件: {wav_file.name}")
        logger.info(f"{'='*60}")
        
        result = await test_asr_with_file(str(wav_file))
        results[wav_file.name] = result
        
        # 文件间等待一下
        await asyncio.sleep(2)
    
    # 打印所有结果
    logger.info(f"\n{'='*60}")
    logger.info("📊 测试结果汇总")
    logger.info(f"{'='*60}")
    
    for filename, result in results.items():
        logger.info(f"📁 {filename}")
        if result:
            logger.info(f"🗣️  识别结果: {result}")
        else:
            logger.info(f"❌ 识别失败")
        logger.info("")

if __name__ == "__main__":
    asyncio.run(test_all_audio_files()) 