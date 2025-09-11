package message

import (
	"aura-backend/internal/ai"
	"aura-backend/internal/logger"
	"aura-backend/internal/protocol"
	"context"
	"fmt"
	"sync"
	"time"
)

// MessageHandler 消息处理函数类型
type MessageHandler func(message interface{}) error

// WorkerMessage 工作线程消息类型
type WorkerMessage struct {
	Type string      `json:"type"`
	Data interface{} `json:"data"`
}

// WorkerStatus 工作线程状态
type WorkerStatus struct {
	IsRunning bool
	mu        sync.RWMutex
}

func (ws *WorkerStatus) SetRunning(running bool) {
	ws.mu.Lock()
	defer ws.mu.Unlock()
	ws.IsRunning = running
}

func (ws *WorkerStatus) GetRunning() bool {
	ws.mu.RLock()
	defer ws.mu.RUnlock()
	return ws.IsRunning
}

// MessageProcessor 多线程消息处理器
type MessageProcessor struct {
	mu            sync.RWMutex
	handlers      map[string]MessageHandler
	aiClient      *ai.AIClient
	currentChatID string
	currentUserID string
	sendCallback  func(interface{}) error
	isActive      bool
	// 多线程相关
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
	// 消息通道
	// vadInputChan     chan WorkerMessage
	// asrInputChan     chan WorkerMessage
	llmInputChan     chan WorkerMessage
	ttsInputChan     chan WorkerMessage
	e2eInputChan     chan WorkerMessage
	prepostInputChan chan WorkerMessage
	outputChan       chan interface{}
	// 工作线程状态
	// vadStatus WorkerStatus
	// asrStatus     WorkerStatus // ASR工作器被注释掉
	llmStatus     WorkerStatus
	ttsStatus     WorkerStatus
	e2eStatus     WorkerStatus
	prepostStatus WorkerStatus

	// 共享状态
	asrResult    string
	asrStarted   bool
	asrLock      sync.Mutex
	processTimer time.Time
}

var (
	messageProcessorInstance *MessageProcessor
	messageProcessorOnce     sync.Once
)

// GetMessageProcessor 获取消息处理器单例
func GetMessageProcessor() *MessageProcessor {
	messageProcessorOnce.Do(func() {
		ctx, cancel := context.WithCancel(context.Background())
		messageProcessorInstance = &MessageProcessor{
			handlers: make(map[string]MessageHandler),
			aiClient: ai.GetAIClient(),
			ctx:      ctx,
			cancel:   cancel,
			// 初始化通道
			// vadInputChan:     make(chan WorkerMessage, 100),
			// asrInputChan:     make(chan WorkerMessage, 100),
			llmInputChan:     make(chan WorkerMessage, 100),
			ttsInputChan:     make(chan WorkerMessage, 100),
			e2eInputChan:     make(chan WorkerMessage, 100),
			prepostInputChan: make(chan WorkerMessage, 100),
			outputChan:       make(chan interface{}, 1000),
		}
	})
	return messageProcessorInstance
}

// Start 启动消息处理器
func (mp *MessageProcessor) Start(chatID, userID string, sendCallback func(interface{}) error) error {
	mp.mu.Lock()
	defer mp.mu.Unlock()

	mp.currentChatID = chatID
	mp.currentUserID = userID
	mp.sendCallback = sendCallback
	mp.isActive = true
	// 启动所有工作线程
	mp.startWorkers()

	logger.Log.Infof("消息处理器已启动: chat_id=%s, user_id=%s", chatID, userID)
	return nil
}

// Stop 停止消息处理器
func (mp *MessageProcessor) Stop() {
	mp.mu.Lock()
	defer mp.mu.Unlock()

	mp.isActive = false
	mp.currentChatID = ""
	mp.currentUserID = ""
	mp.sendCallback = nil

	// 停止所有工作线程
	mp.stopWorkers()

	logger.Log.Info("消息处理器已停止")
}

