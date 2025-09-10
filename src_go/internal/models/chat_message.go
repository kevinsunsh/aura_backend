package models

import (
	"time"

	"gorm.io/gorm"
)

// ChatMessage 聊天消息模型
type ChatMessage struct {
	ID        uint           `json:"id" gorm:"primaryKey"`
	ChatID    string         `json:"chat_id" gorm:"index;not null"`
	UserID    string         `json:"user_id" gorm:"index;not null"`
	Role      string         `json:"role" gorm:"size:20;not null"` // user, assistant, system
	Content   string         `json:"content" gorm:"type:text"`
	MessageType string       `json:"message_type" gorm:"size:20;default:'text'"` // text, audio, image
	Metadata  string         `json:"metadata" gorm:"type:jsonb"` // 存储额外信息，如音频时长、文件路径等
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `json:"deleted_at,omitempty" gorm:"index"`

	// 关联关系
	ChatSession ChatSession `json:"chat_session,omitempty" gorm:"foreignKey:ChatID;references:ChatID"`
	User        User        `json:"user,omitempty" gorm:"foreignKey:UserID;references:UserID"`
}

// TableName 指定表名
func (ChatMessage) TableName() string {
	return "chat_messages"
}

// BeforeCreate 创建前的钩子
func (cm *ChatMessage) BeforeCreate(tx *gorm.DB) error {
	if cm.CreatedAt.IsZero() {
		cm.CreatedAt = time.Now()
	}
	if cm.UpdatedAt.IsZero() {
		cm.UpdatedAt = time.Now()
	}
	return nil
}

// BeforeUpdate 更新前的钩子
func (cm *ChatMessage) BeforeUpdate(tx *gorm.DB) error {
	cm.UpdatedAt = time.Now()
	return nil
}
