#!/bin/bash

echo "🚀 启动Aura Backend调试模式..."

# 设置调试环境变量
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug

# 编译项目
echo "📦 编译项目..."
go build -o aura-backend .

if [ $? -eq 0 ]; then
    echo "✅ 编译成功！"
    echo "🔍 启动调试模式..."
    echo "💡 提示：在VS Code中按F5或使用调试面板启动调试"
    echo "🌐 服务将在 http://localhost:5876 启动"
    echo "📊 健康检查: http://localhost:5876/health"
    echo "🔌 WebSocket: ws://localhost:5876/ws/stream"
    echo ""
    echo "按Ctrl+C停止服务"
    
    # 启动服务
    ./aura-backend
else
    echo "❌ 编译失败！"
    exit 1
fi


