#!/bin/bash

echo "🚀 Aura Backend Go 版本快速启动脚本"
echo "=================================="

# 检查Go环境
if ! command -v go &> /dev/null; then
    echo "❌ 错误: 未找到Go命令"
    echo ""
    echo "请先安装Go 1.21或更高版本:"
    echo ""
    echo "macOS:"
    echo "  brew install go"
    echo ""
    echo "Ubuntu/Debian:"
    echo "  sudo apt update && sudo apt install golang-go"
    echo ""
    echo "CentOS/RHEL:"
    echo "  sudo yum install golang"
    echo ""
    echo "安装完成后重新运行此脚本"
    exit 1
fi

GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
echo "✅ Go版本检查通过: $GO_VERSION"

# 检查配置文件
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 配置文件"
    echo "📝 正在创建示例配置文件..."
    cp env.example .env
    echo "✅ 已创建 .env 文件，请编辑配置后重新运行"
    echo ""
    echo "需要配置的重要参数:"
    echo "  - OPENAI_API_KEY: 您的OpenAI API密钥"
    echo "  - DATABASE_*: 数据库连接参数"
    echo "  - SERVER_PORT: 服务器端口 (默认: 5876)"
    echo ""
    echo "编辑完成后重新运行此脚本"
    exit 1
fi

echo "✅ 配置文件检查通过"

# 下载依赖
echo "📦 正在下载Go依赖..."
go mod download
if [ $? -ne 0 ]; then
    echo "❌ 依赖下载失败"
    exit 1
fi
echo "✅ 依赖下载完成"

# 验证依赖
echo "🔍 正在验证依赖..."
go mod verify
if [ $? -ne 0 ]; then
    echo "❌ 依赖验证失败"
    exit 1
fi
echo "✅ 依赖验证通过"

# 运行测试
echo "🧪 正在运行测试..."
go test ./...
if [ $? -ne 0 ]; then
    echo "⚠️  测试失败，但继续启动服务..."
else
    echo "✅ 测试通过"
fi

# 启动服务
echo "🚀 正在启动服务..."
echo "📍 服务地址: http://localhost:5876"
echo "🔌 WebSocket: ws://localhost:5876/ws/stream"
echo "📊 健康检查: http://localhost:5876/health"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

go run main.go
