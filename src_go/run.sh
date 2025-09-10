#!/bin/bash

# 设置错误时退出
set -e

echo "启动 Aura Backend Go 版本..."

# 检查配置文件
if [ ! -f ".env" ]; then
    echo "警告: 未找到 .env 配置文件，将使用环境变量"
fi

# 检查Go版本
if ! command -v go &> /dev/null; then
    echo "错误: 未找到Go命令，请先安装Go"
    exit 1
fi

# 下载依赖
echo "检查并下载依赖..."
go mod download
go mod verify

# 设置环境变量（如果没有设置）
export LOG_LEVEL=${LOG_LEVEL:-"info"}
export SERVER_HOST=${SERVER_HOST:-"0.0.0.0"}
export SERVER_PORT=${SERVER_PORT:-"5876"}

echo "环境配置:"
echo "  LOG_LEVEL: $LOG_LEVEL"
echo "  SERVER_HOST: $SERVER_HOST"
echo "  SERVER_PORT: $SERVER_PORT"

# 运行应用
echo "启动应用..."
go run main.go
