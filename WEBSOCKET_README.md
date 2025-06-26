# WebSocket 流式聊天功能

## 概述

本项目已添加 WebSocket 流式聊天功能，支持实时流式响应，提供更好的用户体验。

## 功能特性

- ✅ 实时 WebSocket 连接
- ✅ 流式响应传输
- ✅ 多用户支持
- ✅ 连接状态管理
- ✅ 错误处理和重连机制
- ✅ 消息类型区分（开始、流式、结束、错误）

## API 端点

### WebSocket 端点

1. **主要聊天端点**: `ws://localhost:5876/ws/{user_id}`
2. **备用聊天端点**: `ws://localhost:5876/ws/chat/{user_id}`

### HTTP 端点（保持兼容）

- **健康检查**: `GET /health`
- **传统聊天**: `POST /chat`

## 使用方法

### 1. 启动服务器

```bash
# 启动 FastAPI 服务器
uvicorn app.app:app --host 0.0.0.0 --port 5876 --reload
```

### 2. WebSocket 连接

#### JavaScript 客户端示例

```javascript
// 连接到 WebSocket
const userId = "your_user_id";
const ws = new WebSocket(`ws://localhost:5876/ws/${userId}`);

// 连接建立
ws.onopen = function(event) {
    console.log('WebSocket 连接已建立');
};

// 接收消息
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
        case 'start':
            console.log('开始处理消息...');
            break;
        case 'stream':
            console.log('流式内容:', data.message);
            // 实时显示流式内容
            break;
        case 'end':
            console.log('处理完成');
            break;
        case 'error':
            console.error('错误:', data.message);
            break;
    }
};

// 发送消息
function sendMessage(message) {
    const messageData = {
        message: message
    };
    ws.send(JSON.stringify(messageData));
}

// 发送聊天消息
sendMessage("你好，请介绍一下自己");
```

#### Python 客户端示例

```python
import asyncio
import websockets
import json

async def chat_client():
    uri = "ws://localhost:5876/ws/test_user_001"
    
    async with websockets.connect(uri) as websocket:
        # 发送消息
        message_data = {
            "message": "你好，请介绍一下自己"
        }
        await websocket.send(json.dumps(message_data))
        
        # 接收流式响应
        async for message in websocket:
            data = json.loads(message)
            print(f"类型: {data['type']}, 内容: {data.get('message', '')}")

# 运行客户端
asyncio.run(chat_client())
```

### 3. 消息格式

#### 客户端发送格式

```json
{
    "message": "用户输入的消息内容"
}
```

#### 服务器响应格式

```json
// 开始处理
{
    "type": "start",
    "message": "开始处理您的消息..."
}

// 流式内容
{
    "type": "stream",
    "message": "流式响应的文本内容"
}

// 处理完成
{
    "type": "end",
    "message": "处理完成"
}

// 错误信息
{
    "type": "error",
    "message": "错误描述"
}
```

## 测试工具

### HTML 测试客户端

项目包含一个完整的 HTML 测试客户端 (`websocket_test_client.html`)，可以直接在浏览器中打开使用：

1. 打开 `websocket_test_client.html` 文件
2. 输入用户ID（默认：test_user_001）
3. 点击"连接"按钮
4. 在消息输入框中输入内容并发送
5. 观察流式响应的实时显示

### 功能演示

测试客户端支持以下功能：

- ✅ 连接状态显示
- ✅ 实时消息发送
- ✅ 流式响应显示
- ✅ 错误处理
- ✅ 连接断开重连

## 技术实现

### 核心组件

1. **ConnectionManager**: WebSocket 连接管理器
   - 管理多个用户的 WebSocket 连接
   - 处理连接建立和断开
   - 支持个人消息和广播消息

2. **NovaAgent**: 聊天代理
   - 支持流式回调函数
   - 保持与现有系统的兼容性
   - 提供 `chat_with_stream` 方法

3. **WebSocket 端点**: 
   - `/ws/{user_id}`: 主要聊天端点
   - `/ws/chat/{user_id}`: 备用聊天端点

### 流式处理流程

1. 客户端建立 WebSocket 连接
2. 客户端发送消息到服务器
3. 服务器接收消息并开始处理
4. 服务器通过流式回调发送处理进度
5. 客户端实时接收并显示流式内容
6. 处理完成后发送结束信号

### 错误处理

- WebSocket 连接断开自动重连
- 消息格式错误提示
- 服务器处理异常捕获
- 连接状态实时监控

## 配置说明

### 环境变量

确保以下环境变量已正确配置：

```bash
# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB_FOR_MEMORY=0
REDIS_PASSWORD=your_password
REDIS_USERNAME=your_username

# 服务器配置
SERVER_PORT=5876
RESPONSE_CALLBACK_URL=http://your-callback-url
```

### 端口配置

默认 WebSocket 端口为 5876，可通过环境变量 `SERVER_PORT` 修改。

## 性能优化

### 连接管理

- 自动清理断开的连接
- 支持多用户并发连接
- 连接状态实时监控

### 消息处理

- 异步流式处理
- 错误隔离，不影响其他连接
- 内存使用优化

## 安全考虑

1. **用户验证**: 建议在生产环境中添加用户身份验证
2. **消息验证**: 验证客户端发送的消息格式
3. **连接限制**: 限制单个用户的连接数量
4. **超时处理**: 设置合理的连接超时时间

## 故障排除

### 常见问题

1. **连接失败**
   - 检查服务器是否启动
   - 确认端口是否正确
   - 检查防火墙设置

2. **消息发送失败**
   - 确认 WebSocket 连接状态
   - 检查消息格式是否正确
   - 查看服务器日志

3. **流式响应中断**
   - 检查网络连接稳定性
   - 查看服务器错误日志
   - 确认 NovaAgent 配置正确

### 日志查看

服务器日志会记录以下信息：
- WebSocket 连接建立和断开
- 消息处理状态
- 错误信息和异常

## 扩展功能

### 可能的扩展

1. **消息历史**: 保存聊天历史记录
2. **用户管理**: 添加用户认证和权限管理
3. **群聊功能**: 支持多用户群聊
4. **文件传输**: 支持文件上传和下载
5. **消息加密**: 添加端到端加密

## 总结

WebSocket 流式聊天功能提供了实时、流畅的聊天体验，支持流式响应传输，适用于需要实时交互的应用场景。通过合理的错误处理和连接管理，确保了系统的稳定性和可靠性。 