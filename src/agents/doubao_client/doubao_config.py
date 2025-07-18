import uuid

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": "5859418345",
        "X-Api-Access-Key": "T8ZFE-6co2c5w-DY7rAf8gDR63sxxzI3",
        "X-Api-Resource-Id": "volc.speech.dialog",
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
}

default_session_req = {
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
        "bot_name": "aura",
        "system_role": "你是Aura，你只会说一些口头禅，例如：我想想。等一下。稍等。好呀。嗯嗯。之类的。不要任何其他内容",
        "speaking_style": "你只会说一些口头禅，例如：我想想。等一下。稍等。好呀。嗯嗯。之类的。不要任何其他内容",
        "dialog_id": str(uuid.uuid4()),
        "extra" : {
            "strict_audit": False
        }
    }
}

# ASR API配置
asr_config = {
    "ws_url": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    "headers": {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Access-Key": "wo4mooD0lf3nNJlfNoYsnHzrx7Dl5jrl",
        "X-Api-App-Key": "4427555468",
    },
    "audio": {
        "format": "pcm",
        "sample_rate": 16000,
        "bits": 16,
        "channel": 1,
        "codec": "raw"
    },
    "seg_duration": 200  # 分片时长(ms) - 双向流式模式推荐200ms以获得最优性能
}

# TTS API配置
tts_config = {
    "ws_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
    "app_id": "5859418345",  # 需要配置实际的app_id
    "token": "T8ZFE-6co2c5w-DY7rAf8gDR63sxxzI3",   # 需要配置实际的token
    "speaker": "zh_female_wanwanxiaohe_moon_bigtts",  # 默认说话人
    "audio": {
        "format": "pcm",
        "sample_rate": 24000,
        "channel": 1
    }
}
