package agent

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	agentmemory "aura-backend/internal/agent/agent_memory"
	"aura-backend/internal/logger"
	"aura-backend/internal/message"
	"aura-backend/internal/protocol"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // 允许所有来源
	},
}

// AuraAgent WebSocket连接管理器 (对应Python版本的AuraAgent类)
type AuraAgent struct {
	instance            *AuraAgent
	websocketConnection *websocket.Conn // 对应Python版本的self.websocket_connection
	lastMessageTime     time.Time       // 对应Python版本的self.last_message_time
	chatStream          interface{}     // 对应Python版本的self.chat_stream
	msgProcessor        *message.MessageProcessor
	pythonWrapper       *agentmemory.PythonWrapper // Python包装器
	mutex               sync.RWMutex
}

var (
	auraAgentInstance *AuraAgent
	auraAgentOnce     sync.Once
)

// getProjectRoot 获取项目根路径
func getProjectRoot() string {
	// 从当前工作目录开始向上查找
	dir, err := os.Getwd()
	if err != nil {
		logger.Log.Errorf("获取当前工作目录失败: %v", err)
		return ""
	}

	// 向上查找，直到找到包含src_go目录的路径
	for {
		srcGoPath := filepath.Join(dir, "src_go")
		if _, err := os.Stat(srcGoPath); err == nil {
			logger.Log.Infof("找到项目根路径: %s", dir)
			return dir
		}

		// 检查是否已经到达根目录
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}

	logger.Log.Errorf("未找到项目根路径")
	return ""
}

// GetInstance 获取AuraAgent单例 (对应Python版本的get_instance())
func GetInstance() *AuraAgent {
	auraAgentOnce.Do(func() {
		// 获取项目根路径 (从当前工作目录向上查找，直到找到包含src_go的目录)
		projectRoot := getProjectRoot()
		auraAgentInstance = &AuraAgent{
			msgProcessor:  message.GetMessageProcessor(),
			pythonWrapper: agentmemory.NewPythonWrapper(projectRoot),
		}
	})
	return auraAgentInstance
}

// NewAuraAgent 创建新的AuraAgent实例 (保留用于测试)
func NewAuraAgent(msgProcessor *message.MessageProcessor) *AuraAgent {
	projectRoot := getProjectRoot()
	return &AuraAgent{
		msgProcessor:  msgProcessor,
		pythonWrapper: agentmemory.NewPythonWrapper(projectRoot),
	}
}

// HandleWebSocket 处理WebSocket连接 (对应Python版本的handle_websocket_connection)
func (a *AuraAgent) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		logger.Log.Errorf("WebSocket升级失败: %v", err)
		return
	}

	logger.Log.Info("开始处理WebSocket连接")

	// 设置WebSocket连接 (对应Python版本的self.websocket_connection = websocket)
	a.websocketConnection = conn
	logger.Log.Info("WebSocket连接已设置")

	// 启动消息处理循环
	go a.handleWebSocketConnection(conn)
}

// handleWebSocketConnection 处理WebSocket连接，包括连接和session生命周期管理 (对应Python版本的handle_websocket_connection)
func (a *AuraAgent) handleWebSocketConnection(conn *websocket.Conn) {
	defer func() {
		// 清理资源 (对应Python版本的finally块)
		a.cleanup()
	}()

	logger.Log.Info("开始处理WebSocket连接")

	// 第一步：等待客户端发送开始连接消息 (对应Python版本的第一步)
	logger.Log.Info("等待客户端发送开始连接消息...")
	if !a.waitForConnectionStart(conn) {
		logger.Log.Error("未收到有效的开始连接消息，关闭连接")
		return
	}

	// 第二步：等待客户端发送开始session消息 (对应Python版本的第二步)
	logger.Log.Info("等待客户端发送开始session消息...")
	if !a.waitForSessionStart(conn) {
		logger.Log.Error("未收到有效的开始session消息，关闭连接")
		return
	}

	// 第三步：进入正常的消息处理循环 (对应Python版本的第三步)
	logger.Log.Info("开始处理session消息")
	a.messageProcessingLoop(conn)

	// 第四步：等待客户端发送session结束和连接结束消息 (对应Python版本的第四步)
	a.waitForGracefulShutdown(conn)
}

