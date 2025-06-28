import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
import json
import logging
from agents.aura import AuraAgent, ChatRequest
import uvicorn
from config import settings

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

# 获取AuraAgent实例
aura_agent = AuraAgent.get_instance()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat")
async def chat(request: ChatRequest):
    """HTTP聊天接口，收集完整内容后返回响应"""
    try:
        full_response = ""
        async for chunk in AuraAgent.chat(request):
            if chunk["status"] == "streaming":
                full_response += chunk["content"]
            elif chunk["status"] == "completed":
                break
            elif chunk["status"] == "error":
                raise HTTPException(status_code=500, detail=chunk["content"])
        
        return {
            "user_id": request.user_id,
            "response": full_response,
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/stream/{user_id}")
async def websocket_stream_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket 流式聊天端点，实时流式返回响应内容"""
    await aura_agent.handle_websocket_connection(websocket, user_id)

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=settings.DEBUG
    )
