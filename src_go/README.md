# Aura Backend - Go 版本

这是 Aura Backend 项目的 Go 语言重构版本，提供了与原 Python 版本相同的功能，但具有更好的性能和并发处理能力。

## 功能特性

- 🚀 **高性能**: 基于 Go 的并发模型，支持高并发 WebSocket 连接
- 🔌 **WebSocket 支持**: 实时双向通信，支持文本和音频消息
- 🤖 **AI 集成**: 集成 OpenAI API，支持智能对话
- 🎵 **音频处理**: 支持音频输入和输出
- 💾 **数据持久化**: 使用 PostgreSQL 数据库存储聊天记录
- 📊 **实时监控**: 提供详细的统计信息和健康检查
- 🐳 **容器化**: 支持 Docker 部署
- 🔒 **安全**: 支持 CORS 和身份验证

## 系统要求

- Go 1.21 或更高版本
- PostgreSQL 12 或更高版本
- 至少 512MB 内存
- 至少 1GB 磁盘空间

## 快速开始

### 1. 克隆项目

```bash
git clone <repository-url>
cd aura_backend/src_go
```

### 2. 安装依赖

```bash
go mod download
```

### 3. 配置环境变量

创建 `.env` 文件：

```env
# 服务器配置
SERVER_HOST=0.0.0.0
SERVER_PORT=5876

# 数据库配置
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_DBNAME=aura_postgresql
DATABASE_USER=root
DATABASE_PASSWORD=your_password
DATABASE_SSLMODE=disable

# OpenAI 配置
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com
OPENAI_MODEL=gpt-3.5-turbo

# 应用配置
APP_DEBUG=true
APP_VERSION=1.0.0
LOG_LEVEL=info
```

### 4. 运行应用

#### 开发模式
```bash
chmod +x run.sh
./run.sh
```

#### 生产模式
```bash
chmod +x build.sh
./build.sh
cd build
./aura-backend
```

### 5. 使用 Docker

```bash
# 构建镜像
docker build -t aura-backend-go .

# 运行容器
docker run -p 5876:5876 --env-file .env aura-backend-go
```

#### 使用 Docker Compose

```bash
docker-compose up -d
```

## API 端点

### HTTP 端点

- `GET /` - 状态检查
- `GET /health` - 健康检查
- `GET /v1/ping` - 心跳检测
- `GET /v1/stats` - 统计信息
- `GET /v1/chat/streams` - 聊天流列表

### WebSocket 端点

- `GET /ws/stream` - 流式聊天（支持 TTS）
- `GET /ws/stream/without_tts` - 流式聊天（不支持 TTS）

### SSE 端点

- `GET /sse` - 服务器发送事件

## 项目结构

```
src_go/
├── main.go                 # 主程序入口
├── go.mod                 # Go 模块文件
├── go.sum                 # 依赖校验文件
├── Dockerfile             # Docker 镜像构建文件
├── docker-compose.yml     # Docker Compose 配置
├── build.sh               # 构建脚本
├── run.sh                 # 运行脚本
├── README.md              # 项目文档
└── internal/              # 内部包
    ├── agent/             # 代理模块
    ├── ai/                # AI 客户端
    ├── chat/              # 聊天流管理
    ├── config/            # 配置管理
    ├── database/          # 数据库连接
    ├── logger/            # 日志管理
    ├── message/           # 消息处理
    ├── models/            # 数据模型
    ├── protocol/          # 协议定义
    └── server/            # HTTP 服务器
```

## 配置说明

### 环境变量

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| `SERVER_HOST` | 服务器监听地址 | `0.0.0.0` |
| `SERVER_PORT` | 服务器监听端口 | `5876` |
| `LOG_LEVEL` | 日志级别 | `info` |
| `DATABASE_HOST` | 数据库主机 | `localhost` |
| `DATABASE_PORT` | 数据库端口 | `5432` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 必需 |
| `OPENAI_BASE_URL` | OpenAI API 基础 URL | 必需 |

### 日志级别

- `debug`: 调试信息
- `info`: 一般信息
- `warn`: 警告信息
- `error`: 错误信息
- `fatal`: 致命错误

## 开发指南

### 添加新的消息处理器

```go
// 在 message_processor.go 中注册新的处理器
mp.RegisterHandler("custom_event", func(message interface{}) error {
    // 处理自定义事件
    return nil
})
```

### 添加新的 API 端点

```go
// 在 server.go 中添加新的路由
func (server *Server) setupRoutes() {
    // ... 现有路由
    server.router.GET("/v1/custom", server.customHandler)
}
```

### 数据库迁移

```go
// 在 database.go 中添加新的模型
func (db *Database) autoMigrate() error {
    return db.DB.AutoMigrate(&User{}, &ChatSession{}, &ChatMessage{}, &NewModel{})
}
```

## 性能优化

### 并发处理

- 使用 Go 的 goroutine 处理并发请求
- 实现连接池管理数据库连接
- 使用 sync.Pool 减少内存分配

### 内存管理

- 及时释放不需要的资源
- 使用对象池减少 GC 压力
- 实现优雅关闭机制

## 监控和调试

### 健康检查

```bash
curl http://localhost:5876/health
```

### 统计信息

```bash
curl http://localhost:5876/v1/stats
```

### 日志查看

```bash
tail -f logs/main.log
```

## 故障排除

### 常见问题

1. **端口被占用**
   ```bash
   lsof -i :5876
   kill -9 <PID>
   ```

2. **数据库连接失败**
   - 检查数据库服务是否运行
   - 验证连接参数是否正确
   - 检查防火墙设置

3. **WebSocket 连接失败**
   - 检查客户端实现
   - 验证协议格式
   - 查看服务器日志

### 调试模式

设置环境变量 `APP_DEBUG=true` 启用调试模式，将显示详细的日志信息。

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 许可证

本项目采用 MIT 许可证。

## 联系方式

如有问题或建议，请提交 Issue 或联系开发团队。
