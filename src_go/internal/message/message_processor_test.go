package message

import (
	"aura-backend/internal/protocol"
	"testing"
	"time"
)

func TestMessageProcessorMultiThreading(t *testing.T) {
	// 获取消息处理器实例
	mp := GetMessageProcessor()

	// 测试回调函数
	var receivedMessages []interface{}
	sendCallback := func(msg interface{}) error {
		receivedMessages = append(receivedMessages, msg)
		return nil
	}

	// 启动消息处理器
	err := mp.Start("test_chat_001", "test_user_001", sendCallback)
	if err != nil {
		t.Fatalf("启动消息处理器失败: %v", err)
	}

	// 启动所有工作器
	err = mp.StartAllWorkers("test_chat_001", "test_user_001")
	if err != nil {
		t.Fatalf("启动工作器失败: %v", err)
	}

	// 等待工作器启动
	time.Sleep(100 * time.Millisecond)

	// 测试SayHello消息
	sayHelloMsg := &protocol.Message{
		Event:  "300", // ClientEventSayHello
		ChatID: "test_chat_001",
		UserID: "test_user_001",
		Payload: map[string]interface{}{
			"content": "你好",
		},
	}

	result, err := mp.HandleMessage(sayHelloMsg)
	if err != nil {
		t.Errorf("处理SayHello消息失败: %v", err)
	}
	if result == nil || !result["success"].(bool) {
		t.Errorf("SayHello消息处理结果不正确: %v", result)
	}

	// 测试TaskRequest消息
	taskRequestMsg := &protocol.Message{
		Event:   "200", // ClientEventTaskRequest
		ChatID:  "test_chat_001",
		UserID:  "test_user_001",
		Payload: []byte("test audio data"),
	}

	result, err = mp.HandleMessage(taskRequestMsg)
	if err != nil {
		t.Errorf("处理TaskRequest消息失败: %v", err)
	}
	if result == nil || !result["success"].(bool) {
		t.Errorf("TaskRequest消息处理结果不正确: %v", result)
	}

	// 测试SpeakEnded消息
	speakEndedMsg := &protocol.Message{
		Event:  "600", // ClientEventSpeakEnded
		ChatID: "test_chat_001",
		UserID: "test_user_001",
	}

	result, err = mp.HandleMessage(speakEndedMsg)
	if err != nil {
		t.Errorf("处理SpeakEnded消息失败: %v", err)
	}
	if result == nil || !result["success"].(bool) {
		t.Errorf("SpeakEnded消息处理结果不正确: %v", result)
	}

	// 等待消息处理
	time.Sleep(200 * time.Millisecond)

	// 检查统计信息
	stats := mp.GetStats()
	if !stats["is_active"].(bool) {
		t.Error("消息处理器应该处于活跃状态")
	}

	if stats["current_chat_id"].(string) != "test_chat_001" {
		t.Error("聊天ID不匹配")
	}

	if stats["current_user_id"].(string) != "test_user_001" {
		t.Error("用户ID不匹配")
	}

	// 停止所有工作器
	mp.StopAllWorkers()

	// 停止消息处理器
	mp.Stop()

	// 清理资源
	err = mp.Cleanup()
	if err != nil {
		t.Errorf("清理资源失败: %v", err)
	}

	t.Logf("多线程消息处理器测试完成，收到 %d 条消息", len(receivedMessages))
}

func TestWorkerStatus(t *testing.T) {
	mp := GetMessageProcessor()

	// 测试工作器状态
	stats := mp.GetStats()

	// 检查状态字段存在
	requiredFields := []string{
		"vad_running" /* "asr_running", */, "llm_running", // ASR工作器被注释掉
		"tts_running", "e2e_running", "prepost_running",
	}

	for _, field := range requiredFields {
		if _, exists := stats[field]; !exists {
			t.Errorf("统计信息中缺少字段: %s", field)
		}
	}

	t.Log("工作器状态测试完成")
}

func TestMessageChannels(t *testing.T) {
	mp := GetMessageProcessor()

	// 测试消息通道是否正常工作
	testMsg := WorkerMessage{
		Type: "test",
		Data: "test data",
	}

	// 测试非阻塞发送
	select {
	case mp.vadInputChan <- testMsg:
		t.Log("VAD通道发送成功")
	case <-time.After(100 * time.Millisecond):
		t.Error("VAD通道发送超时")
	}

	// ASR工作器被注释掉，与Python版本保持一致
	// select {
	// case mp.asrInputChan <- testMsg:
	// 	t.Log("ASR通道发送成功")
	// case <-time.After(100 * time.Millisecond):
	// 	t.Error("ASR通道发送超时")
	// }

	select {
	case mp.llmInputChan <- testMsg:
		t.Log("LLM通道发送成功")
	case <-time.After(100 * time.Millisecond):
		t.Error("LLM通道发送超时")
	}

	select {
	case mp.ttsInputChan <- testMsg:
		t.Log("TTS通道发送成功")
	case <-time.After(100 * time.Millisecond):
		t.Error("TTS通道发送超时")
	}

	select {
	case mp.e2eInputChan <- testMsg:
		t.Log("E2E通道发送成功")
	case <-time.After(100 * time.Millisecond):
		t.Error("E2E通道发送超时")
	}

	select {
	case mp.prepostInputChan <- testMsg:
		t.Log("预处理通道发送成功")
	case <-time.After(100 * time.Millisecond):
		t.Error("预处理通道发送超时")
	}

	t.Log("消息通道测试完成")
}
