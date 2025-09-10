# 多线程消息处理器 (MessageProcessor)

## 概述

本模块实现了一个基于Go goroutines的多线程消息处理器，参考了Python版本的`message_processor.py`的多进程架构，使用Go的并发特性来实现高性能的消息处理。

## 架构设计

### 核心组件

1. **MessageProcessor**: 主消息处理器，负责协调各个工作器
2. **Worker Goroutines**: 各种专门的工作线程
   - VAD Worker: 语音活动检测
   - ~~ASR Worker: 自动语音识别~~ (已注释，与Python版本保持一致)
   - LLM Worker: 大语言模型处理
   - TTS Worker: 文本转语音
   - E2E Worker: 端到端处理
   - PrePost Worker: 预处理和后处理
   - Output Worker: 输出消息处理

### 消息流

```
音频输入 → VAD → ~~ASR~~ → 预处理 → LLM → TTS → 输出
                ↓
              E2E (并行处理)
```

## 主要特性

### 1. 多线程并发处理
- 使用Go的goroutines实现轻量级线程
- 每个工作器运行在独立的goroutine中
- 支持并发处理多个消息流

### 2. 通道通信
- 使用Go channels替代Python的multiprocessing.Queue
- 类型安全的消息传递
- 非阻塞的异步通信

### 3. 状态管理
- 线程安全的状态管理
- 原子操作保证数据一致性
- 实时状态监控

### 4. 优雅关闭
- 使用context.Context进行生命周期管理
- 支持优雅关闭所有工作器
- 资源清理和内存管理

## API接口

### 基本操作

```go
// 获取单例实例
mp := GetMessageProcessor()

// 启动处理器
err := mp.Start(chatID, userID, sendCallback)

// 处理消息
result, err := mp.HandleMessage(msg)
if err != nil {
    log.Fatal(err)
}
if result["success"].(bool) {
    log.Printf("处理成功: %v", result)
}

// 停止处理器
mp.Stop()

// 清理资源
err := mp.Cleanup()
```

### 工作器管理

```go
// 启动所有工作器
err := mp.StartAllWorkers(chatID, userID)

// 停止所有工作器
mp.StopAllWorkers()

// 获取统计信息
stats := mp.GetStats()
```

### 消息类型支持

- `ClientEventSayHello` (300): 问候消息
- `ClientEventTaskRequest` (200): 任务请求
- `ClientEventSpeakEnded` (600): 说话结束
- `ClientEventWorldInfoActivateKeys` (400): 世界信息激活键
- `ClientEventChangeBotID` (401): 机器人ID变更
- `ClientEventChangeSystemPreset` (402): 系统预设变更

### 返回值格式

所有消息处理方法都返回与Python版本一致的格式：

```go
// 成功时
{
    "success": true,
    "action": "audio_task_started",
    "chat_id": "chat_001"
}

// 失败时
{
    "success": false,
    "error": "error message"
}
```

## 与Python版本的对比

| 特性 | Python版本 | Go版本 |
|------|-------------|--------|
| 并发模型 | 多进程 | 多线程(goroutines) |
| 通信方式 | multiprocessing.Queue | channels |
| 内存使用 | 较高(进程隔离) | 较低(共享内存) |
| 启动速度 | 较慢 | 较快 |
| 资源管理 | 进程管理 | 轻量级线程 |
| 错误处理 | 进程崩溃 | 优雅降级 |

## 性能优势

1. **更低的内存占用**: goroutines比进程更轻量
2. **更快的启动时间**: 线程创建比进程创建快
3. **更好的资源利用**: 共享内存空间
4. **更简单的错误处理**: 统一的错误处理机制

## 使用示例

```go
package main

import (
    "aura-backend/internal/message"
    "aura-backend/internal/protocol"
    "log"
)

func main() {
    // 获取消息处理器
    mp := message.GetMessageProcessor()
    
    // 定义发送回调
    sendCallback := func(msg interface{}) error {
        log.Printf("发送消息: %v", msg)
        return nil
    }
    
    // 启动处理器
    err := mp.Start("chat_001", "user_001", sendCallback)
    if err != nil {
        log.Fatal(err)
    }
    
    // 启动工作器
    err = mp.StartAllWorkers("chat_001", "user_001")
    if err != nil {
        log.Fatal(err)
    }
    
    // 处理消息
    msg := &protocol.Message{
        Event:   "300",
        ChatID:  "chat_001",
        UserID:  "user_001",
        Payload: map[string]interface{}{"content": "你好"},
    }
    
    result, err := mp.HandleMessage(msg)
    if err != nil {
        log.Fatal(err)
    }
    if result["success"].(bool) {
        log.Printf("消息处理成功: %v", result)
    }
    
    // 清理资源
    defer mp.Cleanup()
}
```

## 测试

运行测试：

```bash
go test ./internal/message -v
```

测试包括：
- 多线程消息处理测试
- 工作器状态测试
- 消息通道测试

## 注意事项

1. **线程安全**: 所有共享状态都使用适当的同步机制
2. **资源清理**: 确保调用Cleanup()方法释放资源
3. **错误处理**: 妥善处理工作器启动失败的情况
4. **性能监控**: 使用GetStats()监控系统状态

## 扩展性

该架构支持：
- 添加新的工作器类型
- 自定义消息处理器
- 动态调整工作器数量
- 集成外部AI服务
