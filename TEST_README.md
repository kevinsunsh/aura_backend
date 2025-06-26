# Streaming聊天功能测试说明

## 概述

本文档提供了测试streaming聊天功能的详细说明，包括HTTP和WebSocket两种方式的测试。

## 测试脚本

### 1. 完整测试脚本 (`test_streaming_chat.py`)

这是最全面的测试脚本，包含所有功能的测试：

```bash
python test_streaming_chat.py
```

**测试内容：**
- 健康检查接口
- HTTP普通聊天接口
- HTTP流式聊天接口
- WebSocket普通聊天
- WebSocket流式聊天

### 2. 简化测试脚本 (`test_simple_chat.py`)

快速测试HTTP接口的简化版本：

```bash
python test_simple_chat.py
```

**测试内容：**
- 健康检查
- HTTP普通聊天
- HTTP流式聊天

### 3. WebSocket测试脚本 (`test_websocket_chat.py`)

专门测试WebSocket功能的脚本：

```bash
python test_websocket_chat.py
```

**测试内容：**
- WebSocket普通聊天
- WebSocket流式聊天
- WebSocket错误处理

## 运行测试前的准备

### 1. 安装依赖

确保已安装测试所需的依赖：

```bash
cd app
pip install -r requirements.txt
```

主要依赖包括：
- `aiohttp==3.11.16` - HTTP客户端
- `websockets==13.0` - WebSocket客户端

### 2. 启动服务

确保Aura Agent服务正在运行：

```bash
cd app
python app.py
```

服务将在 `http://localhost:5876` 启动。

### 3. 检查数据库连接

确保PostgreSQL数据库连接正常：

```bash
cd app
python scripts/init_postgres.py
```

## 测试用例说明

### HTTP接口测试

#### 1. 普通聊天接口 (`POST /chat`)

**请求：**
```json
{
    "user_id": "test_user_001"
}
```

**预期响应：**
```json
{
    "user_id": "test_user_001",
    "response": "AI的响应内容",
    "status": "success"
}
```

#### 2. 流式聊天接口 (`POST /chat/stream`)

**请求：**
```json
{
    "user_id": "test_user_001"
}
```

**预期响应：**
```json
{
    "user_id": "test_user_001",
    "responses": ["响应片段1", "响应片段2", ...],
    "full_response": "完整响应内容",
    "status": "success"
}
```

### WebSocket接口测试

#### 1. 普通聊天WebSocket (`/ws/{user_id}`)

**连接：**
```javascript
const ws = new WebSocket('ws://localhost:5876/ws/test_user_001');
```

**发送消息：**
```json
{
    "message": "你好，请介绍一下你自己"
}
```

**接收消息类型：**
- `start` - 开始处理
- `response` - AI响应
- `end` - 处理完成
- `error` - 错误信息

#### 2. 流式聊天WebSocket (`/ws/stream/{user_id}`)

**连接：**
```javascript
const ws = new WebSocket('ws://localhost:5876/ws/stream/test_user_001');
```

**发送消息：**
```json
{
    "message": "请详细介绍一下人工智能的发展历史"
}
```

**接收消息类型：**
- `start` - 开始处理
- `full_response` - 完整响应
- `stream_segment` - 流式片段
- `end` - 处理完成
- `error` - 错误信息

## 测试结果解读

### 成功指标

1. **HTTP接口测试成功：**
   - 响应状态码为200
   - 响应JSON中status字段为"success"
   - 响应时间在合理范围内（通常<30秒）

2. **WebSocket接口测试成功：**
   - 能够成功建立WebSocket连接
   - 能够发送消息并收到响应
   - 收到正确的消息类型序列

3. **流式响应测试成功：**
   - 能够收到多个响应片段
   - 完整响应内容不为空
   - 响应片段能够正确拼接

### 常见问题排查

#### 1. 连接失败

**可能原因：**
- 服务未启动
- 端口被占用
- 防火墙阻止

**解决方法：**
```bash
# 检查服务状态
curl http://localhost:5876/health

# 检查端口占用
netstat -an | grep 5876
```

#### 2. 数据库连接失败

**可能原因：**
- PostgreSQL服务未启动
- 连接信息错误
- 网络连接问题

**解决方法：**
```bash
# 测试数据库连接
cd app
python scripts/init_postgres.py
```

#### 3. 响应超时

**可能原因：**
- AI模型响应慢
- 网络延迟
- 系统负载高

**解决方法：**
- 增加超时时间
- 检查AI模型配置
- 监控系统资源

## 性能测试

### 响应时间基准

- **健康检查：** < 1秒
- **普通聊天：** < 30秒
- **流式聊天：** < 60秒

### 并发测试

可以使用以下命令进行简单的并发测试：

```bash
# 使用ab进行HTTP并发测试
ab -n 10 -c 5 -p test_data.json -T application/json http://localhost:5876/chat
```

## 日志分析

测试过程中会输出详细的日志信息，包括：

- 请求和响应时间
- 响应状态和内容
- 错误信息和异常堆栈
- WebSocket连接状态

这些信息有助于诊断问题和优化性能。

## 自动化测试

可以将这些测试脚本集成到CI/CD流程中：

```bash
# 在CI/CD中运行测试
python test_simple_chat.py
if [ $? -eq 0 ]; then
    echo "测试通过"
else
    echo "测试失败"
    exit 1
fi
``` 