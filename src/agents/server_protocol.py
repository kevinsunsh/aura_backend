import gzip
import json

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

PROTOCOL_VERSION_BITS = 4
HEADER_BITS = 4
MESSAGE_TYPE_BITS = 4
MESSAGE_TYPE_SPECIFIC_FLAGS_BITS = 4
MESSAGE_SERIALIZATION_BITS = 4
MESSAGE_COMPRESSION_BITS = 4
RESERVED_BITS = 8

# Message Type:
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010

SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# Message Type Specific Flags
NO_SEQUENCE = 0b0000  # no check sequence
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
NEG_SEQUENCE_1 = 0b0011

MSG_WITH_EVENT = 0b0100

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001
THRIFT = 0b0011
CUSTOM_TYPE = 0b1111

# Message Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001
CUSTOM_COMPRESSION = 0b1111

def server_generate_header(
        version=PROTOCOL_VERSION,
        message_type=SERVER_FULL_RESPONSE,
        message_type_specific_flags=MSG_WITH_EVENT,
        serial_method=JSON,
        compression_type=GZIP,
        reserved_data=0x00,
        extension_header=bytes()
):
    """
    服务端生成响应头
    protocol_version(4 bits), header_size(4 bits),
    message_type(4 bits), message_type_specific_flags(4 bits)
    serialization_method(4 bits) message_compression(4 bits)
    reserved （8bits) 保留字段
    header_extensions 扩展头(大小等于 8 * 4 * (header_size - 1) )
    """
    header = bytearray()
    header_size = int(len(extension_header) / 4) + 1
    header.append((version << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
    header.extend(extension_header)
    return header


def server_parse_request(req):
    """
    服务端解析客户端请求
    - header
        - (4bytes)header
        - (4bits)version(v1) + (4bits)header_size
        - (4bits)messageType + (4bits)messageTypeFlags
            -- 0001	CompleteClient | -- 0001 hasSequence
            -- 0010	audioonly      | -- 0010 isTailPacket
                                           | -- 0100 hasEvent
        - (4bits)payloadFormat + (4bits)compression
        - (8bits) reserve
    - payload
        - [optional 4 bytes] event
        - [optional] session ID
          -- (4 bytes)session ID len
          -- session ID data
        - (4 bytes)data len
        - data
    """
    if isinstance(req, str):
        return {}
    
    protocol_version = req[0] >> 4
    header_size = req[0] & 0x0f
    message_type = req[1] >> 4
    message_type_specific_flags = req[1] & 0x0f
    serialization_method = req[2] >> 4
    message_compression = req[2] & 0x0f
    reserved = req[3]
    header_extensions = req[4:header_size * 4]
    payload = req[header_size * 4:]
    
    result = {
        'protocol_version': protocol_version,
        'header_size': header_size,
        'message_type': message_type,
        'message_type_specific_flags': message_type_specific_flags,
        'serialization_method': serialization_method,
        'message_compression': message_compression,
        'reserved': reserved,
        'header_extensions': header_extensions
    }
    
    payload_msg = None
    payload_size = 0
    start = 0
    
    if message_type == CLIENT_FULL_REQUEST or message_type == CLIENT_AUDIO_ONLY_REQUEST:
        result['request_type'] = 'CLIENT_FULL_REQUEST' if message_type == CLIENT_FULL_REQUEST else 'CLIENT_AUDIO_ONLY_REQUEST'
        
        # 检查是否有序列号
        if message_type_specific_flags & POS_SEQUENCE > 0:
            result['seq'] = int.from_bytes(payload[:4], "big", signed=False)
            start += 4
        
        # 检查是否有事件
        if message_type_specific_flags & MSG_WITH_EVENT > 0:
            result['event'] = int.from_bytes(payload[start:start+4], "big", signed=False)
            start += 4
        
        payload = payload[start:]
        
        # 解析 session ID
        if len(payload) >= 4:
            session_id_size = int.from_bytes(payload[:4], "big", signed=True)
            session_id = payload[4:session_id_size]
            result['session_id'] = str(session_id)
            payload = payload[4 + session_id_size:]
            
        # 解析数据长度和数据
        if len(payload) >= 4:
            payload_size = int.from_bytes(payload[:4], "big", signed=False)
            payload_msg = payload[4:]
            
            # 解压缩
            if message_compression == GZIP:
                payload_msg = gzip.decompress(payload_msg)
            
            # 反序列化
            if serialization_method == JSON:
                payload_msg = json.loads(payload_msg)
            elif serialization_method != NO_SERIALIZATION:
                payload_msg = payload_msg
            
            result['payload_msg'] = payload_msg
            result['payload_size'] = payload_size
    
    return result


def server_generate_response(
        payload_data,
        message_type=SERVER_FULL_RESPONSE,
        message_type_specific_flags=MSG_WITH_EVENT,
        serial_method=JSON,
        compression_type=GZIP,
        seq=None,
        event=None,
        session_id=None,
        reserved_data=0x00
):
    """
    服务端生成完整响应
    """
    # 生成头部
    header = server_generate_header(
        message_type=message_type,
        message_type_specific_flags=message_type_specific_flags,
        serial_method=serial_method,
        compression_type=compression_type,
        reserved_data=reserved_data
    )
    
    # 构建 payload
    payload = bytearray()
    
    # 添加序列号（如果需要）
    if seq is not None and (message_type_specific_flags & NEG_SEQUENCE > 0):
        payload.extend(int(seq).to_bytes(4, "big"))
    
    # 添加事件（如果需要）
    if event is not None and (message_type_specific_flags & MSG_WITH_EVENT > 0):
        payload.extend(int(event).to_bytes(4, "big"))
    
    # 添加 session ID（如果需要）
    if session_id is not None:
        payload.extend(len(session_id).to_bytes(4, "big"))
        payload.extend(str.encode(session_id))
    
    # 序列化数据
    if serial_method == JSON:
        # 否则进行JSON序列化
        data = str.encode(json.dumps(payload_data))
    else:
        # NO_SERIALIZATION 情况，直接使用字节数据
        data = payload_data
    
    # 压缩数据（只有在不是NO_COMPRESSION时才压缩）
    if compression_type == GZIP:
        data = gzip.compress(data)
    
    # 添加数据长度和数据
    payload.extend(len(data).to_bytes(4, "big", signed=False))
    payload.extend(data)
    
    # 组合头部和 payload
    return header + payload


def server_generate_error_response(
        error_code,
        error_message,
        message_type=SERVER_ERROR_RESPONSE,
        reserved_data=0x00
):
    """
    服务端生成错误响应
    """
    header = server_generate_header(
        message_type=message_type,
        message_type_specific_flags=0,
        serial_method=NO_SERIALIZATION,
        compression_type=NO_COMPRESSION,
        reserved_data=reserved_data
    )
    
    payload = bytearray()
    payload.extend(error_code.to_bytes(4, "big", signed=False))
    
    error_msg_bytes = error_message.encode("utf-8")
    payload.extend(len(error_msg_bytes).to_bytes(4, "big", signed=False))
    payload.extend(error_msg_bytes)
    
    return header + payload


def server_generate_ack_response(
        seq=None,
        event=None,
        session_id=None,
        reserved_data=0x00
):
    """
    服务端生成 ACK 响应
    """
    message_type_specific_flags = 0
    if seq is not None:
        message_type_specific_flags |= NEG_SEQUENCE
    if event is not None:
        message_type_specific_flags |= MSG_WITH_EVENT
    
    return server_generate_response(
        payload_data="",
        message_type=SERVER_ACK,
        message_type_specific_flags=message_type_specific_flags,
        serial_method=NO_SERIALIZATION,
        compression_type=NO_COMPRESSION,
        seq=seq,
        event=event,
        session_id=session_id,
        reserved_data=reserved_data
    )
