import uuid

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": "4522921771",
        "X-Api-Access-Key": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",
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
        "bot_name": "aura",
        "system_role": "你是Aura，一个智能助手，现在你在参与和朋友的一场QQ聊天，你只负责随口闲聊，避免冷场，但不要有任何实质性回复",
        "speaking_style": "自然、随意、简短，注意更多口语化表达。不要讲任何实质性内容",
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
        "X-Api-Access-Key": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",
        "X-Api-App-Key": "4522921771",
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
    "app_id": "4522921771",  # 需要配置实际的app_id
    "token": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",   # 需要配置实际的token
    "speaker": "zh_female_shuangkuaisisi_moon_bigtts",  # 默认说话人
    "audio": {
        "format": "pcm",
        "sample_rate": 24000
    }
}
