from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from agents.aura import AuraAgent
import uvicorn
from config import settings
from agents.message_processor_audio import MessageProcessorAudio

logger = logging.getLogger(__name__)

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
    logger.info(f"开始处理WebSocket连接")
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