// HandleMessage 处理消息
func (mp *MessageProcessor) HandleMessage(msg *protocol.Message) (map[string]interface{}, error) {
	mp.mu.RLock()
	if !mp.isActive {
		mp.mu.RUnlock()
		return nil, fmt.Errorf("消息处理器未启动")
	}
	mp.mu.RUnlock()

	// 根据消息类型分发到不同的工作器
	switch msg.Event {
	case fmt.Sprintf("%d", protocol.ClientEventSayHello):
		return mp.handleSayHello(msg)
	case fmt.Sprintf("%d", protocol.ClientEventTaskRequest):
		return mp.handleTaskRequest(msg)
	case fmt.Sprintf("%d", protocol.ClientEventSpeakEnded):
		return mp.handleSpeakEnded(msg)
	case fmt.Sprintf("%d", protocol.ClientEventWorldInfoActivateKeys):
		return mp.handleWorldInfoActivateKeys(msg)
	case fmt.Sprintf("%d", protocol.ClientEventChangeBotID):
		return mp.handleChangeBotID(msg)
	case fmt.Sprintf("%d", protocol.ClientEventChangeSystemPreset):
		return mp.handleChangeSystemPreset(msg)
	default:
		// 使用注册的处理器
		handler, exists := mp.handlers[msg.Event]
		if !exists {
			logger.Log.Warnf("未找到消息处理器: %s", msg.Event)
			return nil, fmt.Errorf("未找到消息处理器: %s", msg.Event)
		}
		err := handler(msg)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{
			"success": true,
			"action":  "message_processed",
			"chat_id": mp.currentChatID,
		}, nil
	}
}

