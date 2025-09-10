# 从 Python 版本迁移到 Go 版本

本文档将帮助您从原有的 Python 版本 Aura Backend 迁移到新的 Go 版本。

## 迁移概述

Go 版本提供了与 Python 版本相同的功能，但具有更好的性能和并发处理能力。迁移过程包括：

1. 环境准备
2. 配置迁移
3. 数据迁移
4. 服务切换
5. 验证测试

## 环境准备

### 1. 安装 Go

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install golang-go

# CentOS/RHEL
sudo yum install golang

# macOS
brew install go

# 验证安装
go version
```

### 2. 安装 PostgreSQL（如果还没有）

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib

# CentOS/RHEL
sudo yum install postgresql postgresql-server

# 启动服务
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## 配置迁移

### 1. 复制配置文件

```bash
# 从 Python 版本复制环境配置
cp ../.env .env

# 或者使用示例配置
cp env.example .env
```

### 2. 更新配置

编辑 `.env` 文件，确保以下配置正确：

```env
# 数据库配置（使用与 Python 版本相同的数据库）
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_DBNAME=aura-PostgreSQL
DATABASE_USER=root
DATABASE_PASSWORD=X1KxZeMkM#nobqKiq

# OpenAI 配置
OPENAI_API_KEY=your_actual_api_key
OPENAI_BASE_URL=https://api.openai.com

# 服务器配置
SERVER_PORT=5876
```

## 数据迁移

### 1. 数据库结构迁移

Go 版本会自动创建必要的数据库表结构。如果您的 Python 版本有自定义表，请确保在 `internal/database/database.go` 中添加相应的模型。

### 2. 现有数据保留

Go 版本会连接到相同的数据库，因此现有的聊天记录和用户数据将被保留。

## 服务切换

### 1. 停止 Python 服务

```bash
# 如果使用 systemd
sudo systemctl stop aura-backend

# 如果使用 Docker
docker stop aura-backend

# 如果直接运行
pkill -f "python.*app.py"
```

### 2. 启动 Go 服务

```bash
# 开发模式
./run.sh

# 生产模式
./build.sh
cd build
./aura-backend

# 使用 Docker
docker-compose up -d
```

### 3. 验证服务状态

```bash
# 检查服务状态
curl http://localhost:5876/health

# 检查统计信息
curl http://localhost:5876/v1/stats
```

## 功能对比

| 功能 | Python 版本 | Go 版本 | 状态 |
|------|-------------|---------|------|
| WebSocket 连接 | ✅ | ✅ | 完全兼容 |
| 文本消息处理 | ✅ | ✅ | 完全兼容 |
| 音频消息处理 | ✅ | ✅ | 完全兼容 |
| AI 对话 | ✅ | ✅ | 完全兼容 |
| 数据库存储 | ✅ | ✅ | 完全兼容 |
| 健康检查 | ✅ | ✅ | 完全兼容 |
| 日志记录 | ✅ | ✅ | 完全兼容 |
| Docker 支持 | ✅ | ✅ | 完全兼容 |
| 性能 | 中等 | 高 | 显著提升 |
| 内存使用 | 中等 | 低 | 显著改善 |
| 并发处理 | 中等 | 高 | 显著提升 |

## 性能提升

### 1. 并发处理能力

- **Python 版本**: 受 GIL 限制，并发性能有限
- **Go 版本**: 原生支持 goroutine，可处理数万并发连接

### 2. 内存使用

- **Python 版本**: 相对较高的内存占用
- **Go 版本**: 更低的内存占用，更好的垃圾回收

### 3. 响应时间

- **Python 版本**: 毫秒级响应
- **Go 版本**: 微秒级响应

## 兼容性说明

### 1. API 兼容性

Go 版本完全兼容 Python 版本的 API 接口，包括：

- HTTP 端点
- WebSocket 协议
- 消息格式
- 响应结构

### 2. 客户端兼容性

现有的客户端代码无需修改，可以直接连接到 Go 版本的服务。

### 3. 数据库兼容性

使用相同的数据库结构和连接参数，确保数据一致性。

## 回滚计划

如果迁移过程中遇到问题，可以快速回滚到 Python 版本：

### 1. 停止 Go 服务

```bash
# 如果使用 Docker
docker-compose down

# 如果直接运行
pkill -f "aura-backend"
```

### 2. 恢复 Python 服务

```bash
# 启动 Python 服务
cd ..
python src/app.py

# 或者使用 Docker
docker-compose up -d
```

## 迁移检查清单

- [ ] Go 环境已安装并配置
- [ ] PostgreSQL 服务正在运行
- [ ] 环境配置文件已更新
- [ ] Python 服务已停止
- [ ] Go 服务已启动
- [ ] 健康检查通过
- [ ] WebSocket 连接测试通过
- [ ] 消息处理测试通过
- [ ] 数据库连接测试通过
- [ ] 性能测试通过

## 常见问题

### 1. 端口冲突

如果端口 5876 被占用：

```bash
# 查找占用进程
lsof -i :5876

# 终止进程
kill -9 <PID>
```

### 2. 数据库连接失败

检查数据库配置：

```bash
# 测试数据库连接
psql -h localhost -U root -d aura-PostgreSQL
```

### 3. 权限问题

确保脚本有执行权限：

```bash
chmod +x build.sh run.sh
```

## 支持

如果在迁移过程中遇到问题，请：

1. 查看日志文件 `logs/main.log`
2. 检查服务状态
3. 提交 Issue 到项目仓库
4. 联系开发团队

## 总结

Go 版本提供了显著的性能提升和更好的资源利用率，同时保持了与 Python 版本的完全兼容性。迁移过程简单直接，风险较低。建议在生产环境部署前先在测试环境进行充分测试。
