# 🐛 Aura Backend 调试指南

## 🚀 快速开始

### 方法1: 使用VS Code调试器（推荐）

1. **打开VS Code调试面板**
   - 按 `Ctrl+Shift+D` (Windows/Linux) 或 `Cmd+Shift+D` (Mac)
   - 或点击左侧活动栏的调试图标

2. **选择调试配置**
   - 选择 `Debug Aura Backend` 配置
   - 这个配置会自动跳过数据库连接，使用内存模式

3. **启动调试**
   - 按 `F5` 或点击绿色的播放按钮
   - 程序会在断点处停止，您可以：
     - 查看变量值
     - 单步执行
     - 查看调用栈
     - 监控日志输出

### 方法2: 使用调试脚本

```bash
# 在src_go目录下运行
./debug.sh
```

### 方法3: 手动设置环境变量

```bash
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug
go run main.go
```

## 🔧 调试配置说明

### 主要调试配置

- **Debug Aura Backend**: 跳过数据库，使用内存模式
- **Debug with Database**: 连接真实数据库
- **Debug Current File**: 调试当前打开的文件
- **Debug Tests**: 运行并调试所有测试
- **Debug Specific Test**: 调试特定的测试函数

### 环境变量

- `SKIP_DATABASE=true`: 跳过数据库连接，使用内存模式
- `LOG_LEVEL=debug`: 启用详细日志输出
- `GIN_MODE=debug`: 启用Gin框架的调试模式

## 🎯 常用断点位置

### 主要流程断点

1. **main.go**: 程序入口点
2. **server.go**: 服务器启动和路由设置
3. **aura_agent.go**: WebSocket连接处理
4. **binary_protocol.go**: 二进制协议解析
5. **message_processor.go**: 消息处理逻辑

### 关键函数断点

- `main()`: 程序启动
- `NewServer()`: 服务器创建
- `HandleWebSocket()`: WebSocket连接处理
- `handleBinaryMessage()`: 二进制消息处理
- `ParseBinaryMessage()`: 协议解析

## 🔍 调试技巧

### 1. 查看变量值
- 在调试模式下，鼠标悬停在变量上查看值
- 使用调试控制台执行表达式
- 在变量面板中展开复杂结构

### 2. 条件断点
- 右键点击断点，设置条件
- 例如：只在特定sessionID时停止

### 3. 日志输出
- 在代码中添加 `logger.Log.Debugf()` 语句
- 使用 `fmt.Printf()` 进行快速调试

### 4. 网络调试
- 使用 `curl` 测试HTTP端点
- 使用WebSocket客户端测试连接
- 监控网络流量

## 🐛 常见问题

### 1. 调试器无法启动
- 确保Go扩展已安装
- 检查 `go.mod` 文件是否存在
- 验证工作目录设置

### 2. 断点不生效
- 确保代码已编译
- 检查断点是否在正确的行
- 验证调试配置

### 3. 环境变量不生效
- 检查 `.env` 文件格式
- 验证环境变量名称
- 重启调试会话

## 📚 相关资源

- [VS Code Go调试指南](https://github.com/golang/vscode-go/blob/master/docs/debugging.md)
- [Go调试最佳实践](https://golang.org/doc/gdb)
- [Gin框架调试](https://gin-gonic.com/docs/debugging/)

## 🎉 开始调试

现在您可以：
1. 在VS Code中按 `F5` 启动调试
2. 在关键代码行设置断点
3. 使用调试脚本快速启动
4. 监控日志输出和网络请求

祝您调试愉快！🚀