// handleSayHello 处理问候消息
func (mp *MessageProcessor) handleSayHello(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理SayHello消息")

	// 发送预处理消息
	mp.prepostInputChan <- WorkerMessage{
		Type: "preprocess",
		Data: nil,
	}

	// 设置ASR结果 (与Python版本保持一致，使用payload_msg)
	if payload, ok := msg.Payload.(map[string]interface{}); ok {
		if content, exists := payload["content"]; exists {
			mp.asrResult = fmt.Sprintf("%v", content)
		}
	}

	mp.processTimer = time.Now()
	logger.Log.Info("SayHello处理完成")

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// handleTaskRequest 处理任务请求
func (mp *MessageProcessor) handleTaskRequest(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理TaskRequest消息")

	if msg.Payload == nil {
		return map[string]interface{}{
			"success": false,
			"error":   "payload_msg is required",
		}, nil
	}
	// 发送到E2E工作器
	mp.e2eInputChan <- WorkerMessage{
		Type: "input",
		Data: msg.Payload,
	}

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// atomicCompareAndSet 原子操作：比较并设置值
func (mp *MessageProcessor) atomicCompareAndSet(expected, new bool) bool {
	mp.asrLock.Lock()
	defer mp.asrLock.Unlock()

	if mp.asrStarted == expected {
		mp.asrStarted = new
		return true
	}
	return false
}

// handleSpeakEnded 处理说话结束
func (mp *MessageProcessor) handleSpeakEnded(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理SpeakEnded消息")

	// 使用原子操作：从True设置为False (与Python版本保持一致)
	if mp.atomicCompareAndSet(true, false) {
		// 原子操作成功：从True设置为False

		// 发送ASR结束事件
		mp.outputChan <- map[string]interface{}{
			"event": fmt.Sprintf("%d", protocol.ServerEventASREnded),
		}

		// 发送预处理消息
		mp.prepostInputChan <- WorkerMessage{
			Type: "preprocess",
			Data: nil,
		}

		mp.processTimer = time.Now()
		logger.Log.Info("SpeakEnded处理完成")
	} else {
		logger.Log.Info("SpeakEnded，但ASR未开始")
	}

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// handleWorldInfoActivateKeys 处理世界信息激活键
func (mp *MessageProcessor) handleWorldInfoActivateKeys(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理WorldInfoActivateKeys消息")

	if payload, ok := msg.Payload.(map[string]interface{}); ok {
		if keys, exists := payload["activate_keys"]; exists {
			mp.prepostInputChan <- WorkerMessage{
				Type: "change_world_info_activate_keys",
				Data: keys,
			}
		}
	}

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// handleChangeBotID 处理机器人ID变更
func (mp *MessageProcessor) handleChangeBotID(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理ChangeBotID消息")

	if payload, ok := msg.Payload.(map[string]interface{}); ok {
		if botName, exists := payload["bot_name"]; exists {
			mp.prepostInputChan <- WorkerMessage{
				Type: "change_bot_name",
				Data: botName,
			}
		}
	}

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// handleChangeSystemPreset 处理系统预设变更
func (mp *MessageProcessor) handleChangeSystemPreset(msg *protocol.Message) (map[string]interface{}, error) {
	logger.Log.Info("处理ChangeSystemPreset消息")

	if payload, ok := msg.Payload.(map[string]interface{}); ok {
		if preset, exists := payload["system_preset"]; exists {
			mp.prepostInputChan <- WorkerMessage{
				Type: "change_system_preset",
				Data: preset,
			}
		}
	}

	return map[string]interface{}{
		"success": true,
		"action":  "audio_task_started",
		"chat_id": mp.currentChatID,
	}, nil
}

// GetStats 获取统计信息
func (mp *MessageProcessor) GetStats() map[string]interface{} {
	mp.mu.RLock()
	defer mp.mu.RUnlock()

	return map[string]interface{}{
		"is_active":       mp.isActive,
		"current_chat_id": mp.currentChatID,
		"current_user_id": mp.currentUserID,
		// "asr_running":     mp.asrStatus.GetRunning(), // ASR工作器被注释掉
		"llm_running":     mp.llmStatus.GetRunning(),
		"tts_running":     mp.ttsStatus.GetRunning(),
		"e2e_running":     mp.e2eStatus.GetRunning(),
		"prepost_running": mp.prepostStatus.GetRunning(),
		"asr_result":      mp.asrResult,
		"asr_started":     mp.asrStarted,
	}
}

// StartAllWorkers 启动所有工作器
func (mp *MessageProcessor) StartAllWorkers(chatID, userID string) error {
	logger.Log.Infof("启动所有工作器: chat_id=%s, user_id=%s", chatID, userID)

	// 启动VAD客户端
	// if mp.vadClient != nil {
	// 	success := mp.vadClient.Start(chatID, userID)
	// 	if success {
	// 		mp.vadStatus.SetRunning(true)
	// 		logger.Log.Info("VAD客户端启动成功")
	// 	} else {
	// 		logger.Log.Error("VAD客户端启动失败")
	// 	}
	// }

	// ASR工作器被注释掉，与Python版本保持一致
	// mp.asrInputChan <- WorkerMessage{
	// 	Type: "start",
	// 	Data: map[string]interface{}{
	// 		"chat_id": chatID,
	// 		"user_id": userID,
	// 	},
	// }

	// 启动LLM工作器
	mp.llmInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": chatID,
			"user_id": userID,
		},
	}

	// 启动TTS工作器
	mp.ttsInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": chatID,
			"user_id": userID,
		},
	}

	// 启动E2E工作器
	mp.e2eInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": chatID,
			"user_id": userID,
		},
	}

	// 启动预处理工作器
	mp.prepostInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": chatID,
			"user_id": userID,
		},
	}

	// 等待所有工作器启动
	timeout := 20 * time.Second
	startTime := time.Now()

	for time.Since(startTime) < timeout {
		// if mp.vadStatus.GetRunning() &&
		// mp.asrStatus.GetRunning() && // ASR工作器被注释掉
		if mp.llmStatus.GetRunning() &&
			mp.ttsStatus.GetRunning() &&
			mp.e2eStatus.GetRunning() &&
			mp.prepostStatus.GetRunning() {
			logger.Log.Info("所有工作器启动完成")
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	logger.Log.Error("工作器启动超时")
	return fmt.Errorf("工作器启动超时")
}

// StopAllWorkers 停止所有工作器
func (mp *MessageProcessor) StopAllWorkers() {
	logger.Log.Info("停止所有工作器")

	// 停止VAD客户端
	// if mp.vadClient != nil {
	// 	mp.vadClient.Cleanup()
	// 	mp.vadStatus.SetRunning(false)
	// 	logger.Log.Info("VAD客户端已停止")
	// }

	// ASR工作器被注释掉，与Python版本保持一致
	// mp.asrInputChan <- WorkerMessage{Type: "stop", Data: nil}

	// 停止LLM工作器
	mp.llmInputChan <- WorkerMessage{Type: "stop", Data: nil}

	// 停止TTS工作器
	mp.ttsInputChan <- WorkerMessage{Type: "stop", Data: nil}

	// 停止E2E工作器
	mp.e2eInputChan <- WorkerMessage{Type: "stop", Data: nil}

	// 停止预处理工作器
	mp.prepostInputChan <- WorkerMessage{Type: "stop", Data: nil}

	// 等待所有工作器停止
	timeout := 10 * time.Second
	startTime := time.Now()

	for time.Since(startTime) < timeout {
		// if !mp.vadStatus.GetRunning() &&
		// !mp.asrStatus.GetRunning() && // ASR工作器被注释掉
		if !mp.llmStatus.GetRunning() &&
			!mp.ttsStatus.GetRunning() &&
			!mp.e2eStatus.GetRunning() &&
			!mp.prepostStatus.GetRunning() {
			logger.Log.Info("所有工作器停止完成")
			return
		}
		time.Sleep(100 * time.Millisecond)
	}

	logger.Log.Warn("工作器停止超时")
}

// ProcessTextMessage 处理文本消息
func (mp *MessageProcessor) ProcessTextMessage(sessionID, content string) error {
	logger.Log.Infof("处理文本消息: sessionID=%s, content=%s", sessionID, content)

	// 这里可以添加实际的文本处理逻辑
	// 例如：调用AI服务、保存到数据库等

	// 模拟处理成功
	return nil
}

// ProcessAudioMessage 处理音频消息
func (mp *MessageProcessor) ProcessAudioMessage(sessionID string, audioData []byte) error {
	logger.Log.Infof("处理音频消息: sessionID=%s, 音频大小=%d字节", sessionID, len(audioData))

	// 这里可以添加实际的音频处理逻辑
	// 例如：调用ASR服务、音频转文本等

	// 模拟处理成功
	return nil
}

// startWorkers 启动所有工作线程
func (mp *MessageProcessor) startWorkers() {
	logger.Log.Info("启动多线程工作器")

	// VAD使用VADLocal客户端，不需要单独的worker
	// mp.wg.Add(1)
	// go mp.vadWorker()

	// ASR工作器被注释掉，与Python版本保持一致
	// mp.wg.Add(1)
	// go mp.asrWorker()

	// 启动LLM工作器
	mp.wg.Add(1)
	go mp.llmWorker()

	// 启动TTS工作器
	mp.wg.Add(1)
	go mp.ttsWorker()

	// 启动E2E工作器
	mp.wg.Add(1)
	go mp.e2eWorker()

	// 启动预处理工作器
	mp.wg.Add(1)
	go mp.prepostWorker()

	// 启动输出消息处理工作器
	mp.wg.Add(1)
	go mp.outputWorker()

	// 发送启动消息给各个工作器
	mp.sendWorkerStartMessages()

	logger.Log.Info("所有工作器已启动")
}

// sendWorkerStartMessages 发送启动消息给各个工作器
func (mp *MessageProcessor) sendWorkerStartMessages() {
	// 启动VAD客户端
	// if mp.vadClient != nil {
	// 	success := mp.vadClient.Start(mp.currentChatID, mp.currentUserID)
	// 	if success {
	// 		mp.vadStatus.SetRunning(true)
	// 		logger.Log.Info("VAD客户端启动成功")
	// 	} else {
	// 		logger.Log.Error("VAD客户端启动失败")
	// 	}
	// }

	// 启动LLM工作器
	mp.llmInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": mp.currentChatID,
			"user_id": mp.currentUserID,
		},
	}

	// 启动TTS工作器
	mp.ttsInputChan <- WorkerMessage{
		Type: "start",
		Data: map[string]interface{}{
			"chat_id": mp.currentChatID,
			"user_id": mp.currentUserID,
		},
	}

	logger.Log.Info("已发送工作器启动消息")
}

