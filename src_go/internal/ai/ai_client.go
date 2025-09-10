package ai

import (
	"aura-backend/internal/config"
	"aura-backend/internal/logger"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

// AIClient AI客户端
type AIClient struct {
	config     *config.Config
	httpClient *http.Client
}

// ChatMessage 聊天消息结构
type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest 聊天请求结构
type ChatRequest struct {
	Model       string        `json:"model"`
	Messages    []ChatMessage `json:"messages"`
	Temperature float64       `json:"temperature,omitempty"`
	MaxTokens   int           `json:"max_tokens,omitempty"`
	Stream      bool          `json:"stream,omitempty"`
}

// ChatResponse 聊天响应结构
type ChatResponse struct {
	ID      string `json:"id"`
	Object  string `json:"object"`
	Created int64  `json:"created"`
	Model   string `json:"model"`
	Choices []struct {
		Index   int `json:"index"`
		Message struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
}

// AudioTranscriptionRequest 音频转录请求
type AudioTranscriptionRequest struct {
	File     []byte `json:"file"`
	Model    string `json:"model"`
	Language string `json:"language,omitempty"`
}

// AudioTranscriptionResponse 音频转录响应
type AudioTranscriptionResponse struct {
	Text string `json:"text"`
}

var (
	aiClientInstance *AIClient
	aiClientOnce     sync.Once
)

// GetAIClient 获取AI客户端单例
func GetAIClient() *AIClient {
	aiClientOnce.Do(func() {
		aiClientInstance = &AIClient{
			httpClient: &http.Client{
				Timeout: 30 * time.Second,
			},
		}
	})
	return aiClientInstance
}

// Init 初始化AI客户端
func (ac *AIClient) Init(cfg *config.Config) {
	ac.config = cfg
	logger.Log.Info("AI客户端已初始化")
}

// Chat 发送聊天请求
func (ac *AIClient) Chat(messages []ChatMessage, stream bool) (*ChatResponse, error) {
	if ac.config == nil {
		return nil, fmt.Errorf("AI客户端未初始化")
	}

	request := ChatRequest{
		Model:       ac.config.OpenAI.Model,
		Messages:    messages,
		Temperature: 0.7,
		MaxTokens:   1000,
		Stream:      stream,
	}

	requestBody, err := json.Marshal(request)
	if err != nil {
		return nil, fmt.Errorf("序列化请求失败: %v", err)
	}

	// 构建HTTP请求
	req, err := http.NewRequest("POST", ac.config.OpenAI.BaseURL+"/v1/chat/completions", bytes.NewBuffer(requestBody))
	if err != nil {
		return nil, fmt.Errorf("创建HTTP请求失败: %v", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+ac.config.OpenAI.APIKey)

	// 发送请求
	resp, err := ac.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("发送HTTP请求失败: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP请求失败，状态码: %d", resp.StatusCode)
	}

	// 解析响应
	var response ChatResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("解析响应失败: %v", err)
	}

	return &response, nil
}

// TranscribeAudio 转录音频
func (ac *AIClient) TranscribeAudio(audioData []byte, language string) (string, error) {
	if ac.config == nil {
		return "", fmt.Errorf("AI客户端未初始化")
	}

	// 这里应该实现音频转录逻辑
	// 暂时返回模拟结果
	logger.Log.Info("音频转录功能待实现")
	return "这是音频转录的文本", nil
}

// GenerateText 生成文本
func (ac *AIClient) GenerateText(prompt string, maxTokens int) (string, error) {
	messages := []ChatMessage{
		{
			Role:    "user",
			Content: prompt,
		},
	}

	response, err := ac.Chat(messages, false)
	if err != nil {
		return "", err
	}

	if len(response.Choices) > 0 {
		return response.Choices[0].Message.Content, nil
	}

	return "", fmt.Errorf("未收到有效响应")
}

// StreamChat 流式聊天
func (ac *AIClient) StreamChat(messages []ChatMessage, callback func(string) error) error {
	// 这里应该实现流式聊天逻辑
	// 暂时使用非流式方式
	response, err := ac.Chat(messages, false)
	if err != nil {
		return err
	}

	if len(response.Choices) > 0 {
		content := response.Choices[0].Message.Content
		// 模拟流式输出
		for i := 0; i < len(content); i += 10 {
			end := i + 10
			if end > len(content) {
				end = len(content)
			}
			chunk := content[i:end]
			if err := callback(chunk); err != nil {
				return err
			}
			time.Sleep(100 * time.Millisecond)
		}
	}

	return nil
}

// GetModels 获取可用模型列表
func (ac *AIClient) GetModels() ([]string, error) {
	if ac.config == nil {
		return nil, fmt.Errorf("AI客户端未初始化")
	}

	// 这里应该实现获取模型列表的逻辑
	// 暂时返回默认模型
	return []string{ac.config.OpenAI.Model}, nil
}

// HealthCheck 健康检查
func (ac *AIClient) HealthCheck() error {
	if ac.config == nil {
		return fmt.Errorf("AI客户端未初始化")
	}

	// 发送简单的测试请求
	messages := []ChatMessage{
		{
			Role:    "user",
			Content: "Hello",
		},
	}

	_, err := ac.Chat(messages, false)
	return err
}
