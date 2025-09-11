# aura_backend

## VAD 二进制可执行服务

提供一个基于 FastAPI 的 HTTP 服务封装 `VADEngine`，可打包为单文件二进制。

### 接口

- `GET /healthz`: 服务健康检查，返回 `{ status, started }`。
- `POST /start`: 启动引擎。
  - 请求体：`{ "model_path": "可选，默认src_go/internal/tool/model/vad", "input_sample_rate": 16000 }`
- `POST /stop`: 停止引擎。
- `POST /audio`: 发送原始 PCM16LE 字节数据，返回 VAD 推理结果。

### 运行（源码方式）

```bash
export VAD_SERVICE_HOST=0.0.0.0
export VAD_SERVICE_PORT=8080
python3 -m uvicorn src_go.internal.tool.vad_service:app --host $VAD_SERVICE_HOST --port $VAD_SERVICE_PORT
```

### 构建二进制

```bash
bash src_go/internal/tool/build_vad_service.sh
# 成功后二进制位于 dist/vad-service
```

### 启动二进制

```bash
./dist/vad-service
```

### 示例调用

```bash
curl -s http://127.0.0.1:8080/healthz

curl -s -X POST http://127.0.0.1:8080/start -H 'Content-Type: application/json' \
  -d '{"input_sample_rate":16000}'

# 发送音频（以 16k PCM16LE 原始数据为例）
curl -s -X POST http://127.0.0.1:8080/audio --data-binary @tests/test.pcm

curl -s -X POST http://127.0.0.1:8080/stop
```