// stopWorkers 停止所有工作线程
func (mp *MessageProcessor) stopWorkers() {
	logger.Log.Info("停止多线程工作器")

	// 取消上下文，通知所有工作器停止
	mp.cancel()

	// 等待所有工作器完成
	mp.wg.Wait()

	logger.Log.Info("所有工作器已停止")
}

// vadWorker VAD工作器 - 已移除，直接使用VADLocal客户端

// asrWorker ASR工作器 (已注释，与Python版本保持一致)
// func (mp *MessageProcessor) asrWorker() {
// 	defer mp.wg.Done()
// 	logger.Log.Info("ASR工作器启动")
//
// 	for {
// 		select {
// 		case <-mp.ctx.Done():
// 			logger.Log.Info("ASR工作器停止")
// 			return
// 		case msg := <-mp.asrInputChan:
// 			mp.processASRMessage(msg)
// 		}
// 	}
// }

// llmWorker LLM工作器
func (mp *MessageProcessor) llmWorker() {
	defer mp.wg.Done()
	logger.Log.Info("LLM工作器启动")

	for {
		select {
		case <-mp.ctx.Done():
			logger.Log.Info("LLM工作器停止")
			return
		case msg := <-mp.llmInputChan:
			mp.processLLMMessage(msg)
		}
	}
}

