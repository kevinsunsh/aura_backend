package tool

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"aura-backend/internal/logger"
	"aura-backend/internal/protocol"
)

// VADLocal VAD客户端，继承自BaseClient
type VADLocal struct {
	*BaseClient
	inputQueue         chan map[string]interface{}
	prepostInputQueues chan map[string]interface{}
	asrIsStarted       *bool
	asrLock            *sync.Mutex
	outputClientQueue  chan map[string]interface{}
	isProcessRunning   *bool
	processTimer       *time.Time
	pythonWrapper      *PythonWrapper
}

// NewVADLocal 创建新的VADLocal实例
func NewVADLocal(
	inputQueue chan map[string]interface{},
	prepostInputQueues chan map[string]interface{},
	asrIsStarted *bool,
	asrLock *sync.Mutex,
	outputClientQueue chan map[string]interface{},
	isProcessRunning *bool,
	processTimer *time.Time,
	pythonWrapper *PythonWrapper,
) *VADLocal {
	vadLocal := &VADLocal{
		inputQueue:         inputQueue,
		prepostInputQueues: prepostInputQueues,
		asrIsStarted:       asrIsStarted,
		asrLock:            asrLock,
		outputClientQueue:  outputClientQueue,
		isProcessRunning:   isProcessRunning,
		processTimer:       processTimer,
		pythonWrapper:      pythonWrapper,
	}

	// 创建BaseClient并传递VADLocal作为接口
	vadLocal.BaseClient = NewBaseClient(vadLocal)
	return vadLocal
}

// StartWorker 重写父类的StartWorker方法
func (v *VADLocal) StartWorker() {
	go v.ConsumerWorker(v.workerCtx, v.internalInputQueue, v.internalOutputQueue)
}

// ConsumerWorker 常驻worker goroutine：负责音频处理
func (v *VADLocal) ConsumerWorker(ctx context.Context, inputQueue <-chan interface{}, outputQueue chan<- ServerResponse) {
	logger.Log.Info("VAD ConsumerWorker 开始")
	defer logger.Log.Info("VAD ConsumerWorker 结束")

	// 初始化VAD引擎
	var vadEngine interface{}

	for {
		select {
		case <-ctx.Done():
			logger.Log.Info("VAD ConsumerWorker 被取消")
			return
		case msg, ok := <-inputQueue:
			if !ok {
				logger.Log.Info("VAD 输入队列已关闭")
				return
			}

			// 处理消息
			if msgMap, ok := msg.(map[string]interface{}); ok {
				if msgType, exists := msgMap["type"].(string); exists {
					switch msgType {
					case "start":
						// 启动VAD引擎
						modelPath := filepath.Join(filepath.Dir(os.Args[0]), "src_go", "internal", "tool", "model", "vad")
						vadEngine = v.startVADEngine(modelPath)
						if vadEngine != nil {
							*v.isProcessRunning = true
							logger.Log.Info("VAD引擎启动成功")
						}
					case "stop":
						// 停止VAD引擎
						v.stopVADEngine(vadEngine)
						*v.isProcessRunning = false
						logger.Log.Info("VAD引擎停止")
					case "input":
						// 处理音频输入
						if *v.isProcessRunning && vadEngine != nil {
							if data, exists := msgMap["data"]; exists {
								if audioData, ok := data.([]byte); ok {
									result := v.processAudioChunk(vadEngine, audioData)
									if result != nil {
										outputQueue <- ServerResponse{"result": result}
									}
								} else {
									logger.Log.Warn("音频数据类型不是[]byte")
								}
							}
						}
					}
				}
			}
		}
	}
}

