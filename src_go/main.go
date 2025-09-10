package main

import (
	"aura-backend/internal/config"
	"aura-backend/internal/logger"
	"aura-backend/internal/server"
	"log"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	// 初始化配置
	if err := config.Init(); err != nil {
		log.Fatalf("配置初始化失败: %v", err)
	}

	// 初始化日志
	if err := logger.Init(); err != nil {
		log.Fatalf("日志初始化失败: %v", err)
	}

	logger.Log.Info("🚀 Aura Backend 启动中...")

	// 获取配置
	cfg := config.GetConfig()
	logger.Log.Infof("配置加载完成: 服务器地址=%s, 端口=%d", cfg.Server.Host, cfg.Server.Port)

	// 创建服务器
	srv := server.NewServer(cfg)

	// 启动服务器（在goroutine中）
	go func() {
		if err := srv.Start(); err != nil {
			logger.Log.Fatalf("服务器启动失败: %v", err)
		}
	}()

	// 等待中断信号
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Log.Info("🛑 收到关闭信号，正在优雅关闭...")

	// 清理资源
	if err := cleanup(); err != nil {
		logger.Log.Errorf("清理资源失败: %v", err)
	}

	logger.Log.Info("✅ Aura Backend 已关闭")
}

// cleanup 清理资源
func cleanup() error {
	logger.Log.Info("🧹 开始清理资源...")
	
	// 这里可以添加其他清理逻辑
	// 例如：关闭数据库连接、清理临时文件等
	
	logger.Log.Info("✅ 资源清理完成")
	return nil
}
