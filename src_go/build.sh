#!/bin/bash

# 设置错误时退出
set -e

echo "开始构建 Aura Backend Go 版本..."

# 检查Go版本
GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
REQUIRED_VERSION="1.21"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$GO_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "错误: 需要Go版本 $REQUIRED_VERSION 或更高，当前版本: $GO_VERSION"
    exit 1
fi

echo "Go版本检查通过: $GO_VERSION"

# 清理之前的构建
echo "清理之前的构建..."
rm -rf build/
mkdir -p build/

# 下载依赖
echo "下载Go依赖..."
go mod download
go mod verify

# 运行测试
echo "运行测试..."
go test ./...

# 构建应用
echo "构建应用..."
CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o build/aura-backend .

# 检查构建结果
if [ -f "build/aura-backend" ]; then
    echo "构建成功!"
    echo "二进制文件位置: build/aura-backend"
    echo "文件大小: $(du -h build/aura-backend | cut -f1)"
else
    echo "构建失败!"
    exit 1
fi

# 复制配置文件
echo "复制配置文件..."
cp -r internal/ build/
cp go.mod go.sum build/

echo "构建完成!"
echo "运行方式: cd build && ./aura-backend"
