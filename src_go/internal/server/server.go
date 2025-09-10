package server

import (
	"net/http"
	"strconv"
	"time"

	"aura-backend/internal/agent"
	"aura-backend/internal/chat"
	"aura-backend/internal/config"
	"aura-backend/internal/database"
	"aura-backend/internal/logger"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

// Server HTTP服务器
type Server struct {
	router    *gin.Engine
	config    *config.Config
	startTime time.Time
}

// NewServer 创建新的服务器实例
func NewServer(config *config.Config) *Server {
	// 初始化数据库（可选）
	db := database.GetDatabase()
	if err := db.Init(); err != nil {
		logger.Log.Warnf("数据库初始化失败（将使用内存模式）: %v", err)
	} else {
		logger.Log.Info("数据库连接成功")
	}

	// 创建Gin路由器
	router := gin.Default()

	// 配置CORS
	router.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	server := &Server{
		router:    router,
		config:    config,
		startTime: time.Now(),
	}

	// 设置路由
	server.setupRoutes()

	return server
}

// setupRoutes 设置路由
func (server *Server) setupRoutes() {
	// 健康检查
	server.router.GET("/health", server.healthCheck)

	// 根路径
	server.router.GET("/", server.rootHandler)

	// API v1 路由组
	v1 := server.router.Group("/v1")
	{
		v1.GET("/ping", server.pingHandler)
		v1.GET("/stats", server.statsHandler)
	}

	// WebSocket流式连接
	server.router.GET("/ws/stream", server.websocketHandler)

	// SSE端点 (对应app.py中的/sse端点)
	server.router.GET("/sse", server.sseHandler)
}

// healthCheck 健康检查处理器
func (server *Server) healthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "healthy",
		"timestamp": time.Now().Unix(),
		"service":   "Aura Backend",
		"version":   "1.0.0",
	})
}

// rootHandler 根路径处理器
func (server *Server) rootHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"message":   "Aura Backend API",
		"version":   "1.0.0",
		"timestamp": time.Now().Unix(),
		"endpoints": []string{
			"GET  /health",
			"GET  /v1/ping",
			"GET  /v1/stats",
			"GET  /ws/stream",
		},
	})
}

// pingHandler 心跳检测处理器
func (server *Server) pingHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"message":   "pong",
		"timestamp": time.Now().Unix(),
	})
}

// statsHandler 统计信息处理器
func (server *Server) statsHandler(c *gin.Context) {
	// 在需要时才获取聊天管理器实例 (对应app.py中的按需获取)
	chatManager := chat.GetChatStreamManager()
	sessionCount := chatManager.GetActiveSessionCount()

	c.JSON(http.StatusOK, gin.H{
		"timestamp":       time.Now().Unix(),
		"active_sessions": sessionCount,
		"uptime_seconds":  time.Since(server.startTime).Seconds(),
	})
}

// websocketHandler WebSocket处理器适配器
func (server *Server) websocketHandler(c *gin.Context) {
	// 在需要时才获取AuraAgent实例 (对应app.py中的AuraAgent.get_instance())
	auraAgent := agent.GetInstance()
	auraAgent.HandleWebSocket(c.Writer, c.Request)
}

// sseHandler SSE处理器 (对应app.py中的sse_endpoint)
func (server *Server) sseHandler(c *gin.Context) {
	// 设置SSE响应头
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("Access-Control-Allow-Origin", "*")

	// 简单的SSE实现
	c.String(http.StatusOK, "data: SSE endpoint ready\n\n")
}

// Start 启动服务器
func (server *Server) Start() error {
	addr := server.config.Server.Host + ":" + strconv.Itoa(server.config.Server.Port)
	logger.Log.Infof("🚀 启动Aura Backend服务器: %s", addr)

	return server.router.Run(addr)
}
