package config

import (
	"os"
	"testing"
)

func TestConfigInit(t *testing.T) {
	// 清理环境变量
	os.Unsetenv("SERVER_PORT")
	os.Unsetenv("DATABASE_HOST")
	
	// 测试初始化
	err := Init()
	if err != nil {
		t.Errorf("配置初始化失败: %v", err)
	}
	
	// 检查默认值
	cfg := GetConfig()
	if cfg == nil {
		t.Error("配置实例为空")
		return
	}
	
	if cfg.Server.Port != 5876 {
		t.Errorf("期望服务器端口为5876，实际为%d", cfg.Server.Port)
	}
	
	if cfg.Server.Host != "0.0.0.0" {
		t.Errorf("期望服务器主机为0.0.0.0，实际为%s", cfg.Server.Host)
	}
}

func TestConfigWithEnvVars(t *testing.T) {
	// 设置环境变量
	os.Setenv("SERVER_PORT", "8080")
	os.Setenv("DATABASE_HOST", "testhost")
	
	// 重新初始化
	err := Init()
	if err != nil {
		t.Errorf("配置初始化失败: %v", err)
	}
	
	// 检查环境变量值
	cfg := GetConfig()
	if cfg.Server.Port != 8080 {
		t.Errorf("期望服务器端口为8080，实际为%d", cfg.Server.Port)
	}
	
	if cfg.Database.Host != "testhost" {
		t.Errorf("期望数据库主机为testhost，实际为%s", cfg.Database.Host)
	}
	
	// 清理环境变量
	os.Unsetenv("SERVER_PORT")
	os.Unsetenv("DATABASE_HOST")
	
	// 重新初始化以恢复默认值
	Init()
}

func TestConfigDefaults(t *testing.T) {
	// 清理环境变量
	os.Unsetenv("SERVER_PORT")
	os.Unsetenv("DATABASE_HOST")
	
	// 重新初始化
	err := Init()
	if err != nil {
		t.Errorf("配置初始化失败: %v", err)
	}
	
	// 检查默认值
	cfg := GetConfig()
	if cfg.Server.Port != 5876 {
		t.Errorf("期望默认服务器端口为5876，实际为%d", cfg.Server.Port)
	}
	
	if cfg.Server.Host != "0.0.0.0" {
		t.Errorf("期望默认服务器主机为0.0.0.0，实际为%s", cfg.Server.Host)
	}
}