// waitForConnectionStart 等待客户端发送开始连接消息 (对应Python版本的_wait_for_connection_start)
func (a *AuraAgent) waitForConnectionStart(conn *websocket.Conn) bool {
	// 设置读取超时
	conn.SetReadDeadline(time.Now().Add(60 * time.Second))

	// 读取消息
	messageType, messageData, err := conn.ReadMessage()
	if err != nil {
		logger.Log.Errorf("读取连接开始消息失败: %v", err)
		return false
	}

	// 只处理二进制协议消息
	if messageType != websocket.BinaryMessage {
		logger.Log.Error("期望收到二进制协议消息")
		return false
	}

	// 解析二进制协议消息
	parsedData := a.parseBinaryProtocolMessage(messageData)

	// 检查是否是开始连接消息
	if parsedData["event"] == fmt.Sprintf("%d", protocol.ClientEventStartConnection) {
		logger.Log.Info("收到开始连接消息")
		// 发送连接确认
		a.sendWebSocketMessage(map[string]interface{}{
			"event":       fmt.Sprintf("%d", protocol.ServerEventConnectionStarted),
			"payload_msg": map[string]interface{}{},
		})
		return true
	} else {
		logger.Log.Errorf("期望收到start_connection消息，但收到: %v", parsedData["event"])
		return false
	}
}

// waitForSessionStart 等待客户端发送开始session消息并初始化session (对应Python版本的_wait_for_session_start)
func (a *AuraAgent) waitForSessionStart(conn *websocket.Conn) bool {
	// 设置读取超时
	conn.SetReadDeadline(time.Now().Add(60 * time.Second))

	// 读取消息
	messageType, messageData, err := conn.ReadMessage()
	if err != nil {
		logger.Log.Errorf("读取session开始消息失败: %v", err)
		return false
	}

	// 只处理二进制协议消息
	if messageType != websocket.BinaryMessage {
		logger.Log.Error("期望收到二进制协议消息")
		return false
	}

	// 解析二进制协议消息
	parsedData := a.parseBinaryProtocolMessage(messageData)

	// 检查解析是否成功
	if _, hasError := parsedData["error"]; hasError {
		logger.Log.Errorf("解析session开始消息失败: %v", parsedData["error"])
		return false
	}

	// 检查是否是开始session消息
	if parsedData["event"] == fmt.Sprintf("%d", protocol.ClientEventStartSession) {
		// 解析会话信息
		payload, ok := parsedData["payload_msg"].(map[string]interface{})
		if !ok {
			logger.Log.Error("开始session消息中没有payload_msg")
			return false
		}

		chatInfo, ok := payload["chat_info"].(map[string]interface{})
		if !ok {
			logger.Log.Error("开始session消息中没有chat_info")
			return false
		}

		chatID, ok := chatInfo["chat_id"].(string)
		if !ok {
			logger.Log.Error("开始session消息中没有chat_id")
			return false
		}

		userID, ok := chatInfo["user_id"].(string)
		if !ok {
			logger.Log.Error("开始session消息中没有user_id")
			return false
		}

		logger.Log.Infof("收到开始session消息: chat_id=%s", chatID)
		// 设置chatStream (对应Python版本的self.chat_stream = get_or_create_chat_stream(chat_id))
		chatStream, err := a.pythonWrapper.GetOrCreateChatStream(chatID)
		if err != nil {
			logger.Log.Errorf("获取或创建聊天流失败: chat_id=%s, error=%v", chatID, err)
			return false
		}
		locked, err := a.pythonWrapper.AcquireChatStreamLock(chatID)
		if err != nil {
			logger.Log.Errorf("获取聊天流锁失败: chat_id=%s, error=%v", chatID, err)
			return false
		}
		if !locked {
			logger.Log.Errorf("获取聊天流锁失败: chat_id=%s", chatID)
			return false
		}
		a.chatStream = chatStream
		logger.Log.Infof("ChatStream已设置: chat_id=%s", chatID)

		// 启动MessageProcessor (对应Python版本的MessageProcessor.get_instance().start)
		if err := a.msgProcessor.Start(chatID, userID, a.createSendCallback()); err != nil {
			logger.Log.Errorf("无法启动session: chat_id=%s, error=%v", chatID, err)
			// 启动失败时释放锁 (对应Python版本的错误处理)
			if released, releaseErr := a.pythonWrapper.ReleaseChatStreamLock(chatID); releaseErr != nil {
				logger.Log.Errorf("启动失败时释放聊天流锁失败: chat_id=%s, error=%v", chatID, releaseErr)
			} else if released {
				logger.Log.Infof("启动失败时已释放聊天流锁: %s", chatID)
			}
			a.sendWebSocketMessage(map[string]interface{}{
				"event": fmt.Sprintf("%d", protocol.ServerEventSessionFailed),
				"payload_msg": map[string]interface{}{
					"status":  "failed",
					"message": "无法启动session",
				},
			})
			return false
		}

		// 发送session确认
		a.sendWebSocketMessage(map[string]interface{}{
			"event": fmt.Sprintf("%d", protocol.ServerEventSessionStarted),
			"payload_msg": map[string]interface{}{
				"status":  "started",
				"chat_id": chatID,
				"message": "Session已开始",
			},
		})
		return true
	} else {
		logger.Log.Errorf("期望收到StartSession事件，但收到: %v", parsedData["event"])
		return false
	}
}

