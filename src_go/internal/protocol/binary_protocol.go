package protocol

import (
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
)

// BinaryMessage 二进制消息结构
type BinaryMessage struct {
	ProtocolVersion          byte
	HeaderSize               byte
	MessageType              byte
	MessageTypeSpecificFlags byte
	SerializationMethod      byte
	MessageCompression       byte
	Reserved                 byte
	HeaderExtensions         []byte
	Event                    uint32
	SessionID                string
	Payload                  []byte
	PayloadSize              uint32
}

// ParseBinaryMessage 解析二进制消息
func ParseBinaryMessage(data []byte) (*BinaryMessage, error) {
	if len(data) < 4 {
		return nil, fmt.Errorf("消息太短，至少需要4字节")
	}

	msg := &BinaryMessage{}

	// 解析头部
	msg.ProtocolVersion = (data[0] >> 4) & 0x0F
	msg.HeaderSize = data[0] & 0x0F
	msg.MessageType = (data[1] >> 4) & 0x0F
	msg.MessageTypeSpecificFlags = data[1] & 0x0F
	msg.SerializationMethod = (data[2] >> 4) & 0x0F
	msg.MessageCompression = data[2] & 0x0F
	msg.Reserved = data[3]

	// 计算头部扩展
	headerEnd := int(msg.HeaderSize) * 4
	if len(data) < headerEnd {
		return nil, fmt.Errorf("消息长度不足，头部声明需要%d字节", headerEnd)
	}

	if msg.HeaderSize > 1 {
		msg.HeaderExtensions = data[4:headerEnd]
	}

	// 解析负载
	payload := data[headerEnd:]
	if len(payload) == 0 {
		return msg, nil
	}

	// 处理事件ID
	if msg.MessageTypeSpecificFlags&MSG_WITH_EVENT != 0 {
		if len(payload) < 4 {
			return nil, fmt.Errorf("消息包含事件标志但负载不足4字节")
		}
		msg.Event = binary.BigEndian.Uint32(payload[:4])
		payload = payload[4:]
	}

	// 处理会话ID
	if len(payload) >= 4 {
		sessionIDSize := binary.BigEndian.Uint32(payload[:4])
		if len(payload) >= int(4+sessionIDSize) {
			msg.SessionID = string(payload[4 : 4+sessionIDSize])
			payload = payload[4+sessionIDSize:]
		}
	}

	// 处理负载大小和数据
	if len(payload) >= 4 {
		msg.PayloadSize = binary.BigEndian.Uint32(payload[:4])
		if len(payload) >= int(4+msg.PayloadSize) {
			compressedPayload := payload[4 : 4+msg.PayloadSize]

			// 如果消息使用了压缩，则解压
			if msg.MessageCompression == GZIP {
				decompressedPayload, err := DecompressPayload(compressedPayload)
				if err != nil {
					return nil, fmt.Errorf("解压负载失败: %v", err)
				}
				msg.Payload = decompressedPayload
			} else {
				msg.Payload = compressedPayload
			}
		}
	}

	return msg, nil
}

// GenerateBinaryResponse 生成二进制响应
func GenerateBinaryResponse(event uint32, sessionID string, payload interface{}, messageType byte) ([]byte, error) {
	var payloadBytes []byte
	var err error

	// 序列化负载
	if payload != nil {
		switch v := payload.(type) {
		case []byte:
			payloadBytes = v
		case string:
			payloadBytes = []byte(v)
		default:
			// 尝试JSON序列化
			payloadBytes, err = json.Marshal(payload)
			if err != nil {
				return nil, fmt.Errorf("序列化负载失败: %v", err)
			}
		}
	}

	// 压缩负载数据
	if len(payloadBytes) > 0 {
		compressedPayload, err := CompressPayload(payloadBytes)
		if err != nil {
			return nil, fmt.Errorf("压缩负载失败: %v", err)
		}
		payloadBytes = compressedPayload
	}

	// 计算压缩后的负载大小
	payloadSize := uint32(len(payloadBytes))

	// 计算会话ID长度
	sessionIDBytes := []byte(sessionID)
	sessionIDSize := uint32(len(sessionIDBytes))

	// 计算总大小
	totalSize := 4 + 4 + 4 + sessionIDSize + 4 + payloadSize // 头部 + 事件 + 会话ID长度 + 会话ID + 负载大小 + 负载

	// 创建缓冲区
	buffer := make([]byte, totalSize)
	offset := 0

	// 写入头部
	buffer[offset] = (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE
	buffer[offset+1] = (messageType << 4) | MSG_WITH_EVENT
	buffer[offset+2] = (JSON << 4) | GZIP
	buffer[offset+3] = 0x00 // 保留字段
	offset += 4

	// 写入事件ID
	binary.BigEndian.PutUint32(buffer[offset:], event)
	offset += 4

	// 写入会话ID长度和会话ID
	binary.BigEndian.PutUint32(buffer[offset:], sessionIDSize)
	offset += 4
	copy(buffer[offset:], sessionIDBytes)
	offset += len(sessionIDBytes)

	// 写入负载大小
	binary.BigEndian.PutUint32(buffer[offset:], payloadSize)
	offset += 4

	// 写入负载
	if len(payloadBytes) > 0 {
		copy(buffer[offset:], payloadBytes)
	}

	return buffer, nil
}

// CompressPayload 压缩负载数据
func CompressPayload(data []byte) ([]byte, error) {
	var buf bytes.Buffer
	gw := gzip.NewWriter(&buf)

	if _, err := gw.Write(data); err != nil {
		return nil, err
	}

	if err := gw.Close(); err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}

// DecompressPayload 解压负载数据
func DecompressPayload(data []byte) ([]byte, error) {
	gr, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer gr.Close()

	return io.ReadAll(gr)
}

// IsAudioMessage 检查是否为音频消息
func (msg *BinaryMessage) IsAudioMessage() bool {
	return msg.MessageType == CLIENT_AUDIO_ONLY_REQUEST
}

// IsControlMessage 检查是否为控制消息
func (msg *BinaryMessage) IsControlMessage() bool {
	return msg.MessageType == CLIENT_FULL_REQUEST
}

// GetEventName 获取事件名称
func (msg *BinaryMessage) GetEventName() string {
	switch msg.Event {
	case ClientEventStartConnection:
		return "StartConnection"
	case ClientEventFinishConnection:
		return "FinishConnection"
	case ClientEventStartSession:
		return "StartSession"
	case ClientEventFinishSession:
		return "FinishSession"
	case ClientEventTaskRequest:
		return "TaskRequest"
	case ClientEventSpeakEnded:
		return "SpeakEnded"
	default:
		return fmt.Sprintf("Unknown(%d)", msg.Event)
	}
}
