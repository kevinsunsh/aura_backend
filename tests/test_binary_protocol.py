#!/usr/bin/env python3
"""
测试简洁的task_request协议构造是否正确
"""
import sys
import os
import gzip

# 添加当前目录到路径，以便导入test_websocket_audio中的协议函数
sys.path.append(os.path.dirname(__file__))

try:
    from agents.doubao_client import protocol
except ImportError:
    print("⚠️ 无法导入protocol模块，将使用内置协议定义")
    # 内置协议定义作为备选
    class protocol:
        CLIENT_AUDIO_ONLY_REQUEST = 0b0010
        CLIENT_FULL_REQUEST = 0b0001
        NO_SERIALIZATION = 0b0000
        JSON = 0b0001
        
        @staticmethod
        def generate_header(message_type=0b0010, serial_method=0b0000):
            header = bytearray()
            header_size = 1
            header.append((0b0001 << 4) | header_size)  # version + header_size
            header.append((message_type << 4) | 0b0100)  # message_type + MSG_WITH_EVENT
            header.append((serial_method << 4) | 0b0001)  # serial_method + GZIP
            header.append(0x00)  # reserved
            return header

def construct_audio_task_request(audio: bytes, session_id: str = "test_user_123") -> bytes:
    """构造音频task_request，参考RealtimeDialogClient.task_request"""
    task_request = bytearray(
        protocol.generate_header(message_type=protocol.CLIENT_AUDIO_ONLY_REQUEST,
                                 serial_method=protocol.NO_SERIALIZATION))
    task_request.extend(int(200).to_bytes(4, 'big'))
    task_request.extend((len(session_id)).to_bytes(4, 'big'))
    task_request.extend(str.encode(session_id))
    payload_bytes = gzip.compress(audio)
    task_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # payload size(4 bytes)
    task_request.extend(payload_bytes)
    return bytes(task_request)

def test_audio_protocol():
    """测试音频协议消息构造"""
    print("=== 测试简洁的task_request音频协议 ===")
    
    # 创建一些测试音频数据
    test_audio = b'\x00\x01\x02\x03' * 1600  # 6400字节的测试数据
    
    # 构造协议消息
    message = construct_audio_task_request(test_audio, "test_user_123")
    
    if message:
        compressed_size = len(gzip.compress(test_audio))
        print(f"✅ 音频task_request构造成功")
        print(f"   - 原始音频数据: {len(test_audio)} 字节")
        print(f"   - 压缩后音频数据: {compressed_size} 字节")
        print(f"   - 协议消息总长度: {len(message)} 字节")
        print(f"   - 协议头前4字节: {message[:4].hex()}")
        print(f"   - 协议消息前20字节: {message[:20].hex()}")
        print(f"   - 压缩率: {compressed_size/len(test_audio)*100:.1f}%")
    else:
        print("❌ 音频协议消息构造失败")

def analyze_protocol_structure():
    """分析协议结构"""
    print("\n=== task_request协议结构分析 ===")
    
    test_audio = b'\x00\x01' * 100  # 200字节的测试数据
    message = construct_audio_task_request(test_audio, "test_session")
    
    if message:
        print(f"协议消息结构分析 (总长度: {len(message)} 字节):")
        
        # 解析协议头 (4字节)
        header = message[:4]
        print(f"1. 协议头 (4字节): {header.hex()}")
        
        version = (header[0] >> 4) & 0x0F
        header_size = header[0] & 0x0F
        message_type = (header[1] >> 4) & 0x0F
        flags = header[1] & 0x0F
        serial_method = (header[2] >> 4) & 0x0F
        compression = header[2] & 0x0F
        reserved = header[3]
        
        print(f"   - 版本: {version}")
        print(f"   - 头大小: {header_size}")
        print(f"   - 消息类型: {message_type} (CLIENT_AUDIO_ONLY_REQUEST)")
        print(f"   - 标志: {flags} (MSG_WITH_EVENT)")
        print(f"   - 序列化方法: {serial_method} (NO_SERIALIZATION)")
        print(f"   - 压缩类型: {compression} (GZIP)")
        print(f"   - 保留字段: {reserved}")
        
        # 解析事件ID (4字节)
        offset = 4
        event_id = int.from_bytes(message[offset:offset+4], 'big')
        print(f"2. 事件ID (4字节): {event_id} (TaskRequest)")
        offset += 4
        
        # 解析Session ID长度和数据
        session_len = int.from_bytes(message[offset:offset+4], 'big')
        offset += 4
        session_id = message[offset:offset+session_len].decode('utf-8')
        print(f"3. Session ID 长度: {session_len}")
        print(f"4. Session ID: '{session_id}'")
        offset += session_len
        
        # 解析Payload长度和数据
        payload_len = int.from_bytes(message[offset:offset+4], 'big')
        offset += 4
        print(f"5. Payload 长度: {payload_len} 字节 (gzip压缩后)")
        
        # 尝试解压缩验证
        try:
            compressed_payload = message[offset:offset+payload_len]
            decompressed = gzip.decompress(compressed_payload)
            print(f"6. 解压缩后音频数据: {len(decompressed)} 字节")
            print(f"   - 压缩效果: {len(test_audio)} -> {payload_len} 字节 ({payload_len/len(test_audio)*100:.1f}%)")
        except Exception as e:
            print(f"6. 解压缩失败: {e}")
        
        # 验证计算
        expected_total = 4 + 4 + 4 + session_len + 4 + payload_len
        print(f"\n验证: 计算总长度 {expected_total} vs 实际长度 {len(message)} - {'✅' if expected_total == len(message) else '❌'}")

if __name__ == "__main__":
    test_audio_protocol()
    analyze_protocol_structure()
    print("\n🎉 简洁协议测试完成！") 