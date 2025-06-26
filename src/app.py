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

# WebSocket 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"用户 {user_id} 已连接 WebSocket")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"用户 {user_id} 已断开 WebSocket 连接")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"发送消息给用户 {user_id} 失败: {str(e)}")
                self.disconnect(user_id)

manager = ConnectionManager()

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
    await manager.connect(websocket, user_id)
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # 验证消息格式
            if "message" not in message_data:
                await manager.send_personal_message({
                    "type": "error",
                    "message": "消息格式错误，缺少 'message' 字段"
                }, user_id)
                continue
            
            user_message = message_data["message"]
            
            # 发送开始处理的消息
            await manager.send_personal_message({
                "type": "start",
                "message": "开始处理您的消息..."
            }, user_id)
            
            try:
                # 创建聊天请求
                chat_request = ChatRequest(user_id=user_id)
                
                # 使用流式聊天方法，实时发送每个内容片段
                async for chunk in AuraAgent.chat(chat_request):
                    if chunk["status"] == "streaming":
                        # 发送流式内容片段
                        await manager.send_personal_message({
                            "type": "stream_chunk",
                            "content": chunk["content"],
                            "user_id": chunk["user_id"]
                        }, user_id)
                    elif chunk["status"] == "completed":
                        # 发送完成消息
                        await manager.send_personal_message({
                            "type": "end",
                            "message": "处理完成"
                        }, user_id)
                        break
                    elif chunk["status"] == "error":
                        # 发送错误消息
                        await manager.send_personal_message({
                            "type": "error",
                            "message": chunk["content"]
                        }, user_id)
                        break
                
            except Exception as e:
                logger.error(f"处理聊天请求失败: {str(e)}")
                await manager.send_personal_message({
                    "type": "error",
                    "message": f"处理失败: {str(e)}"
                }, user_id)
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket 连接错误: {str(e)}")
        manager.disconnect(user_id)



if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=settings.DEBUG
    )
