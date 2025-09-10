# 🐛 VS Code Go调试问题解决方案

## ❌ 问题描述
```
Unhandled error in debug adapter: TypeError [ERR_INVALID_ARG_VALUE]: The argument 'file' cannot be empty. Received ''
```

## 🔍 问题分析
这个错误通常是由于以下原因造成的：
1. VS Code无法正确识别Go模块路径
2. 调试配置中的路径解析问题
3. Go扩展配置不正确

## 🛠️ 解决方案

### 方案1: 使用最小化调试配置（推荐）

我已经创建了一个最小化的调试配置：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug",
            "type": "go",
            "request": "launch",
            "mode": "auto",
            "program": "."
        }
    ]
}
```

**使用方法：**
1. 在VS Code中按 `F5`
2. 选择 `Debug` 配置
3. 在代码中设置断点

### 方案2: 手动编译后调试

如果VS Code调试器仍有问题，可以：

```bash
# 1. 编译项目
go build -o aura-backend .

# 2. 设置环境变量
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug

# 3. 运行程序
./aura-backend
```

### 方案3: 使用go run直接运行

```bash
# 设置环境变量
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug

# 直接运行
go run main.go
```

## 🔧 调试技巧

### 1. 设置断点
在以下关键位置设置断点：
- `main.go:34` - goroutine启动
- `main.go:40` - 信号等待
- `server.go` - 服务器启动
- `aura_agent.go` - WebSocket处理

### 2. 使用日志调试
```go
logger.Log.Debugf("调试信息: %+v", variable)
```

### 3. 检查环境变量
```bash
echo "SKIP_DATABASE: $SKIP_DATABASE"
echo "LOG_LEVEL: $LOG_LEVEL"
echo "GIN_MODE: $GIN_MODE"
```

## 🎯 推荐的调试流程

1. **启动调试**：按 `F5` 选择 `Debug` 配置
2. **设置断点**：在关键代码行点击行号左侧
3. **运行程序**：程序会在断点处停止
4. **查看变量**：鼠标悬停在变量上查看值
5. **单步执行**：使用F10（单步跳过）或F11（单步进入）

## 🚨 如果仍有问题

1. **重启VS Code**
2. **重新安装Go扩展**
3. **检查Go环境**：`go version`, `go env`
4. **使用命令行运行**：`go run main.go`

## 📚 相关资源

- [VS Code Go调试指南](https://github.com/golang/vscode-go/blob/master/docs/debugging.md)
- [Go调试最佳实践](https://golang.org/doc/gdb)

## 🎉 开始调试

现在尝试在VS Code中按 `F5` 启动调试。如果仍有问题，使用方案2或方案3进行调试。


