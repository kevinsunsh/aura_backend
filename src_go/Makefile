.PHONY: help install build run test clean docker-build docker-run check-env

# 默认目标
help:
	@echo "🚀 Aura Backend Go 版本 - 可用命令"
	@echo "=================================="
	@echo ""
	@echo "📦 依赖管理:"
	@echo "  install      - 下载Go依赖"
	@echo "  tidy         - 整理Go模块"
	@echo ""
	@echo "🔨 构建和运行:"
	@echo "  build        - 构建可执行文件"
	@echo "  run          - 运行开发服务"
	@echo "  quick-start  - 快速启动（包含环境检查）"
	@echo ""
	@echo "🧪 测试和检查:"
	@echo "  test         - 运行测试"
	@echo "  check-env    - 检查环境配置"
	@echo ""
	@echo "🐳 Docker操作:"
	@echo "  docker-build - 构建Docker镜像"
	@echo "  docker-run   - 使用Docker Compose运行"
	@echo ""
	@echo "🧹 清理:"
	@echo "  clean        - 清理构建文件"
	@echo ""
	@echo "💡 使用示例:"
	@echo "  make install    # 安装依赖"
	@echo "  make check-env  # 检查环境"
	@echo "  make run        # 运行服务"

# 安装依赖
install:
	@echo "📦 正在下载Go依赖..."
	go mod download
	go mod verify
	@echo "✅ 依赖安装完成"

# 整理模块
tidy:
	@echo "🧹 正在整理Go模块..."
	go mod tidy
	@echo "✅ 模块整理完成"

# 构建
build:
	@echo "🔨 正在构建应用..."
	@chmod +x build.sh
	./build.sh

# 运行开发服务
run:
	@echo "🚀 正在启动开发服务..."
	@chmod +x run.sh
	./run.sh

# 快速启动
quick-start:
	@echo "🚀 正在快速启动..."
	@chmod +x quick_start.sh
	./quick_start.sh

# 运行测试
test:
	@echo "🧪 正在运行测试..."
	go test ./...
	@echo "✅ 测试完成"

# 检查环境
check-env:
	@echo "🔍 正在检查环境..."
	@chmod +x check_env.sh
	./check_env.sh

# 构建Docker镜像
docker-build:
	@echo "🐳 正在构建Docker镜像..."
	docker build -t aura-backend-go .
	@echo "✅ Docker镜像构建完成"

# 运行Docker服务
docker-run:
	@echo "🐳 正在启动Docker服务..."
	docker-compose up -d
	@echo "✅ Docker服务启动完成"

# 停止Docker服务
docker-stop:
	@echo "🛑 正在停止Docker服务..."
	docker-compose down
	@echo "✅ Docker服务已停止"

# 清理构建文件
clean:
	@echo "🧹 正在清理构建文件..."
	rm -rf build/
	rm -f aura-backend
	@echo "✅ 清理完成"

# 格式化代码
fmt:
	@echo "🎨 正在格式化代码..."
	go fmt ./...
	@echo "✅ 代码格式化完成"

# 代码检查
lint:
	@echo "🔍 正在检查代码..."
	@if command -v golangci-lint &> /dev/null; then \
		golangci-lint run; \
	else \
		echo "⚠️  golangci-lint未安装，跳过代码检查"; \
		echo "💡 安装命令: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"; \
	fi

# 生成go.sum
sum:
	@echo "📝 正在生成go.sum..."
	go mod download
	go mod verify
	@echo "✅ go.sum生成完成"

# 显示依赖树
deps:
	@echo "🌳 显示依赖树..."
	go mod graph

# 更新依赖
update:
	@echo "🔄 正在更新依赖..."
	go get -u ./...
	go mod tidy
	@echo "✅ 依赖更新完成"
