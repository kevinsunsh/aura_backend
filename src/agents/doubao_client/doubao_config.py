import uuid
import json

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": "5747111361",
        "X-Api-Access-Key": "t03OTM_abaNE-o1ZJvhNnPfR4aC4oU3v",
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
    "app_id": "4522921771",  # 需要配置实际的app_id
    "token": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",   # 需要配置实际的token
    "speaker": "zh_female_roumeinvyou_emo_v2_mars_bigtts"  # 默认说话人
}

class MoodLevel:
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    @staticmethod
    def map_to_scale(mood_level):
        return {
            MoodLevel.VERY_LOW: 1,
            MoodLevel.LOW: 2,
            MoodLevel.MEDIUM: 3,
            MoodLevel.HIGH: 4,
            MoodLevel.VERY_HIGH: 5
        }[mood_level]
    @staticmethod
    def get_mood_level_str():
        return "very_low|low|medium|high|very_high"
        
class SpeechRate:
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"
    VERY_FAST = "very_fast"
    @staticmethod
    def map_to_scale(speech_rate):
        return {
            SpeechRate.VERY_SLOW: -25,
            SpeechRate.SLOW: -10,
            SpeechRate.NORMAL: 0,
            SpeechRate.FAST: 25,
            SpeechRate.VERY_FAST: 50
        }[speech_rate]
    @staticmethod
    def get_speech_rate_str():
        return "very_slow|slow|normal|fast|very_fast"

speaker_config = {
    "female_1": {
        "voice_code": "zh_female_roumeinvyou_emo_v2_mars_bigtts",
        "mood": ["开心", "悲伤", "生气", "惊讶", "恐惧", "厌恶", "激动", "冷漠", "中性"],
        "mood_code": ["happy", "sad", "angry", "surprised", "fear", "hate", "excited", "coldness", "neutral"],
        "mood_str": "happy|sad|angry|surprised|fear|hate|excited|coldness|neutral"
    },
    "female_2": {
        "voice_code": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
        "mood": ["开心", "悲伤", "生气", "惊讶", "恐惧", "厌恶", "激动", "冷漠", "中性"],
        "mood_code": ["happy", "sad", "angry", "surprised", "fear", "hate", "excited", "coldness", "neutral"],
        "mood_str": "happy|sad|angry|surprised|fear|hate|excited|coldness|neutral"
    }
}

def get_tts_payload_bytes(uid, event, speaker='', text='', mood_code='neutral', mood_level='medium', speech_rate='normal'):
    return str.encode(json.dumps({
        "user": {"uid": uid},
        "event": event,
        "namespace": "BidirectionalTTS",
        "req_params": {
            "text": text,
            "speaker": speaker,
            # "additions": {
            #     "mute_cut_threshold": "400",
            #     "mute_cut_remain_ms": "1"
            # },
            "audio_params": {
                "format": "pcm",
                "sample_rate": 24000,
                "channel": 1,
                "emotion": mood_code,
                "emotion_scale": MoodLevel.map_to_scale(mood_level),
                "speech_rate": SpeechRate.map_to_scale(speech_rate),
            }
        }
    }))
