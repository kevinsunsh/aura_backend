#!/bin/bash

echo "🔍 Aura Backend Go 版本环境检查"
echo "================================"

# 检查Go环境
echo "1. 检查Go环境..."
if command -v go &> /dev/null; then
    GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
    echo "   ✅ Go已安装: $GO_VERSION"
    
    # 检查Go版本
    REQUIRED_VERSION="1.21"
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$GO_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
        echo "   ✅ Go版本满足要求 (>= $REQUIRED_VERSION)"
    else
        echo "   ⚠️  Go版本过低，建议升级到 $REQUIRED_VERSION 或更高"
    fi
else
    echo "   ❌ Go未安装"
    echo "   💡 安装命令:"
    echo "      macOS: brew install go"
    echo "      Ubuntu: sudo apt install golang-go"
    echo "      CentOS: sudo yum install golang"
fi

echo ""

# 检查Go环境变量
echo "2. 检查Go环境变量..."
if [ -n "$GOPATH" ]; then
    echo "   ✅ GOPATH: $GOPATH"
else
    echo "   ⚠️  GOPATH未设置"
fi

if [ -n "$GOROOT" ]; then
    echo "   ✅ GOROOT: $GOROOT"
else
    echo "   ⚠️  GOROOT未设置"
fi

echo ""

# 检查项目依赖
echo "3. 检查项目依赖..."
if [ -f "go.mod" ]; then
    echo "   ✅ go.mod 文件存在"
    
    # 检查依赖
    if [ -d "vendor" ] || [ -f "go.sum" ]; then
        echo "   ✅ 依赖文件存在"
    else
        echo "   ⚠️  依赖未下载，运行: go mod download"
    fi
else
    echo "   ❌ go.mod 文件不存在"
fi

echo ""

# 检查配置文件
echo "4. 检查配置文件..."
if [ -f ".env" ]; then
    echo "   ✅ .env 配置文件存在"
    
    # 检查关键配置
    if grep -q "OPENAI_API_KEY" .env; then
        echo "   ✅ OpenAI API密钥已配置"
    else
        echo "   ⚠️  OpenAI API密钥未配置"
    fi
    
    if grep -q "DATABASE_HOST" .env; then
        echo "   ✅ 数据库配置已设置"
    else
        echo "   ⚠️  数据库配置未设置"
    fi
else
    echo "   ⚠️  .env 配置文件不存在"
    echo "   💡 运行: cp env.example .env 创建配置文件"
fi

echo ""

# 检查数据库连接
echo "5. 检查数据库连接..."
if command -v psql &> /dev/null; then
    echo "   ✅ PostgreSQL客户端已安装"
    
    # 尝试连接数据库（如果配置了的话）
    if [ -f ".env" ] && grep -q "DATABASE_HOST" .env; then
        DB_HOST=$(grep "DATABASE_HOST" .env | cut -d'=' -f2)
        DB_PORT=$(grep "DATABASE_PORT" .env | cut -d'=' -f2)
        DB_NAME=$(grep "DATABASE_DBNAME" .env | cut -d'=' -f2)
        DB_USER=$(grep "DATABASE_USER" .env | cut -d'=' -f2)
        
        if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ] && [ -n "$DB_NAME" ] && [ -n "$DB_USER" ]; then
            echo "   🔍 尝试连接数据库: $DB_HOST:$DB_PORT/$DB_NAME"
            # 这里可以添加实际的数据库连接测试
        fi
    fi
else
    echo "   ⚠️  PostgreSQL客户端未安装"
    echo "   💡 安装命令:"
    echo "      Ubuntu: sudo apt install postgresql-client"
    echo "      CentOS: sudo yum install postgresql"
fi

echo ""

# 检查Docker环境
echo "6. 检查Docker环境..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | sed 's/,//')
    echo "   ✅ Docker已安装: $DOCKER_VERSION"
    
    if command -v docker-compose &> /dev/null; then
        echo "   ✅ Docker Compose已安装"
    else
        echo "   ⚠️  Docker Compose未安装"
    fi
else
    echo "   ⚠️  Docker未安装"
    echo "   💡 安装命令:"
    echo "      macOS: brew install docker"
    echo "      Ubuntu: sudo apt install docker.io"
fi

echo ""

# 检查端口占用
echo "7. 检查端口占用..."
PORT=5876
if lsof -i :$PORT &> /dev/null; then
    echo "   ⚠️  端口 $PORT 已被占用"
    lsof -i :$PORT
else
    echo "   ✅ 端口 $PORT 可用"
fi

echo ""
echo "🎯 环境检查完成！"
echo ""
echo "💡 下一步操作:"
echo "   1. 如果Go未安装，请先安装Go"
echo "   2. 配置 .env 文件"
echo "   3. 运行: ./quick_start.sh 启动服务"
echo "   4. 或运行: ./run.sh 启动开发服务"