// messageProcessingLoop 主要的消息处理循环 (对应Python版本的_message_processing_loop)
func (a *AuraAgent) messageProcessingLoop(conn *websocket.Conn) {
	for {
		// 设置读取超时
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))

		// 读取消息
		messageType, messageData, err := conn.ReadMessage()
		if err != nil {
			// 检查是否是连接断开相关的错误 (对应Python版本的连接断开检测)
			errorMsg := strings.ToLower(err.Error())
			if strings.Contains(errorMsg, "disconnect") ||
				strings.Contains(errorMsg, "closed") ||
				strings.Contains(errorMsg, "connection") ||
				websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				logger.Log.Info("检测到连接断开相关错误，停止处理")
				break
			}
			logger.Log.Errorf("WebSocket读取错误: %v", err)
			continue
		}

		// 只处理二进制协议消息
		if messageType != websocket.BinaryMessage {
			logger.Log.Error("期望收到二进制协议消息")
			continue
		}

		// 解析二进制协议消息
		parsedData := a.parseBinaryProtocolMessage(messageData)

		// 检查解析是否成功
		if _, hasError := parsedData["error"]; hasError {
			logger.Log.Errorf("消息解析失败: %v", parsedData["error"])
			continue
		}

		// 检查是否是结束session消息
		if parsedData["event"] == fmt.Sprintf("%d", protocol.ClientEventFinishSession) {
			logger.Log.Info("收到结束session消息")
			a.sendWebSocketMessage(map[string]interface{}{
				"event": fmt.Sprintf("%d", protocol.ServerEventSessionFinished),
				"payload_msg": map[string]interface{}{
					"status":  "ended",
					"message": "Session已结束",
				},
			})
			break
		}

		// 更新最后消息时间
		now := time.Now()
		logger.Log.Debugf("收到二进制协议消息: event=%s, 时间差=%v", parsedData["event"], now.Sub(a.lastMessageTime))
		a.lastMessageTime = now

		// 调用MessageProcessor处理消息 (对应Python版本的MessageProcessor.get_instance().handle_message(message_data))
		result, err := a.msgProcessor.HandleMessage(&protocol.Message{
			Event:     parsedData["event"].(string),
			SessionID: parsedData["session_id"].(string),
			Payload:   parsedData["payload_msg"],
		})
		if err != nil {
			logger.Log.Errorf("MessageProcessor处理消息失败: %v", err)
		}
		if result != nil {
			logger.Log.Debugf("MessageProcessor处理结果: %v", result)
		}
	}
}

