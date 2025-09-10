#!/bin/bash

echo "🔧 准备VS Code调试环境..."

# 设置环境变量
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug

echo "✅ 环境变量设置完成："
echo "   SKIP_DATABASE=$SKIP_DATABASE"
echo "   LOG_LEVEL=$LOG_LEVEL"
echo "   GIN_MODE=$GIN_MODE"
echo ""

echo "📦 编译项目..."
go build -o aura-backend .

if [ $? -eq 0 ]; then
    echo "✅ 编译成功！"
    echo ""
    echo "🎯 现在您可以："
    echo "1. 在VS Code中按 F5 启动调试"
    echo "2. 选择 'Launch Package' 配置"
    echo "3. 在代码中设置断点"
    echo ""
    echo "🌐 服务将在 http://localhost:5876 启动"
    echo "📊 健康检查: http://localhost:5876/health"
    echo "🔌 WebSocket: ws://localhost:5876/ws/stream"
    echo ""
    echo "💡 提示：如果调试器仍有问题，可以直接运行："
    echo "   ./aura-backend"
else
    echo "❌ 编译失败！"
    exit 1
fi