// HandleServerResponse 处理服务器响应
func (v *VADLocal) HandleServerResponse(response ServerResponse) {
	logger.Log.Debugf("VAD处理服务器响应: %v", response)

	// 解析响应数据
	if result, exists := response["result"]; exists {
		if resultSlice, ok := result.([]interface{}); ok && len(resultSlice) > 0 {
			if firstResult, ok := resultSlice[0].([]interface{}); ok && len(firstResult) > 0 {
				if innerResult, ok := firstResult[0].([]interface{}); ok && len(innerResult) > 0 {
					if vadResult, ok := innerResult[0].(float64); ok {
						if vadResult == -1 {
							// VAD识别结束
							v.asrLock.Lock()
							if *v.asrIsStarted {
								*v.asrIsStarted = false
								v.asrLock.Unlock()

								// 发送ASR结束事件
								v.outputClientQueue <- map[string]interface{}{
									"event": fmt.Sprintf("%d", protocol.ServerEventASREnded),
								}

								// 发送预处理事件
								v.prepostInputQueues <- map[string]interface{}{
									"type": "preprocess",
								}

								// 更新处理计时器
								now := time.Now()
								*v.processTimer = now

								logger.Log.Info("VAD识别结束")
							} else {
								v.asrLock.Unlock()
								logger.Log.Warn("VAD识别结束，但ASR未开始")
							}
						}
					}
				}
			}
		}
	}
}

// startVADEngine 启动VAD引擎（调用Python）
func (v *VADLocal) startVADEngine(modelPath string) interface{} {
	if v.pythonWrapper == nil {
		logger.Log.Error("Python包装器未初始化")
		return nil
	}

	result, err := v.pythonWrapper.CallPythonFunction("start_vad_engine", modelPath)
	if err != nil {
		logger.Log.Errorf("启动VAD引擎失败: %v", err)
		return nil
	}

	logger.Log.Infof("VAD引擎启动成功: %v", result)
	return result.Data
}

// stopVADEngine 停止VAD引擎（调用Python）
func (v *VADLocal) stopVADEngine(engine interface{}) {
	if v.pythonWrapper == nil || engine == nil {
		return
	}

	_, err := v.pythonWrapper.CallPythonFunction("stop_vad_engine")
	if err != nil {
		logger.Log.Errorf("停止VAD引擎失败: %v", err)
	}

	logger.Log.Info("VAD引擎停止")
}

// processAudioChunk 处理音频数据块（调用Python）
func (v *VADLocal) processAudioChunk(engine interface{}, audioData []byte) interface{} {
	if v.pythonWrapper == nil || engine == nil {
		return nil
	}

	result, err := v.pythonWrapper.CallPythonFunction("process_audio_chunk", audioData)
	if err != nil {
		logger.Log.Errorf("处理音频数据块失败: %v", err)
		return nil
	}

	return result.Data
}

// Start 启动VAD客户端
func (v *VADLocal) Start(chatID, userID string) bool {
	logger.Log.Infof("启动VAD客户端: chat_id=%s, user_id=%s", chatID, userID)

	// 调用父类的Start方法
	if !v.BaseClient.Start(chatID, userID) {
		return false
	}

	// 发送启动消息到worker
	v.SendToWorker(map[string]interface{}{
		"type": "start",
	})

	// 等待worker启动
	for !*v.isProcessRunning {
		time.Sleep(100 * time.Millisecond)
	}

	logger.Log.Info("VAD客户端启动成功")
	return true
}

// Cleanup 清理资源
func (v *VADLocal) Cleanup() {
	logger.Log.Info("开始清理VAD客户端资源")

	// 发送停止消息到worker
	v.SendToWorker(map[string]interface{}{
		"type": "stop",
	})

	// 等待worker停止
	for *v.isProcessRunning {
		time.Sleep(100 * time.Millisecond)
	}

	// 调用父类的Cleanup方法
	v.BaseClient.Cleanup()

	logger.Log.Info("VAD客户端资源清理完成")
}

// ProcessInput 处理输入数据
func (v *VADLocal) ProcessInput(data interface{}) {
	if *v.isProcessRunning {
		v.SendToWorker(map[string]interface{}{
			"type": "input",
			"data": data,
		})
	}
}

// IsRunning 检查是否正在运行
func (v *VADLocal) IsRunning() bool {
	return *v.isProcessRunning
}

// GetASRStatus 获取ASR状态
func (v *VADLocal) GetASRStatus() bool {
	v.asrLock.Lock()
	defer v.asrLock.Unlock()
	return *v.asrIsStarted
}

// SetASRStatus 设置ASR状态
func (v *VADLocal) SetASRStatus(status bool) {
	v.asrLock.Lock()
	defer v.asrLock.Unlock()
	*v.asrIsStarted = status
}
