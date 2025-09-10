# AuraAgent - WebSocket连接管理器

## 概述

AuraAgent是Go版本的WebSocket连接管理器，负责处理客户端连接、会话管理和消息分发。它**完全重构**以对应Python版本的`aura.py`实现，使用相同的函数名和结构，确保行为一致性。

## 🔄 重构说明

### 函数名对应关系

| Python版本 | Go版本 | 说明 |
|------------|--------|------|
| `get_instance()` | `GetInstance()` | 单例模式获取实例 |
| `handle_websocket_connection()` | `handleWebSocketConnection()` | 主要连接处理 |
| `_wait_for_connection_start()` | `waitForConnectionStart()` | 等待连接开始 |
| `_wait_for_session_start()` | `waitForSessionStart()` | 等待会话开始 |
| `_message_processing_loop()` | `messageProcessingLoop()` | 消息处理循环 |
| `_wait_for_graceful_shutdown()` | `waitForGracefulShutdown()` | 优雅关闭 |
| `send_websocket_message()` | `sendWebSocketMessage()` | 发送WebSocket消息 |
| `_parse_binary_protocol_message()` | `parseBinaryProtocolMessage()` | 解析二进制协议 |
| `_construct_protocol_message()` | `constructProtocolMessage()` | 构造协议消息 |
| `remove_websocket_connection()` | `removeWebSocketConnection()` | 移除连接 |
| `cleanup()` | `cleanup()` | 清理资源 |

### 结构体字段对应

| Python版本 | Go版本 | 说明 |
|------------|--------|------|
| `self.websocket_connection` | `websocketConnection` | WebSocket连接 |
| `self.last_message_time` | `lastMessageTime` | 最后消息时间 |
| `self.chat_stream` | `chatStream` | 聊天流 |

## 核心功能

### 1. WebSocket连接管理
- 处理WebSocket连接升级
- 管理多个并发连接
- 自动清理断开的连接

### 2. 消息处理流程
参考Python版本的`_message_processing_loop`实现：

```go
// 主要消息处理循环
func (a *AuraAgent) handleBinaryMessage(conn *Connection, messageData []byte) error {
    // 1. 解析二进制消息
    binaryMsg, err := protocol.ParseBinaryMessage(messageData)
    
    // 2. 检查特殊事件（如FinishSession）
    if binaryMsg.Event == protocol.ClientEventFinishSession {
        // 处理session结束
        return nil
    }
    
    // 3. 转换为Message格式
    msg := &protocol.Message{
        Event:     fmt.Sprintf("%d", binaryMsg.Event),
        SessionID: binaryMsg.SessionID,
        ChatID:    conn.chatID,
        UserID:    conn.userID,
        Payload:   binaryMsg.Payload,
    }
    
    // 4. 调用MessageProcessor处理消息 (与Python版本保持一致)
    result, err := a.msgProcessor.HandleMessage(msg)
    
    return nil
}
```

### 3. 会话生命周期管理

#### 连接开始
```go
func (a *AuraAgent) handleStartConnection(conn *Connection, msg *protocol.BinaryMessage) error {
    // 发送连接确认
    response, err := protocol.GenerateBinaryResponse(
        protocol.ServerEventConnectionStarted,
        "",
        map[string]string{"status": "connected"},
        protocol.SERVER_ACK,
    )
    // 发送响应...
}
```

#### 会话开始
```go
func (a *AuraAgent) handleStartSession(conn *Connection, msg *protocol.BinaryMessage) error {
    // 1. 解析会话信息
    // 2. 设置连接信息
    // 3. 创建聊天会话
    // 4. 启动MessageProcessor (关键步骤)
    if err := a.msgProcessor.Start(conn.chatID, conn.userID, a.createSendCallback(conn)); err != nil {
        return err
    }
    // 5. 发送会话确认
}
```

#### 会话结束
```go
func (a *AuraAgent) handleFinishConnection(conn *Connection, msg *protocol.BinaryMessage) error {
    // 停止MessageProcessor
    a.msgProcessor.Stop()
    // 发送连接结束确认
}
```

## 关键修复

### 问题
Go版本的`handleBinaryMessage`方法没有调用`MessageProcessor.HandleMessage`，与Python版本不一致。

### 解决方案
1. **统一消息处理**: 所有消息都通过`MessageProcessor.HandleMessage`处理
2. **实现发送回调**: 创建`createSendCallback`方法，将MessageProcessor输出转换为二进制格式
3. **事件类型转换**: 实现`parseEventString`方法，将字符串事件转换为数字事件ID

### 与Python版本的对比

| 功能 | Python版本 | Go版本 |
|------|-------------|--------|
| 消息处理循环 | `_message_processing_loop` | `handleBinaryMessage` |
| MessageProcessor调用 | `MessageProcessor.get_instance().handle_message(message_data)` | `a.msgProcessor.HandleMessage(msg)` |
| 发送回调 | `self.send_websocket_message` | `a.createSendCallback(conn)` |
| 协议格式 | 二进制协议 | 二进制协议 |

## 消息流

```
客户端 → WebSocket → AuraAgent.handleBinaryMessage → MessageProcessor.HandleMessage → 工作器 → 输出回调 → 客户端
```

## 支持的事件类型

### 客户端事件
- `ClientEventStartConnection` (1): 开始连接
- `ClientEventStartSession` (100): 开始会话
- `ClientEventTaskRequest` (200): 任务请求
- `ClientEventSpeakEnded` (600): 说话结束
- `ClientEventFinishSession` (102): 结束会话
- `ClientEventFinishConnection` (2): 结束连接

### 服务器事件
- `ServerEventConnectionStarted` (50): 连接已开始
- `ServerEventSessionStarted` (150): 会话已开始
- `ServerEventSessionFinished` (152): 会话已结束
- `ServerEventConnectionFinished` (52): 连接已结束
- `ServerEventASREnded` (459): ASR结束
- `ServerEventTTSResponse` (352): TTS响应
- `ServerEventChatResponse` (550): 聊天响应

## 使用示例

```go
// 创建AuraAgent实例
agent := NewAuraAgent(chatManager, msgProcessor)

// 处理WebSocket连接
http.HandleFunc("/ws", agent.HandleWebSocket)

// 启动服务器
http.ListenAndServe(":8080", nil)
```

## 注意事项

1. **线程安全**: 使用互斥锁保护连接映射
2. **资源清理**: 连接断开时自动清理资源
3. **错误处理**: 完善的错误处理和日志记录
4. **协议兼容**: 完全兼容二进制协议格式
5. **性能优化**: 使用goroutines处理并发连接

## 测试

```bash
# 编译测试
go build ./internal/agent

# 运行测试
go test ./internal/agent -v
```

## 扩展性

该架构支持：
- 添加新的事件类型处理
- 自定义消息处理逻辑
- 集成外部服务
- 扩展协议支持
