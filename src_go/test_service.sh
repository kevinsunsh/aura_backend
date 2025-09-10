#!/bin/bash

echo "🧪 Aura Backend 服务测试"
echo "========================"

# 检查服务是否运行
echo "1. 检查服务状态..."
if curl -s http://localhost:5876/health > /dev/null 2>&1; then
    echo "   ✅ 服务正在运行"
    echo "   📍 健康检查端点: http://localhost:5876/health"
else
    echo "   ❌ 服务未运行"
    echo "   💡 请先启动服务: ./aura-backend"
    exit 1
fi

echo ""

# 测试各个端点
echo "2. 测试HTTP端点..."

echo "   📊 健康检查..."
if response=$(curl -s http://localhost:5876/health); then
    echo "   ✅ 健康检查通过: $response"
else
    echo "   ❌ 健康检查失败"
fi

echo "   📍 状态检查..."
if response=$(curl -s http://localhost:5876/); then
    echo "   ✅ 状态检查通过: $response"
else
    echo "   ❌ 状态检查失败"
fi

echo "   🏓 心跳检测..."
if response=$(curl -s http://localhost:5876/v1/ping); then
    echo "   ✅ 心跳检测通过: $response"
else
    echo "   ❌ 心跳检测失败"
fi

echo "   📈 统计信息..."
if response=$(curl -s http://localhost:5876/v1/stats); then
    echo "   ✅ 统计信息获取成功: $response"
else
    echo "   ❌ 统计信息获取失败"
fi

echo ""

# 测试WebSocket连接
echo "3. 测试WebSocket连接..."
echo "   🔌 尝试建立WebSocket连接..."

# 使用websocat或类似工具测试WebSocket
if command -v websocat &> /dev/null; then
    echo "   📡 使用websocat测试WebSocket..."
    # 这里可以添加websocat测试命令
else
    echo "   ⚠️  websocat未安装，跳过WebSocket测试"
    echo "   💡 安装websocat: brew install websocat"
    echo "   💡 或使用提供的HTML测试页面: test_websocket.html"
fi

echo ""

# 显示测试结果
echo "🎯 测试完成！"
echo ""
echo "💡 下一步操作:"
echo "   1. 使用浏览器打开 test_websocket.html 测试WebSocket"
echo "   2. 或使用其他WebSocket客户端工具测试"
echo "   3. 查看服务日志了解详细运行状态"
echo ""
echo "🔧 服务端点:"
echo "   - 健康检查: http://localhost:5876/health"
echo "   - 状态检查: http://localhost:5876/"
echo "   - 心跳检测: http://localhost:5876/v1/ping"
echo "   - 统计信息: http://localhost:5876/v1/stats"
echo "   - WebSocket: ws://localhost:5876/ws/stream"