// ttsWorker TTS工作器
func (mp *MessageProcessor) ttsWorker() {
	defer mp.wg.Done()
	logger.Log.Info("TTS工作器启动")

	for {
		select {
		case <-mp.ctx.Done():
			logger.Log.Info("TTS工作器停止")
			return
		case msg := <-mp.ttsInputChan:
			mp.processTTSMessage(msg)
		}
	}
}

// e2eWorker E2E工作器
func (mp *MessageProcessor) e2eWorker() {
	defer mp.wg.Done()
	logger.Log.Info("E2E工作器启动")

	for {
		select {
		case <-mp.ctx.Done():
			logger.Log.Info("E2E工作器停止")
			return
		case msg := <-mp.e2eInputChan:
			mp.processE2EMessage(msg)
		}
	}
}

// prepostWorker 预处理工作器
func (mp *MessageProcessor) prepostWorker() {
	defer mp.wg.Done()
	logger.Log.Info("预处理工作器启动")

	for {
		select {
		case <-mp.ctx.Done():
			logger.Log.Info("预处理工作器停止")
			return
		case msg := <-mp.prepostInputChan:
			mp.processPrepostMessage(msg)
		}
	}
}

// outputWorker 输出消息处理工作器
func (mp *MessageProcessor) outputWorker() {
	defer mp.wg.Done()
	logger.Log.Info("输出工作器启动")

	for {
		select {
		case <-mp.ctx.Done():
			logger.Log.Info("输出工作器停止")
			return
		case msg := <-mp.outputChan:
			mp.processOutputMessage(msg)
		}
	}
}

// Cleanup 清理资源
func (mp *MessageProcessor) Cleanup() error {
	logger.Log.Info("清理消息处理器资源")

	// 停止处理器
	mp.Stop()

	// 清理其他资源
	mp.mu.Lock()
	mp.handlers = make(map[string]MessageHandler)
	mp.mu.Unlock()

	return nil
}

// processVADMessage 处理VAD消息 - 已移除，直接使用VADLocal客户端

// processASRMessage 处理ASR消息 (已注释，与Python版本保持一致)
// func (mp *MessageProcessor) processASRMessage(msg WorkerMessage) {
// 	logger.Log.Debugf("处理ASR消息: %s", msg.Type)
//
// 	switch msg.Type {
// 	case "start":
// 		mp.asrStatus.SetRunning(true)
// 		logger.Log.Info("ASR工作器启动")
// 	case "stop":
// 		mp.asrStatus.SetRunning(false)
// 		logger.Log.Info("ASR工作器停止")
// 	case "input":
// 		if mp.asrStatus.GetRunning() {
// 			// 处理音频输入
// 			logger.Log.Debugf("ASR处理音频输入: %v", msg.Data)
// 			// 这里应该调用实际的ASR处理逻辑
// 		}
// 	}
// }

