package chat

import (
	"aura-backend/internal/logger"
	"sync"
	"time"

	"github.com/google/uuid"
)

// ChatStream 聊天流结构
type ChatStream struct {
	ChatID      string    `json:"chat_id"`
	UserID      string    `json:"user_id"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
	IsActive    bool      `json:"is_active"`
	MessageCount int       `json:"message_count"`
}

// ChatStreamManager 聊天流管理器
type ChatStreamManager struct {
	mu         sync.RWMutex
	chatStreams map[string]*ChatStream
	locks      map[string]bool
}

var (
	chatManagerInstance *ChatStreamManager
	chatManagerOnce     sync.Once
)

// GetChatStreamManager 获取聊天流管理器单例
func GetChatStreamManager() *ChatStreamManager {
	chatManagerOnce.Do(func() {
		chatManagerInstance = &ChatStreamManager{
			chatStreams: make(map[string]*ChatStream),
			locks:      make(map[string]bool),
		}
	})
	return chatManagerInstance
}

// GetOrCreateChatStream 获取或创建聊天流
func (csm *ChatStreamManager) GetOrCreateChatStream(chatID string) *ChatStream {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	if stream, exists := csm.chatStreams[chatID]; exists {
		stream.UpdatedAt = time.Now()
		stream.IsActive = true
		return stream
	}

	// 创建新的聊天流
	stream := &ChatStream{
		ChatID:      chatID,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		IsActive:    true,
		MessageCount: 0,
	}

	csm.chatStreams[chatID] = stream
	logger.Log.Infof("创建新的聊天流: %s", chatID)
	return stream
}

// AcquireLock 获取聊天流锁
func (csm *ChatStreamManager) AcquireLock(chatID string) bool {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	if csm.locks[chatID] {
		return false // 锁已被占用
	}

	csm.locks[chatID] = true
	logger.Log.Debugf("获取聊天流锁: %s", chatID)
	return true
}

// ReleaseLock 释放聊天流锁
func (csm *ChatStreamManager) ReleaseLock(chatID string) {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	if csm.locks[chatID] {
		delete(csm.locks, chatID)
		logger.Log.Debugf("释放聊天流锁: %s", chatID)
	}
}

// GetChatStream 获取聊天流
func (csm *ChatStreamManager) GetChatStream(chatID string) *ChatStream {
	csm.mu.RLock()
	defer csm.mu.RUnlock()

	return csm.chatStreams[chatID]
}

// UpdateChatStream 更新聊天流
func (csm *ChatStreamManager) UpdateChatStream(chatID string, updates map[string]interface{}) {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	if stream, exists := csm.chatStreams[chatID]; exists {
		stream.UpdatedAt = time.Now()
		
		// 应用更新
		if messageCount, ok := updates["message_count"].(int); ok {
			stream.MessageCount = messageCount
		}
		if isActive, ok := updates["is_active"].(bool); ok {
			stream.IsActive = isActive
		}
	}
}

// RemoveChatStream 移除聊天流
func (csm *ChatStreamManager) RemoveChatStream(chatID string) {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	delete(csm.chatStreams, chatID)
	delete(csm.locks, chatID)
	logger.Log.Infof("移除聊天流: %s", chatID)
}

// GetActiveChatStreams 获取活跃的聊天流
func (csm *ChatStreamManager) GetActiveChatStreams() []*ChatStream {
	csm.mu.RLock()
	defer csm.mu.RUnlock()

	var activeStreams []*ChatStream
	for _, stream := range csm.chatStreams {
		if stream.IsActive {
			activeStreams = append(activeStreams, stream)
		}
	}
	return activeStreams
}

// CleanupInactiveStreams 清理非活跃的聊天流
func (csm *ChatStreamManager) CleanupInactiveStreams(maxAge time.Duration) {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	now := time.Now()
	for chatID, stream := range csm.chatStreams {
		if !stream.IsActive && now.Sub(stream.UpdatedAt) > maxAge {
			delete(csm.chatStreams, chatID)
			delete(csm.locks, chatID)
			logger.Log.Infof("清理非活跃聊天流: %s", chatID)
		}
	}
}

// GenerateChatID 生成新的聊天ID
func (csm *ChatStreamManager) GenerateChatID() string {
	return uuid.New().String()
}

// GetStats 获取统计信息
func (csm *ChatStreamManager) GetStats() map[string]interface{} {
	csm.mu.RLock()
	defer csm.mu.RUnlock()

	totalStreams := len(csm.chatStreams)
	activeStreams := 0
	totalMessages := 0

	for _, stream := range csm.chatStreams {
		if stream.IsActive {
			activeStreams++
		}
		totalMessages += stream.MessageCount
	}

	return map[string]interface{}{
		"total_streams":   totalStreams,
		"active_streams":  activeStreams,
		"total_messages":  totalMessages,
		"locked_streams":  len(csm.locks),
	}
}

// CreateSession 创建新的聊天会话
func (csm *ChatStreamManager) CreateSession(sessionID, chatID, userID string) error {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	// 创建新的聊天流
	stream := &ChatStream{
		ChatID:      chatID,
		UserID:      userID,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		IsActive:    true,
		MessageCount: 0,
	}

	csm.chatStreams[chatID] = stream
	logger.Log.Infof("创建新的聊天会话: sessionID=%s, chatID=%s, userID=%s", sessionID, chatID, userID)
	return nil
}

// EndSession 结束聊天会话
func (csm *ChatStreamManager) EndSession(sessionID string) error {
	csm.mu.Lock()
	defer csm.mu.Unlock()

	// 查找并标记会话为非活跃
	for chatID, stream := range csm.chatStreams {
		if stream.IsActive {
			stream.IsActive = false
			stream.UpdatedAt = time.Now()
			logger.Log.Infof("结束聊天会话: sessionID=%s, chatID=%s", sessionID, chatID)
			break
		}
	}

	return nil
}

// GetActiveSessionCount 获取活跃会话数量
func (csm *ChatStreamManager) GetActiveSessionCount() int {
	csm.mu.RLock()
	defer csm.mu.RUnlock()

	count := 0
	for _, stream := range csm.chatStreams {
		if stream.IsActive {
			count++
		}
	}
	return count
}
