import uuid

# ASR API配置
asr_config = {
    "base_url": "ws://sd1r107kfo0m61h76b49g.apigateway-cn-beijing.volceapi.com/ws/stream/asr",
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

vad_config = {
    # "base_url": "ws://sd1vnrgvr8npbn2c42ke0.apigateway-cn-beijing.volceapi.com/ws/stream/vad",
    "base_url": "ws://sd20ng67r8npbn2c43olg.apigateway-cn-beijing.volceapi.com/ws/stream/vad",
    "headers": {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Access-Key": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",
        "X-Api-App-Key": "4522921771",
    },
}

vad_split_config = {
    # "base_url": "ws://sd1vnrgvr8npbn2c42ke0.apigateway-cn-beijing.volceapi.com/ws/stream/vad_split",
    "base_url": "ws://sd20ng67r8npbn2c43olg.apigateway-cn-beijing.volceapi.com/ws/stream/vad_split",
    "headers": {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Access-Key": "a-dexJIefJUDznZAtt3Qj_yAivD0BU9H",
        "X-Api-App-Key": "4522921771",
    },
}
