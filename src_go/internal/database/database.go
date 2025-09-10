package database

import (
	"aura-backend/internal/config"
	"aura-backend/internal/logger"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

// Database 数据库连接管理器
type Database struct {
	DB *gorm.DB
}

var (
	databaseInstance *Database
	databaseOnce     sync.Once
)

// GetDatabase 获取数据库实例单例
func GetDatabase() *Database {
	databaseOnce.Do(func() {
		databaseInstance = &Database{}
	})
	return databaseInstance
}

// Init 初始化数据库连接
func (db *Database) Init() error {
	cfg := config.GetConfig()
	if cfg == nil {
		return fmt.Errorf("配置未初始化")
	}

	// 检查是否跳过数据库连接
	if os.Getenv("SKIP_DATABASE") == "true" {
		logger.Log.Info("跳过数据库连接，使用内存模式")
		return nil
	}

	// 构建数据库连接字符串
	dsn := fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=%s TimeZone=Asia/Shanghai",
		cfg.Database.Host,
		cfg.Database.Port,
		cfg.Database.User,
		cfg.Database.Password,
		cfg.Database.DBName,
		cfg.Database.SSLMode,
	)

	// 配置GORM日志
	gormLogger := gormlogger.New(
		log.New(os.Stdout, "\r\n", log.LstdFlags),
		gormlogger.Config{
			SlowThreshold:             time.Second,
			LogLevel:                  gormlogger.Info,
			IgnoreRecordNotFoundError: true,
			Colorful:                  true,
		},
	)

	// 连接数据库
	gormDB, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		Logger: gormLogger,
	})
	if err != nil {
		return fmt.Errorf("连接数据库失败: %v", err)
	}

	// 获取底层SQL数据库连接
	sqlDB, err := gormDB.DB()
	if err != nil {
		return fmt.Errorf("获取SQL数据库连接失败: %v", err)
	}

	// 配置连接池
	sqlDB.SetMaxIdleConns(10)
	sqlDB.SetMaxOpenConns(100)
	sqlDB.SetConnMaxLifetime(time.Hour)

	// 测试连接
	if err := sqlDB.Ping(); err != nil {
		return fmt.Errorf("数据库连接测试失败: %v", err)
	}

	db.DB = gormDB
	logger.Log.Info("数据库连接成功")

	// 自动迁移表结构
	if err := db.autoMigrate(); err != nil {
		logger.Log.Warnf("自动迁移失败: %v", err)
	}

	return nil
}

// autoMigrate 自动迁移表结构
func (db *Database) autoMigrate() error {
	// 这里可以添加需要自动迁移的模型
	// 例如：return db.DB.AutoMigrate(&User{}, &ChatMessage{}, &ChatSession{})
	logger.Log.Info("数据库自动迁移完成")
	return nil
}

// Close 关闭数据库连接
func (db *Database) Close() error {
	if db.DB != nil {
		sqlDB, err := db.DB.DB()
		if err != nil {
			return err
		}
		return sqlDB.Close()
	}
	return nil
}

// GetDB 获取GORM数据库实例
func (db *Database) GetDB() *gorm.DB {
	return db.DB
}

// HealthCheck 数据库健康检查
func (db *Database) HealthCheck() error {
	if db.DB == nil {
		return fmt.Errorf("数据库未初始化")
	}

	sqlDB, err := db.DB.DB()
	if err != nil {
		return fmt.Errorf("获取SQL数据库连接失败: %v", err)
	}

	return sqlDB.Ping()
}

// Transaction 执行数据库事务
func (db *Database) Transaction(fn func(tx *gorm.DB) error) error {
	return db.DB.Transaction(fn)
}

// Begin 开始事务
func (db *Database) Begin() *gorm.DB {
	return db.DB.Begin()
}

// Commit 提交事务
func (db *Database) Commit() *gorm.DB {
	return db.DB.Commit()
}

// Rollback 回滚事务
func (db *Database) Rollback() *gorm.DB {
	return db.DB.Rollback()
}
