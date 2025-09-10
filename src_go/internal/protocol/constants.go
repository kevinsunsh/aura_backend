package protocol

// 二进制协议常量
const (
	PROTOCOL_VERSION    = 0x01
	DEFAULT_HEADER_SIZE = 0x01

	// 消息类型
	CLIENT_FULL_REQUEST       = 0x01
	CLIENT_AUDIO_ONLY_REQUEST = 0x02
	SERVER_FULL_RESPONSE      = 0x09
	SERVER_ACK                = 0x0B
	SERVER_ERROR_RESPONSE     = 0x0F

	// 消息类型特定标志
	NO_SEQUENCE    = 0x00
	POS_SEQUENCE   = 0x01
	NEG_SEQUENCE   = 0x02
	NEG_SEQUENCE_1 = 0x03
	MSG_WITH_EVENT = 0x04

	// 消息序列化
	NO_SERIALIZATION = 0x00
	JSON             = 0x01
	THRIFT           = 0x03
	CUSTOM_TYPE      = 0x0F

	// 消息压缩
	NO_COMPRESSION     = 0x00
	GZIP               = 0x01
	CUSTOM_COMPRESSION = 0x0F
)

// 服务器事件类型（数字常量）
const (
	ServerEventConnectionStarted  = 50
	ServerEventConnectionFailed   = 51
	ServerEventConnectionFinished = 52
	ServerEventSessionStarted     = 150
	ServerEventSessionFinished    = 152
	ServerEventSessionFailed      = 153
	ServerEventMessageReceived    = 154
	ServerEventAudioReceived      = 155
	ServerEventStreamingResponse  = 156
	ServerEventTTSSentenceStart   = 350
	ServerEventTTSSentenceEnd     = 351
	ServerEventTTSResponse        = 352
	ServerEventTTSEnded           = 359
	ServerEventVADResponse        = 460
	ServerEventASRInfo            = 450
	ServerEventASRResponse        = 451
	ServerEventASREnded           = 459
	ServerEventChatActionParams   = 495
	ServerEventChatEmotionParams  = 496
	ServerEventChatEnvDescParams  = 497
	ServerEventChatResponseParams = 500
	ServerEventChatAction         = 501
	ServerEventChatEmotion        = 502
	ServerEventChatEnvDesc        = 503
	ServerEventChatActionEnd      = 504
	ServerEventChatEmotionEnd     = 505
	ServerEventChatEnvDescEnd     = 506
	ServerEventChatResponse       = 550
	ServerEventChatResponseEnd    = 551
	ServerEventChatEnded          = 559
	ServerEventMutteringResponse  = 650
)

// 客户端事件类型（数字常量）
const (
	ClientEventStartConnection       = 1
	ClientEventFinishConnection      = 2
	ClientEventStartSession          = 100
	ClientEventFinishSession         = 102
	ClientEventTaskRequest           = 200
	ClientEventSendMessage           = 201
	ClientEventSendAudio             = 202
	ClientEventSayHello              = 300
	ClientEventWorldInfoActivateKeys = 400
	ClientEventChangeBotID           = 401
	ClientEventChangeSystemPreset    = 402
	ClientEventChatTTSText           = 500
	ClientEventSpeakEnded            = 600
)

// 协议版本
const (
	ProtocolVersion = "1.0.0"
)

// 消息结构
type Message struct {
	Event       string      `json:"event"`
	SessionID   string      `json:"session_id,omitempty"`
	ChatID      string      `json:"chat_id,omitempty"`
	UserID      string      `json:"user_id,omitempty"`
	Timestamp   int64       `json:"timestamp"`
	Payload     interface{} `json:"payload,omitempty"`
	MessageType string      `json:"message_type,omitempty"`
	Status      string      `json:"status,omitempty"`
	Error       string      `json:"error,omitempty"`
}

// 请求消息结构
type RequestMessage struct {
	Event     string      `json:"event"`
	SessionID string      `json:"session_id,omitempty"`
	Content   string      `json:"content,omitempty"`
	Data      interface{} `json:"data,omitempty"`
	Timestamp int64       `json:"timestamp,omitempty"`
}

// 聊天信息
type ChatInfo struct {
	ChatID string `json:"chat_id"`
	UserID string `json:"user_id"`
}

// 连接开始消息
type StartConnectionMessage struct {
	Event string `json:"event"`
}

// 会话开始消息
type StartSessionMessage struct {
	Event    string   `json:"event"`
	ChatInfo ChatInfo `json:"chat_info"`
}

// 会话结束消息
type FinishSessionMessage struct {
	Event string `json:"event"`
}

// 连接结束消息
type FinishConnectionMessage struct {
	Event string `json:"event"`
}

// 文本消息
type TextMessage struct {
	Event     string `json:"event"`
	SessionID string `json:"session_id"`
	Content   string `json:"content"`
}

// 音频消息
type AudioMessage struct {
	Event     string `json:"event"`
	SessionID string `json:"session_id"`
	AudioData []byte `json:"audio_data"`
	Format    string `json:"format"`
}

// 响应消息
type ResponseMessage struct {
	Event     string      `json:"event"`
	SessionID string      `json:"session_id"`
	Status    string      `json:"status"`
	Data      interface{} `json:"data,omitempty"`
	Message   string      `json:"message,omitempty"`
	Error     string      `json:"error,omitempty"`
	Timestamp int64       `json:"timestamp,omitempty"`
}