// processLLMMessage 处理LLM消息
func (mp *MessageProcessor) processLLMMessage(msg WorkerMessage) {
	logger.Log.Debugf("处理LLM消息: %s", msg.Type)

	switch msg.Type {
	case "start":
		mp.llmStatus.SetRunning(true)
		logger.Log.Info("LLM工作器启动")
	case "stop":
		mp.llmStatus.SetRunning(false)
		logger.Log.Info("LLM工作器停止")
	case "run":
		if mp.llmStatus.GetRunning() {
			// 处理LLM请求
			logger.Log.Debugf("LLM处理请求: %v", msg.Data)
			// 这里应该调用实际的LLM处理逻辑
		}
	case "interruption":
		if mp.llmStatus.GetRunning() {
			logger.Log.Info("LLM收到中断信号")
			// 处理中断逻辑
		}
	}
}

// processTTSMessage 处理TTS消息
func (mp *MessageProcessor) processTTSMessage(msg WorkerMessage) {
	logger.Log.Debugf("处理TTS消息: %s", msg.Type)

	switch msg.Type {
	case "start":
		mp.ttsStatus.SetRunning(true)
		logger.Log.Info("TTS工作器启动")
	case "stop":
		mp.ttsStatus.SetRunning(false)
		logger.Log.Info("TTS工作器停止")
	case "tts_start":
		if mp.ttsStatus.GetRunning() {
			logger.Log.Debugf("TTS开始合成: %v", msg.Data)
			// 这里应该调用实际的TTS处理逻辑
		}
	case "tts_content":
		if mp.ttsStatus.GetRunning() {
			logger.Log.Debugf("TTS处理内容: %v", msg.Data)
			// 这里应该调用实际的TTS处理逻辑
		}
	case "tts_end":
		if mp.ttsStatus.GetRunning() {
			logger.Log.Debugf("TTS结束合成: %v", msg.Data)
			// 这里应该调用实际的TTS处理逻辑
		}
	}
}

// processE2EMessage 处理E2E消息
func (mp *MessageProcessor) processE2EMessage(msg WorkerMessage) {
	logger.Log.Debugf("处理E2E消息: %s", msg.Type)

	switch msg.Type {
	case "start":
		mp.e2eStatus.SetRunning(true)
		logger.Log.Info("E2E工作器启动")
	case "stop":
		mp.e2eStatus.SetRunning(false)
		logger.Log.Info("E2E工作器停止")
	case "input":
		if mp.e2eStatus.GetRunning() {
			// 处理端到端音频输入
			logger.Log.Debugf("E2E处理音频输入: %v", msg.Data)
			// 这里应该调用实际的E2E处理逻辑
		}
	}
}

// processPrepostMessage 处理预处理消息
func (mp *MessageProcessor) processPrepostMessage(msg WorkerMessage) {
	logger.Log.Debugf("处理预处理消息: %s", msg.Type)

	switch msg.Type {
	case "start":
		mp.prepostStatus.SetRunning(true)
		logger.Log.Info("预处理工作器启动")
	case "stop":
		mp.prepostStatus.SetRunning(false)
		logger.Log.Info("预处理工作器停止")
	case "preprocess":
		if mp.prepostStatus.GetRunning() {
			logger.Log.Debugf("预处理数据: %v", msg.Data)
			// 这里应该调用实际的预处理逻辑
		}
	case "postprocess":
		if mp.prepostStatus.GetRunning() {
			logger.Log.Debugf("后处理数据: %v", msg.Data)
			// 这里应该调用实际的后处理逻辑
		}
	}
}

// processOutputMessage 处理输出消息
func (mp *MessageProcessor) processOutputMessage(msg interface{}) {
	logger.Log.Debugf("处理输出消息: %v", msg)

	// 如果有发送回调函数，则调用它
	if mp.sendCallback != nil {
		if err := mp.sendCallback(msg); err != nil {
			logger.Log.Errorf("发送消息失败: %v", err)
		}
	}
}

// SendSSEMessage 发送SSE消息（用于兼容性）
func (mp *MessageProcessor) SendSSEMessage() {
	// 这里可以实现SSE消息发送逻辑
	logger.Log.Info("SSE消息发送功能待实现")
}
