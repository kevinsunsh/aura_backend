package logger

import (
	"aura-backend/internal/config"
	"os"
	"path/filepath"

	"github.com/sirupsen/logrus"
)

var log *logrus.Logger

// Log 导出的日志实例
var Log *logrus.Logger

func Init() error {
	log = logrus.New()
	Log = log // 导出Log变量

	// 设置日志格式
	log.SetFormatter(&logrus.TextFormatter{
		FullTimestamp:   true,
		TimestampFormat: "15:04:05",
		ForceColors:     true,
	})

	// 设置日志级别
	level := os.Getenv("LOG_LEVEL")
	if level == "" {
		level = "info"
	}

	logLevel, err := logrus.ParseLevel(level)
	if err != nil {
		logLevel = logrus.InfoLevel
	}
	log.SetLevel(logLevel)

	// 设置输出
	cfg := config.GetConfig()
	if cfg != nil && cfg.App.LogDir != "" {
		// 确保日志目录存在
		if err := os.MkdirAll(cfg.App.LogDir, 0755); err != nil {
			return err
		}

		// 创建日志文件
		logFile := filepath.Join(cfg.App.LogDir, "main.log")
		file, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
		if err != nil {
			return err
		}

		// 同时输出到文件和控制台
		log.SetOutput(file)
		log.AddHook(&ConsoleHook{})
	}

	return nil
}

// ConsoleHook 用于同时输出到控制台
type ConsoleHook struct{}

func (h *ConsoleHook) Levels() []logrus.Level {
	return logrus.AllLevels
}

func (h *ConsoleHook) Fire(entry *logrus.Entry) error {
	// 直接输出到控制台，避免递归调用
	formatter := &logrus.TextFormatter{
		FullTimestamp:   true,
		TimestampFormat: "15:04:05",
		ForceColors:     true,
	}
	
	// 格式化消息
	formatted, err := formatter.Format(entry)
	if err != nil {
		return err
	}
	
	// 直接写入到控制台
	os.Stdout.Write(formatted)
	return nil
}

// 提供便捷的日志方法
func Info(args ...interface{}) {
	log.Info(args...)
}

func Infof(format string, args ...interface{}) {
	log.Infof(format, args...)
}

func Error(args ...interface{}) {
	log.Error(args...)
}

func Errorf(format string, args ...interface{}) {
	log.Errorf(format, args...)
}

func Warn(args ...interface{}) {
	log.Warn(args...)
}

func Warnf(format string, args ...interface{}) {
	log.Warnf(format, args...)
}

func Debug(args ...interface{}) {
	log.Debug(args...)
}

func Debugf(format string, args ...interface{}) {
	log.Debugf(format, args...)
}

func Fatal(args ...interface{}) {
	log.Fatal(args...)
}

func Fatalf(format string, args ...interface{}) {
	log.Fatalf(format, args...)
}

// WithField 添加字段到日志
func WithField(key string, value interface{}) *logrus.Entry {
	return log.WithField(key, value)
}

// WithFields 添加多个字段到日志
func WithFields(fields logrus.Fields) *logrus.Entry {
	return log.WithFields(fields)
}

// GetLogger 获取日志实例
func GetLogger() *logrus.Logger {
	return log
}
