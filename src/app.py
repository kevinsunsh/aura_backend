import sys
import uvicorn
from loguru import logger
from config import settings
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request

TAG_COLOR = {
    "BASE": ("<magenta>{extra[tag]}</magenta>", "<white>{message}</white>"),
    "DELAY": ("<cyan>{extra[tag]}</cyan>", "<green>{message}</green>"),
    "CONNECTION": ("<yellow>{extra[tag]}</yellow>", "<blue>{message}</blue>"),
    "TTS": ("<red>{extra[tag]}</red>", "<green>{message}</green>"),
}

def tag_color_format(record):
    tag = record["extra"].get("tag", "NO_TAG")
    tag_fmt, msg_fmt = TAG_COLOR.get(tag, ("<white>{extra[tag]}</white>", "<white>{message}</white>"))
    return (
        "<green>{time:HH:mm:ss}</green> | "
        # "<level>{level: <8}</level> | "
        # "<cyan>{file}</cyan> | "
        f"{tag_fmt} | "
        f"{msg_fmt}"
        "\n"
    )

def log_filter(record):
    tag = record["extra"].get("tag")
    # return tag in ["TTS", "BASE"]
    # return False
    return tag in ["BASE", "DELAY"]

# 配置输出格式，包含文件名和 tag
logger.remove()
# f"{settings.LOG_DIR}/main.log",
logger.add(
    sys.stdout,
    level="INFO",
    filter=log_filter,
    format=tag_color_format
)

from agents.aura import AuraAgent
from agents.message_processor_audio import MessageProcessorAudio

app = FastAPI(
    title="Aura Agent Service",
    description="Aura Agent Service",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有请求头
)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """WebSocket 流式聊天端点，实时流式返回响应内容，支持文本和音频输入"""
    logger.bind(tag="BASE").info(f"开始处理WebSocket连接")
    await AuraAgent.get_instance().handle_websocket_connection(websocket)

@app.get("/sse")
async def sse_endpoint(request: Request):
    return StreamingResponse(MessageProcessorAudio.get_instance().send_sse_message(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT
    )
