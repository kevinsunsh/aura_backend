package models

import (
	"time"

	"gorm.io/gorm"
)

// ChatSession 聊天会话模型
type ChatSession struct {
	ID          uint           `json:"id" gorm:"primaryKey"`
	ChatID      string         `json:"chat_id" gorm:"uniqueIndex;not null"`
	UserID      string         `json:"user_id" gorm:"index;not null"`
	Title       string         `json:"title" gorm:"size:200"`
	Status      string         `json:"status" gorm:"size:20;default:'active'"`
	MessageCount int            `json:"message_count" gorm:"default:0"`
	LastMessageAt *time.Time   `json:"last_message_at"`
	CreatedAt   time.Time      `json:"created_at"`
	UpdatedAt   time.Time      `json:"updated_at"`
	DeletedAt   gorm.DeletedAt `json:"deleted_at,omitempty" gorm:"index"`

	// 关联关系
	User        User           `json:"user,omitempty" gorm:"foreignKey:UserID;references:UserID"`
	Messages    []ChatMessage  `json:"messages,omitempty" gorm:"foreignKey:ChatID;references:ChatID"`
}

// TableName 指定表名
func (ChatSession) TableName() string {
	return "chat_sessions"
}

// BeforeCreate 创建前的钩子
func (cs *ChatSession) BeforeCreate(tx *gorm.DB) error {
	if cs.CreatedAt.IsZero() {
		cs.CreatedAt = time.Now()
	}
	if cs.UpdatedAt.IsZero() {
		cs.UpdatedAt = time.Now()
	}
	return nil
}

// BeforeUpdate 更新前的钩子
func (cs *ChatSession) BeforeUpdate(tx *gorm.DB) error {
	cs.UpdatedAt = time.Now()
	return nil
}