// waitForGracefulShutdown 等待客户端优雅关闭：先end_connection (对应Python版本的_wait_for_graceful_shutdown)
func (a *AuraAgent) waitForGracefulShutdown(conn *websocket.Conn) {
	// 给客户端一些时间发送end_connection消息
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))

	// 读取消息
	messageType, messageData, err := conn.ReadMessage()
	if err != nil {
		logger.Log.Info("等待结束连接消息超时，强制关闭")
		return
	}

	// 只处理二进制协议消息
	if messageType != websocket.BinaryMessage {
		logger.Log.Error("期望收到二进制协议消息")
		return
	}

	// 解析二进制协议消息
	parsedData := a.parseBinaryProtocolMessage(messageData)

	if parsedData["event"] == fmt.Sprintf("%d", protocol.ClientEventFinishConnection) {
		logger.Log.Info("收到结束连接消息")
		a.sendWebSocketMessage(map[string]interface{}{
			"event": fmt.Sprintf("%d", protocol.ServerEventConnectionFinished),
			"payload_msg": map[string]interface{}{
				"status":  "ended",
				"message": "连接已结束",
			},
		})
	} else {
		logger.Log.Warnf("期望收到FinishConnection事件，但收到: %v", parsedData["event"])
	}
}

// cleanup 清理所有资源 (对应Python版本的cleanup)
func (a *AuraAgent) cleanup() {
	// 移除WebSocket连接
	a.removeWebSocketConnection()

	time.Sleep(1 * time.Second)
	logger.Log.Info("AuraAgent 资源清理完成")
}

// removeWebSocketConnection 移除WebSocket连接 (对应Python版本的remove_websocket_connection)
func (a *AuraAgent) removeWebSocketConnection() {
	if a.websocketConnection != nil {
		a.websocketConnection.Close()
		a.websocketConnection = nil
	}

	// 清理MessageProcessor
	if a.msgProcessor != nil {
		a.msgProcessor.Cleanup()
		logger.Log.Info("MessageProcessor清理完成")
	}

	// 释放聊天流锁 (对应Python版本的ChatStreamManager.get_instance().release_lock)
	if a.chatStream != nil {
		// 从chatStream中获取chat_id
		if chatStreamMap, ok := a.chatStream.(map[string]interface{}); ok {
			if chatID, ok := chatStreamMap["chat_id"].(string); ok {
				released, err := a.pythonWrapper.ReleaseChatStreamLock(chatID)
				if err != nil {
					logger.Log.Errorf("释放聊天流锁失败: chat_id=%s, error=%v", chatID, err)
				} else if released {
					logger.Log.Infof("已释放聊天流锁: %s", chatID)
				}
			}
		} else if chatStream, ok := a.chatStream.(*agentmemory.ChatStream); ok {
			released, err := a.pythonWrapper.ReleaseChatStreamLock(chatStream.ChatID)
			if err != nil {
				logger.Log.Errorf("释放聊天流锁失败: chat_id=%s, error=%v", chatStream.ChatID, err)
			} else if released {
				logger.Log.Infof("已释放聊天流锁: %s", chatStream.ChatID)
			}
		}
	}

	logger.Log.Info("WebSocket连接已移除")
}

// createSendCallback 创建发送回调函数
func (a *AuraAgent) createSendCallback() func(interface{}) error {
	return func(msg interface{}) error {
		// 将消息转换为map格式
		msgMap, ok := msg.(map[string]interface{})
		if !ok {
			logger.Log.Warnf("无法转换消息格式: %v", msg)
			return nil
		}

		// 调用sendWebSocketMessage发送消息
		return a.sendWebSocketMessage(msgMap)
	}
}

// parseBinaryProtocolMessage 使用统一的协议解析方法 (对应Python版本的_parse_binary_protocol_message)
func (a *AuraAgent) parseBinaryProtocolMessage(data []byte) map[string]interface{} {
	// 使用统一的协议解析函数
	result, err := protocol.ParseBinaryMessage(data)
	if err != nil {
		logger.Log.Errorf("解析二进制协议消息失败: %v", err)
		return map[string]interface{}{"error": fmt.Sprintf("解析失败: %v", err)}
	}
	// 解析payload为JSON对象
	var payloadData interface{}
	if len(result.Payload) > 0 {
		if result.SerializationMethod == protocol.JSON {
			if err := json.Unmarshal(result.Payload, &payloadData); err != nil {
				logger.Log.Errorf("解析payload JSON失败: %v", err)
				// 如果JSON解析失败，将payload作为字符串处理
				payloadData = string(result.Payload)
			}
		} else if result.SerializationMethod != protocol.NO_SERIALIZATION {
			payloadData = string(result.Payload)
		} else {
			payloadData = result.Payload
		}
	}

	// 转换为map格式
	messageData := map[string]interface{}{
		"event":       fmt.Sprintf("%d", result.Event),
		"session_id":  result.SessionID,
		"payload_msg": payloadData,
	}

	logger.Log.Debugf("协议解析成功: event=%s, session_id=%s, payload_type=%T", messageData["event"], messageData["session_id"], payloadData)
	return messageData
}

