package config

import (
	"github.com/spf13/viper"
	"os"
)

type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Database DatabaseConfig `mapstructure:"database"`
	OpenAI   OpenAIConfig   `mapstructure:"openai"`
	API      APIConfig      `mapstructure:"api"`
	App      AppConfig      `mapstructure:"app"`
}

type ServerConfig struct {
	Port int    `mapstructure:"port"`
	Host string `mapstructure:"host"`
}

type DatabaseConfig struct {
	Host     string `mapstructure:"host"`
	Port     int    `mapstructure:"port"`
	DBName   string `mapstructure:"dbname"`
	User     string `mapstructure:"user"`
	Password string `mapstructure:"password"`
	Schema   string `mapstructure:"schema"`
	SSLMode  string `mapstructure:"sslmode"`
}

type OpenAIConfig struct {
	APIKey    string `mapstructure:"api_key"`
	BaseURL   string `mapstructure:"base_url"`
	Model     string `mapstructure:"model"`
}

type APIConfig struct {
	TavilyAPIKey    string `mapstructure:"tavily_api_key"`
	JinaAPIKey      string `mapstructure:"jina_api_key"`
	BraveSearchKey  string `mapstructure:"brave_search_api_key"`
	SerperAPIKey    string `mapstructure:"serper_api_key"`
}

type AppConfig struct {
	Debug   bool   `mapstructure:"debug"`
	LogDir  string `mapstructure:"log_dir"`
	Version string `mapstructure:"version"`
}

var GlobalConfig *Config

func Init() error {
	// 设置配置文件路径
	configPath := os.Getenv("CONFIG_PATH")
	if configPath == "" {
		configPath = "."
	}

	viper.SetConfigName(".env")
	viper.SetConfigType("env")
	viper.AddConfigPath(configPath)

	// 设置默认值
	setDefaults()

	// 读取环境变量
	viper.AutomaticEnv()

	// 读取配置文件
	if err := viper.ReadInConfig(); err != nil {
		// 如果配置文件不存在，使用环境变量
		if _, ok := err.(viper.ConfigFileNotFoundError); !ok {
			return err
		}
	}

	// 解析配置
	config := &Config{}
	if err := viper.Unmarshal(config); err != nil {
		return err
	}

	// 设置全局配置
	GlobalConfig = config

	return nil
}

func setDefaults() {
	viper.SetDefault("server.port", 5876)
	viper.SetDefault("server.host", "0.0.0.0")
	viper.SetDefault("database.host", "localhost")
	viper.SetDefault("database.port", 5432)
	viper.SetDefault("database.sslmode", "disable")
	viper.SetDefault("database.schema", "public")
	viper.SetDefault("openai.model", "gpt-3.5-turbo")
	viper.SetDefault("app.debug", true)
	viper.SetDefault("app.version", "1.0.0")
	
	// 设置日志目录
	if logDir := os.Getenv("LOG_DIR"); logDir != "" {
		viper.SetDefault("app.log_dir", logDir)
	} else {
		viper.SetDefault("app.log_dir", "./logs")
	}
}

func GetConfig() *Config {
	return GlobalConfig
}
