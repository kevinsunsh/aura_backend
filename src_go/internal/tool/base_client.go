package tool

import (
	"aura-backend/internal/logger"
	"context"
	"fmt"
	"sync"
	"time"
)

// ServerResponse 服务器响应结构
type ServerResponse map[string]interface{}

// ClientInterface 客户端接口
type ClientInterface interface {
	ConsumerWorker(ctx context.Context, inputQueue <-chan interface{}, outputQueue chan<- ServerResponse)
	HandleServerResponse(response ServerResponse)
}

// BaseClient 实时对话客户端基类，使用goroutine代替进程
type BaseClient struct {
	logid                   string
	chatID                  string
	userID                  string
	sessionID               string
	internalInputQueue      chan interface{}
	internalOutputQueue     chan ServerResponse
	internalIsWorkerRunning bool
	workerMutex             sync.RWMutex
	messageLoopCtx          context.Context
	messageLoopCancel       context.CancelFunc
	workerCtx               context.Context
	workerCancel            context.CancelFunc
	started                 bool
	startMutex              sync.Mutex
	clientInterface         ClientInterface
}

// NewBaseClient 创建新的BaseClient实例
func NewBaseClient(clientInterface ClientInterface) *BaseClient {
	// 创建带缓冲的channel，避免阻塞
	inputQueue := make(chan interface{}, 100)
	outputQueue := make(chan ServerResponse, 100)

	workerCtx, workerCancel := context.WithCancel(context.Background())

	return &BaseClient{
		internalInputQueue:      inputQueue,
		internalOutputQueue:     outputQueue,
		internalIsWorkerRunning: false,
		workerCtx:               workerCtx,
		workerCancel:            workerCancel,
		started:                 false,
		clientInterface:         clientInterface,
	}
}

// ConsumerWorker 常驻worker goroutine：负责音频处理
// 子类需要实现这个方法
func (bc *BaseClient) ConsumerWorker(ctx context.Context, inputQueue <-chan interface{}, outputQueue chan<- ServerResponse) {
	// 子类实现
	logger.Log.Warn("BaseClient.ConsumerWorker 需要被子类实现")
}

// StartWorker 启动worker的通用方法，使用接口调用子类实现
func (bc *BaseClient) StartWorker() {
	if bc.clientInterface != nil {
		go bc.clientInterface.ConsumerWorker(bc.workerCtx, bc.internalInputQueue, bc.internalOutputQueue)
	} else {
		go bc.ConsumerWorker(bc.workerCtx, bc.internalInputQueue, bc.internalOutputQueue)
	}
}

// MessageReceiveLoop 服务器响应接收循环
func (bc *BaseClient) MessageReceiveLoop(ctx context.Context) {
	logger.Log.Info("开始消息接收循环")
	defer logger.Log.Info("消息接收循环结束")

	for {
		select {
		case <-ctx.Done():
			logger.Log.Info("消息接收循环被取消")
			return
		case response, ok := <-bc.internalOutputQueue:
			if !ok {
				logger.Log.Info("输出队列已关闭")
				return
			}
			bc.HandleServerResponse(response)
		case <-time.After(1 * time.Second):
			// 定期检查context状态
			continue
		}
	}
}

// HandleServerResponse 处理服务器响应
// 使用接口调用子类实现
func (bc *BaseClient) HandleServerResponse(response ServerResponse) {
	if bc.clientInterface != nil {
		bc.clientInterface.HandleServerResponse(response)
	} else {
		logger.Log.Warn("BaseClient.HandleServerResponse 需要被子类实现")
	}
}

// Start 启动客户端
func (bc *BaseClient) Start(chatID, userID string) bool {
	bc.startMutex.Lock()
	defer bc.startMutex.Unlock()

	if bc.started {
		logger.Log.Warn("客户端已经启动")
		return true
	}

	bc.sessionID = chatID
	bc.userID = userID
	bc.chatID = chatID

	// 启动worker goroutine
	bc.workerMutex.Lock()
	bc.internalIsWorkerRunning = true
	bc.workerMutex.Unlock()

	bc.StartWorker()

	// 启动消息接收循环
	bc.messageLoopCtx, bc.messageLoopCancel = context.WithCancel(context.Background())
	go bc.MessageReceiveLoop(bc.messageLoopCtx)

	bc.started = true
	logger.Log.Infof("启动客户端成功: chat_id=%s, user_id=%s", chatID, userID)
	return true
}

// Cleanup 清理资源
func (bc *BaseClient) Cleanup() {
	bc.startMutex.Lock()
	defer bc.startMutex.Unlock()

	if !bc.started {
		return
	}

	logger.Log.Info("开始清理BaseClient资源")

	// 停止worker
	bc.workerMutex.Lock()
	if bc.internalIsWorkerRunning {
		bc.internalIsWorkerRunning = false
		bc.workerCancel()
	}
	bc.workerMutex.Unlock()

	// 停止消息接收循环
	if bc.messageLoopCancel != nil {
		bc.messageLoopCancel()
	}

	// 关闭channels
	close(bc.internalInputQueue)
	close(bc.internalOutputQueue)

	bc.started = false
	logger.Log.Info("BaseClient资源清理完成")
}

// SendToWorker 发送消息到worker
func (bc *BaseClient) SendToWorker(data interface{}) error {
	select {
	case bc.internalInputQueue <- data:
		return nil
	case <-time.After(5 * time.Second):
		return fmt.Errorf("发送到worker超时")
	}
}

// IsWorkerRunning 检查worker是否正在运行
func (bc *BaseClient) IsWorkerRunning() bool {
	bc.workerMutex.RLock()
	defer bc.workerMutex.RUnlock()
	return bc.internalIsWorkerRunning
}

// GetChatID 获取聊天ID
func (bc *BaseClient) GetChatID() string {
	return bc.chatID
}

// GetUserID 获取用户ID
func (bc *BaseClient) GetUserID() string {
	return bc.userID
}

// GetSessionID 获取会话ID
func (bc *BaseClient) GetSessionID() string {
	return bc.sessionID
}

// SetLogID 设置日志ID
func (bc *BaseClient) SetLogID(logid string) {
	bc.logid = logid
}

// GetLogID 获取日志ID
func (bc *BaseClient) GetLogID() string {
	return bc.logid
}
