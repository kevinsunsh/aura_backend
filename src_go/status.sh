#!/bin/bash

echo "📊 Aura Backend Go 版本项目状态"
echo "================================"

# 检查项目结构
echo "1. 项目结构检查..."
MISSING_FILES=()

# 检查核心文件
if [ ! -f "main.go" ]; then MISSING_FILES+=("main.go"); fi
if [ ! -f "go.mod" ]; then MISSING_FILES+=("go.mod"); fi
if [ ! -f "Dockerfile" ]; then MISSING_FILES+=("Dockerfile"); fi
if [ ! -f "docker-compose.yml" ]; then MISSING_FILES+=("docker-compose.yml"); fi

# 检查内部包
if [ ! -d "internal" ]; then MISSING_FILES+=("internal/"); fi
if [ ! -d "internal/agent" ]; then MISSING_FILES+=("internal/agent/"); fi
if [ ! -d "internal/ai" ]; then MISSING_FILES+=("internal/ai/"); fi
if [ ! -d "internal/chat" ]; then MISSING_FILES+=("internal/chat/"); fi
if [ ! -d "internal/config" ]; then MISSING_FILES+=("internal/config/"); fi
if [ ! -d "internal/database" ]; then MISSING_FILES+=("internal/database/"); fi
if [ ! -d "internal/logger" ]; then MISSING_FILES+=("internal/logger/"); fi
if [ ! -d "internal/message" ]; then MISSING_FILES+=("internal/message/"); fi
if [ ! -d "internal/models" ]; then MISSING_FILES+=("internal/models/"); fi
if [ ! -d "internal/protocol" ]; then MISSING_FILES+=("internal/protocol/"); fi
if [ ! -d "internal/server" ]; then MISSING_FILES+=("internal/server/"); fi

if [ ${#MISSING_FILES[@]} -eq 0 ]; then
    echo "   ✅ 项目结构完整"
else
    echo "   ❌ 缺失文件/目录:"
    for file in "${MISSING_FILES[@]}"; do
        echo "      - $file"
    done
fi

echo ""

# 检查Go模块
echo "2. Go模块检查..."
if [ -f "go.mod" ]; then
    echo "   ✅ go.mod 存在"
    
    # 检查模块名称
    MODULE_NAME=$(grep "^module" go.mod | awk '{print $2}')
    if [ "$MODULE_NAME" = "aura-backend" ]; then
        echo "   ✅ 模块名称正确: $MODULE_NAME"
    else
        echo "   ⚠️  模块名称不正确: $MODULE_NAME"
    fi
else
    echo "   ❌ go.mod 不存在"
fi

echo ""

# 检查依赖
echo "3. 依赖检查..."
if [ -f "go.mod" ]; then
    # 检查主要依赖
    DEPS=("github.com/gin-gonic/gin" "github.com/gorilla/websocket" "gorm.io/gorm")
    for dep in "${DEPS[@]}"; do
        if grep -q "$dep" go.mod; then
            echo "   ✅ $dep"
        else
            echo "   ❌ $dep"
        fi
    done
fi

echo ""

# 检查配置文件
echo "4. 配置文件检查..."
if [ -f ".env" ]; then
    echo "   ✅ .env 配置文件存在"
    
    # 检查关键配置项
    CONFIG_ITEMS=("OPENAI_API_KEY" "DATABASE_HOST" "SERVER_PORT")
    for item in "${CONFIG_ITEMS[@]}"; do
        if grep -q "$item" .env; then
            echo "   ✅ $item 已配置"
        else
            echo "   ⚠️  $item 未配置"
        fi
    done
else
    echo "   ⚠️  .env 配置文件不存在"
    echo "   💡 运行: cp env.example .env 创建配置文件"
fi

echo ""

# 检查脚本权限
echo "5. 脚本权限检查..."
SCRIPTS=("build.sh" "run.sh" "quick_start.sh" "check_env.sh" "status.sh")
for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        if [ -x "$script" ]; then
            echo "   ✅ $script 可执行"
        else
            echo "   ⚠️  $script 不可执行"
        fi
    else
        echo "   ❌ $script 不存在"
    fi
done

echo ""

# 检查构建状态
echo "6. 构建状态检查..."
if [ -d "build" ] && [ -f "build/aura-backend" ]; then
    echo "   ✅ 已构建，二进制文件存在"
    echo "   📁 构建目录: build/"
    echo "   📦 二进制文件: build/aura-backend"
    echo "   📏 文件大小: $(du -h build/aura-backend | cut -f1)"
else
    echo "   ⚠️  未构建或构建失败"
    echo "   💡 运行: make build 或 ./build.sh"
fi

echo ""

# 检查服务状态
echo "7. 服务状态检查..."
PORT=5876
if lsof -i :$PORT &> /dev/null; then
    echo "   ✅ 服务正在运行 (端口 $PORT)"
    lsof -i :$PORT
else
    echo "   ⚠️  服务未运行 (端口 $PORT)"
    echo "   💡 运行: make run 或 ./run.sh"
fi

echo ""
echo "🎯 项目状态检查完成！"
echo ""
echo "💡 建议操作:"
if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    echo "   1. 修复缺失的文件/目录"
fi
if [ ! -f ".env" ]; then
    echo "   2. 创建并配置 .env 文件"
fi
if [ ! -d "build" ]; then
    echo "   3. 构建项目: make build"
fi
if ! lsof -i :5876 &> /dev/null; then
    echo "   4. 启动服务: make run"
fi
echo ""
echo "🔧 常用命令:"
echo "   make help        - 查看所有可用命令"
echo "   make check-env   - 检查环境配置"
echo "   make install     - 安装依赖"
echo "   make test        - 运行测试"
echo "   make build       - 构建项目"
echo "   make run         - 运行服务"
