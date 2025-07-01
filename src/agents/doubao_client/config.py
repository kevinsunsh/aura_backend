import uuid
import pyaudio

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": "7303031858",
        "X-Api-Access-Key": "78VO_doF2SAJ6NwVmoS3RCOQcwyz_oLv",
        "X-Api-Resource-Id": "volc.speech.dialog",
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
}

start_session_req = {
    "tts": {
        "audio_config": {
            "channel": 1,
            "format": "pcm",
            "sample_rate": 24000
        },
        "voice": {
            "name": "zh_female_1"
        }
    },
    "dialog": {
        "bot_name": "豆包",
    }
}

input_audio_config = {
    "chunk": 3200,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 16000,
    "bit_size": pyaudio.paInt16
}

output_audio_config = {
    "chunk": 3200,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 24000,
    "bit_size": pyaudio.paFloat32
}

# ASR API配置
asr_config = {
    "ws_url": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    "headers": {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Access-Key": "78VO_doF2SAJ6NwVmoS3RCOQcwyz_oLv",
        "X-Api-App-Key": "7303031858",
    },
    "audio": {
        "format": "pcm",
        "sample_rate": 16000,
        "bits": 16,
        "channel": 1,
        "codec": "raw"
    },
    "seg_duration": 200,  # 分片时长(ms) - 双向流式模式推荐200ms以获得最优性能
    "uid": "aura_user"
}

# TTS API配置
tts_config = {
    "ws_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
    "app_id": "7303031858",  # 需要配置实际的app_id
    "token": "78VO_doF2SAJ6NwVmoS3RCOQcwyz_oLv",   # 需要配置实际的token
    "speaker": "zh_female_shuangkuaisisi_moon_bigtts",  # 默认说话人
    "audio": {
        "format": "mp3",
        "sample_rate": 24000
    }
}