// sendWebSocketMessage 发送WebSocket消息，使用统一的协议格式 (对应Python版本的send_websocket_message)
func (a *AuraAgent) sendWebSocketMessage(message map[string]interface{}) error {
	if a.websocketConnection == nil {
		return fmt.Errorf("WebSocket连接未设置")
	}

	logger.Log.Debugf("发送消息: %v", message)

	// 使用统一的协议构造方法
	binaryData := a.constructProtocolMessage(message)

	// 发送二进制数据
	if err := a.websocketConnection.WriteMessage(websocket.BinaryMessage, binaryData); err != nil {
		logger.Log.Errorf("发送消息失败: %v", err)
		return err
	}

	logger.Log.Debugf("发送消息成功: %v", message["event"])
	return nil
}

// constructProtocolMessage 使用统一的协议构造方法 (对应Python版本的_construct_protocol_message)
func (a *AuraAgent) constructProtocolMessage(message map[string]interface{}) []byte {
	// 获取事件ID
	eventStr, ok := message["event"].(string)
	if !ok {
		logger.Log.Error("消息中缺少event字段")
		return nil
	}

	// 获取payload数据
	payloadData := message["payload_msg"]
	if payloadData == nil {
		payloadData = message
	}

	// 获取session_id
	sessionID := ""
	if a.chatStream != nil {
		// 从chatStream中获取chat_id作为session_id
		if chatStreamMap, ok := a.chatStream.(map[string]interface{}); ok {
			if chatID, ok := chatStreamMap["chat_id"].(string); ok {
				sessionID = chatID
			}
		} else if chatStream, ok := a.chatStream.(*agentmemory.ChatStream); ok {
			sessionID = chatStream.ChatID
		}
	}
	if sessionID == "" {
		sessionID = "default"
	}

	// 处理音频数据 - 统一使用SERVER_FULL_RESPONSE

	// 转换事件字符串为数字ID
	eventID := a.parseEventString(eventStr)

	// 使用统一的协议生成方法
	binaryData, err := protocol.GenerateBinaryResponse(
		eventID,
		sessionID,
		payloadData,
		protocol.SERVER_FULL_RESPONSE,
	)
	if err != nil {
		logger.Log.Errorf("构造协议消息失败: %v", err)
		return nil
	}

	return binaryData
}

// parseEventString 将字符串事件转换为数字事件ID
func (a *AuraAgent) parseEventString(eventStr string) uint32 {
	switch eventStr {
	case "50":
		return protocol.ServerEventConnectionStarted
	case "51":
		return protocol.ServerEventConnectionFailed
	case "52":
		return protocol.ServerEventConnectionFinished
	case "150":
		return protocol.ServerEventSessionStarted
	case "152":
		return protocol.ServerEventSessionFinished
	case "153":
		return protocol.ServerEventSessionFailed
	case "350":
		return protocol.ServerEventTTSSentenceStart
	case "351":
		return protocol.ServerEventTTSSentenceEnd
	case "352":
		return protocol.ServerEventTTSResponse
	case "359":
		return protocol.ServerEventTTSEnded
	case "450":
		return protocol.ServerEventASRInfo
	case "451":
		return protocol.ServerEventASRResponse
	case "459":
		return protocol.ServerEventASREnded
	case "500":
		return protocol.ServerEventChatResponseParams
	case "550":
		return protocol.ServerEventChatResponse
	case "551":
		return protocol.ServerEventChatResponseEnd
	case "559":
		return protocol.ServerEventChatEnded
	default:
		logger.Log.Warnf("未知的事件类型: %s", eventStr)
		return protocol.ServerEventMessageReceived // 默认值
	}
}
