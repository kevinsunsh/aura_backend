# PostgreSQL Checkpointer 使用说明

## 概述

本项目已成功将LangGraph的checkpointer从RedisSaver替换为PostgresSaver，使用PostgreSQL数据库来存储LangGraph的状态检查点。

## 主要变更

### 1. 配置变更

在 `app/config.py` 中添加了PostgreSQL配置：

```python
# PostgreSQL 配置 (用于LangGraph checkpoint)
POSTGRES_HOST: str = "sh-postgres-c93lya14.sql.tencentcdb.com"
POSTGRES_PORT: int = 25561
POSTGRES_DB: str = "aura-PostgreSQL"
POSTGRES_USER: str = "root"
POSTGRES_PASSWORD: str = "X1KxZeMkM#nobqKiq"
POSTGRES_SCHEMA: str = "public"
```

### 2. 代码变更

#### AuraAgent类 (`app/agents/aura.py`)

- 删除了所有callback相关的逻辑
- 将RedisSaver替换为PostgresSaver
- 修改了chat方法，现在直接返回响应内容
- 添加了chat_with_stream方法，返回所有响应内容

#### API接口 (`app/app.py`)

- 删除了callback逻辑
- 修改了WebSocket端点，直接返回响应内容
- 添加了新的HTTP接口：
  - `POST /chat` - 普通聊天接口
  - `POST /chat/stream` - 流式聊天接口
- 添加了新的WebSocket端点：
  - `/ws/{user_id}` - 普通聊天WebSocket
  - `/ws/stream/{user_id}` - 流式聊天WebSocket

## 接口说明

### HTTP接口

#### 1. 普通聊天接口
```bash
POST /chat
Content-Type: application/json

{
    "user_id": "your_user_id"
}
```

响应：
```json
{
    "user_id": "your_user_id",
    "response": "AI的响应内容",
    "status": "success"
}
```

#### 2. 流式聊天接口
```bash
POST /chat/stream
Content-Type: application/json

{
    "user_id": "your_user_id"
}
```

响应：
```json
{
    "user_id": "your_user_id",
    "responses": ["响应片段1", "响应片段2", ...],
    "full_response": "完整响应内容",
    "status": "success"
}
```

### WebSocket接口

#### 1. 普通聊天WebSocket
```javascript
const ws = new WebSocket('ws://localhost:5876/ws/your_user_id');

// 发送消息
ws.send(JSON.stringify({
    "message": "用户消息"
}));

// 接收响应
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    switch(data.type) {
        case 'start':
            console.log('开始处理');
            break;
        case 'response':
            console.log('AI响应:', data.message);
            break;
        case 'end':
            console.log('处理完成');
            break;
        case 'error':
            console.error('错误:', data.message);
            break;
    }
};
```

#### 2. 流式聊天WebSocket
```javascript
const ws = new WebSocket('ws://localhost:5876/ws/stream/your_user_id');

// 发送消息
ws.send(JSON.stringify({
    "message": "用户消息"
}));

// 接收响应
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    switch(data.type) {
        case 'start':
            console.log('开始处理');
            break;
        case 'full_response':
            console.log('完整响应:', data.message);
            break;
        case 'stream_segment':
            console.log(`片段${data.segment_index}:`, data.message);
            break;
        case 'end':
            console.log('处理完成');
            break;
        case 'error':
            console.error('错误:', data.message);
            break;
    }
};
```

## 数据库初始化

运行数据库初始化脚本：

```bash
cd app
python scripts/init_postgres.py
```

这个脚本会：
1. 连接到PostgreSQL服务器
2. 创建数据库（如果不存在）
3. 创建schema（如果不存在）
4. PostgresSaver会自动创建所需的表结构

## 环境变量配置

确保在 `.env` 文件中配置了正确的PostgreSQL连接信息：

```env
# PostgreSQL 配置 (用于LangGraph checkpoint)
POSTGRES_HOST=sh-postgres-c93lya14.sql.tencentcdb.com
POSTGRES_PORT=25561
POSTGRES_DB=aura-PostgreSQL
POSTGRES_USER=root
POSTGRES_PASSWORD=X1KxZeMkM#nobqKiq
POSTGRES_SCHEMA=public

# 服务器配置
SERVER_PORT=5876
```

## 优势

1. **持久化存储**: PostgreSQL提供更好的数据持久化
2. **事务支持**: 支持ACID事务
3. **更好的查询能力**: 可以使用SQL查询历史数据
4. **扩展性**: 更容易进行数据备份和恢复
5. **并发支持**: 更好的并发处理能力

## 注意事项

1. 确保PostgreSQL服务器正在运行且可访问
2. 确保数据库用户有足够的权限创建表和schema
3. 首次运行时会自动创建所需的表结构
4. 如果遇到连接问题，请检查网络连接和防火墙设置 