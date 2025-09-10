#!/bin/bash

echo "🚀 启动Aura Backend简单调试模式..."

# 设置调试环境变量
export SKIP_DATABASE=true
export LOG_LEVEL=debug
export GIN_MODE=debug

echo "🔍 环境变量设置完成："
echo "   SKIP_DATABASE=$SKIP_DATABASE"
echo "   LOG_LEVEL=$LOG_LEVEL"
echo "   GIN_MODE=$GIN_MODE"
echo ""

echo "📦 使用 go run 启动调试模式..."
echo "💡 提示：在VS Code中按F5或使用调试面板启动调试"
echo "🌐 服务将在 http://localhost:5876 启动"
echo "📊 健康检查: http://localhost:5876/health"
echo "🔌 WebSocket: ws://localhost:5876/ws/stream"
echo ""
echo "按Ctrl+C停止服务"

# 直接使用 go run 启动
go run main.go


