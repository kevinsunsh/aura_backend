package models

import (
	"time"

	"gorm.io/gorm"
)

// User 用户模型
type User struct {
	ID        uint           `json:"id" gorm:"primaryKey"`
	UserID    string         `json:"user_id" gorm:"uniqueIndex;not null"`
	Username  string         `json:"username" gorm:"size:100;not null"`
	Email     string         `json:"email" gorm:"size:255;uniqueIndex"`
	Avatar    string         `json:"avatar" gorm:"size:500"`
	Status    string         `json:"status" gorm:"size:20;default:'active'"`
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `json:"deleted_at,omitempty" gorm:"index"`

	// 关联关系
	ChatSessions []ChatSession `json:"chat_sessions,omitempty" gorm:"foreignKey:UserID;references:UserID"`
}

// TableName 指定表名
func (User) TableName() string {
	return "users"
}

// BeforeCreate 创建前的钩子
func (u *User) BeforeCreate(tx *gorm.DB) error {
	if u.CreatedAt.IsZero() {
		u.CreatedAt = time.Now()
	}
	if u.UpdatedAt.IsZero() {
		u.UpdatedAt = time.Now()
	}
	return nil
}

// BeforeUpdate 更新前的钩子
func (u *User) BeforeUpdate(tx *gorm.DB) error {
	u.UpdatedAt = time.Now()
	return nil
}
