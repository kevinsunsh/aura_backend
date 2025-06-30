import asyncio
import uuid
import queue
import threading
import time
import json
import logging
import base64
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

import websockets
import gzip

from ..aura_memory.message_store import Message
from ..configuration import Configuration
from ..graphs.main_graph import builder
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = logging.getLogger(__name__)

@dataclass
class AudioConfig:
    """音频配置数据类"""
    format: str
    bit_size: int
    channels: int
    sample_rate: int
    chunk: int


class RealtimeDialogClient:
    """实时对话客户端，基于参考代码实现"""
    
    def __init__(self, config: Dict[str, Any], session_id: str):
        self.config = config
        self.logid = ""
        self.session_id = session_id
        self.ws = None

    async def connect(self) -> None:
        """建立WebSocket连接"""
        logger.info(f"连接服务器: {self.config['base_url']}")
        self.ws = await websockets.connect(
            self.config['base_url'],
            extra_headers=self.config['headers'],
            ping_interval=None
        )
        self.logid = self.ws.response_headers.get("X-Tt-Logid")
        logger.info(f"服务器响应logid: {self.logid}")

        # StartConnection request (事件ID: 1)
        await self.start_connection()

        # StartSession request (事件ID: 100)
        await self.start_session()

    async def start_connection(self) -> None:
        """StartConnection - 客户端事件ID: 1"""
        start_connection_request = bytearray(self._generate_header())
        start_connection_request.extend(int(1).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        start_connection_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        start_connection_request.extend(payload_bytes)
        await self.ws.send(start_connection_request)
        response = await self.ws.recv()
        logger.info(f"StartConnection响应: {self._parse_response(response)}")

    async def start_session(self, bot_name: str = "豆包", dialog_id: str = None, strict_audit: bool = True) -> None:
        """StartSession - 客户端事件ID: 100"""
        # 构建会话参数
        session_params = {
            "dialog": {
                "bot_name": bot_name,
                "extra": {
                    "strict_audit": strict_audit
                }
            }
        }
        
        # 如果提供了dialog_id，添加到参数中
        if dialog_id:
            session_params["dialog"]["dialog_id"] = dialog_id
        
        payload_bytes = str.encode(json.dumps(session_params))
        payload_bytes = gzip.compress(payload_bytes)
        start_session_request = bytearray(self._generate_header())
        start_session_request.extend(int(100).to_bytes(4, 'big'))
        start_session_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        start_session_request.extend(str.encode(self.session_id))
        start_session_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        start_session_request.extend(payload_bytes)
        await self.ws.send(start_session_request)
        response = await self.ws.recv()
        logger.info(f"StartSession响应: {self._parse_response(response)}")

    async def finish_session(self) -> None:
        """FinishSession - 客户端事件ID: 102"""
        finish_session_request = bytearray(self._generate_header())
        finish_session_request.extend(int(102).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        finish_session_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        finish_session_request.extend(str.encode(self.session_id))
        finish_session_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        finish_session_request.extend(payload_bytes)
        await self.ws.send(finish_session_request)

    async def finish_connection(self) -> None:
        """FinishConnection - 客户端事件ID: 2"""
        finish_connection_request = bytearray(self._generate_header())
        finish_connection_request.extend(int(2).to_bytes(4, 'big'))
        payload_bytes = str.encode("{}")
        payload_bytes = gzip.compress(payload_bytes)
        finish_connection_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        finish_connection_request.extend(payload_bytes)
        await self.ws.send(finish_connection_request)
        response = await self.ws.recv()
        logger.info(f"FinishConnection响应: {self._parse_response(response)}")

    async def task_request(self, audio: bytes) -> None:
        """TaskRequest - 客户端事件ID: 200"""
        task_request = bytearray(
            self._generate_header(message_type=0b0010, serial_method=0b0000))
        task_request.extend(int(200).to_bytes(4, 'big'))
        task_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        task_request.extend(str.encode(self.session_id))
        payload_bytes = gzip.compress(audio)
        task_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        task_request.extend(payload_bytes)
        await self.ws.send(task_request)

    async def say_hello(self, content: str) -> None:
        """SayHello - 客户端事件ID: 300"""
        hello_data = {
            "content": content
        }
        payload_bytes = str.encode(json.dumps(hello_data))
        payload_bytes = gzip.compress(payload_bytes)
        
        say_hello_request = bytearray(self._generate_header(message_type=0b0001, serial_method=0b0001))
        say_hello_request.extend(int(300).to_bytes(4, 'big'))
        say_hello_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        say_hello_request.extend(str.encode(self.session_id))
        say_hello_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        say_hello_request.extend(payload_bytes)
        await self.ws.send(say_hello_request)

    async def chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """ChatTTSText - 客户端事件ID: 500"""
        tts_data = {
            "start": start,
            "content": content,
            "end": end
        }
        payload_bytes = str.encode(json.dumps(tts_data))
        payload_bytes = gzip.compress(payload_bytes)
        
        chat_tts_request = bytearray(self._generate_header(message_type=0b0001, serial_method=0b0001))
        chat_tts_request.extend(int(500).to_bytes(4, 'big'))
        chat_tts_request.extend((len(self.session_id)).to_bytes(4, 'big'))
        chat_tts_request.extend(str.encode(self.session_id))
        chat_tts_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        chat_tts_request.extend(payload_bytes)
        await self.ws.send(chat_tts_request)

    def _generate_header(self, message_type=0b0010, serial_method=0b0000):
        """生成协议头"""
        header = bytearray()
        header.append((0b0001 << 4) | 0b0001)  # version + header_size
        header.append((message_type << 4) | 0b0100)  # message_type + flags
        header.append((serial_method << 4) | 0b0001)  # serial + compression
        header.append(0x00)  # reserved
        return header

    def _parse_response(self, res):
        """解析服务器响应"""
        if isinstance(res, str):
            return {}
        
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size * 4]
        payload = res[header_size * 4:]
        
        result = {}
        payload_msg = None
        payload_size = 0
        start = 0
        
        if message_type == 0b1001 or message_type == 0b1011:  # SERVER_FULL_RESPONSE or SERVER_ACK
            result['message_type'] = 'SERVER_FULL_RESPONSE'
            if message_type == 0b1011:
                result['message_type'] = 'SERVER_ACK'
            if message_type_specific_flags & 0b0010 > 0:  # NEG_SEQUENCE
                result['seq'] = int.from_bytes(payload[:4], "big", signed=False)
                start += 4
            if message_type_specific_flags & 0b0100 > 0:  # MSG_WITH_EVENT
                result['event'] = int.from_bytes(payload[:4], "big", signed=False)
                start += 4
            payload = payload[start:]
            session_id_size = int.from_bytes(payload[:4], "big", signed=True)
            session_id = payload[4:4+session_id_size]
            result['session_id'] = str(session_id, 'utf-8')
            payload = payload[4 + session_id_size:]
            payload_size = int.from_bytes(payload[:4], "big", signed=False)
            payload_msg = payload[4:]
        elif message_type == 0b1111:  # SERVER_ERROR_RESPONSE
            code = int.from_bytes(payload[:4], "big", signed=False)
            result['code'] = code
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]
            
        if payload_msg is None:
            return result
            
        if message_compression == 0b0001:  # GZIP
            payload_msg = gzip.decompress(payload_msg)
        if serialization_method == 0b0001:  # JSON
            payload_msg = json.loads(str(payload_msg, "utf-8"))
        elif serialization_method != 0b0000:  # NO_SERIALIZATION
            payload_msg = str(payload_msg, "utf-8")
            
        result['payload_msg'] = payload_msg
        result['payload_size'] = payload_size
        return result

    async def receive_server_response(self) -> Dict[str, Any]:
        """接收服务器响应"""
        try:
            response = await self.ws.recv()
            data = self._parse_response(response)
            return data
        except Exception as e:
            raise Exception(f"接收消息失败: {e}")

    async def close(self) -> None:
        """关闭WebSocket连接"""
        if self.ws:
            logger.info("关闭WebSocket连接...")
            await self.ws.close()


class DialogSession:
    """对话会话管理类，集成RealtimeDialogClient和aura流式聊天"""

    def __init__(self, 
                 chat_id: str,
                 ws_config: Dict[str, Any],
                 message_store,
                 chat_stream_manager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None]):
        self.chat_id = chat_id
        self.session_id = str(uuid.uuid4())
        self.client = RealtimeDialogClient(config=ws_config, session_id=self.session_id)
        
        # aura相关组件
        self.message_store = message_store
        self.chat_stream_manager = chat_stream_manager
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
        
        # 状态管理
        self.is_running = True
        self.is_session_finished = False
        
        # 音频缓冲队列
        self.audio_queue = queue.Queue()
        
        # 响应缓冲
        self.server_asr_result = None
        self.aura_chat_response = None
        self.aura_tts_response = None
        self.server_tts_response = None
        self.server_chat_response = None
        
        # 延迟监控
        self.last_input_time = None
        self.first_audio_response_time = None
        self.latency_stats = {
            'total_requests': 0,
            'total_latency': 0.0,
            'min_latency': float('inf'),
            'max_latency': 0.0,
            'avg_latency': 0.0
        }
        
        # 任务管理
        self.aura_task = None
        self.server_receive_task = None

    def _update_latency_stats(self, latency: float) -> None:
        """更新延迟统计信息"""
        self.latency_stats['total_requests'] += 1
        self.latency_stats['total_latency'] += latency
        self.latency_stats['min_latency'] = min(self.latency_stats['min_latency'], latency)
        self.latency_stats['max_latency'] = max(self.latency_stats['max_latency'], latency)
        self.latency_stats['avg_latency'] = self.latency_stats['total_latency'] / self.latency_stats['total_requests']
    
    async def _handle_server_response(self, response: Dict[str, Any]) -> None:
        """处理服务器响应"""
        if response == {}:
            return
            
        # 处理事件类型响应
        if response.get('event') is not None:
            await self._handle_server_event(response)
            return

    async def _handle_server_event(self, response: Dict[str, Any]) -> None:
        """处理服务器事件响应"""
        event_id = response.get('event')
        payload_msg = response.get('payload_msg', {})
        
        logger.info(f"处理服务器事件: {event_id}")
        
        # Connect类事件 (50-52)
        if event_id == 50:  # ConnectionStarted
            await self._on_connection_started(payload_msg)
        elif event_id == 51:  # ConnectionFailed
            await self._on_connection_failed(payload_msg)
        elif event_id == 52:  # ConnectionFinished
            await self._on_connection_finished(payload_msg)
            
        # Session类事件 (150-153)
        elif event_id == 150:  # SessionStarted
            await self._on_session_started(payload_msg)
        elif event_id == 152:  # SessionFinished
            await self._on_session_finished(payload_msg)
        elif event_id == 153:  # SessionFailed
            await self._on_session_failed(payload_msg)
            
        # TTS类事件 (350-359)
        elif event_id == 350:  # TTSSentenceStart
            await self._on_tts_sentence_start(payload_msg)
        elif event_id == 351:  # TTSSentenceEnd
            await self._on_tts_sentence_end(payload_msg)
        elif event_id == 352:  # TTSResponse
            await self._on_tts_response(payload_msg)
        elif event_id == 359:  # TTSEnded
            await self._on_tts_ended(payload_msg)
            
        # ASR类事件 (450-459)
        elif event_id == 450:  # ASRInfo
            await self._on_asr_info(payload_msg)
        elif event_id == 451:  # ASRResponse
            await self._on_asr_response(payload_msg)
        elif event_id == 459:  # ASREnded
            await self._on_asr_ended(payload_msg)
            
        # Chat类事件 (550-559)
        elif event_id == 550:  # ChatResponse
            await self._on_chat_response(payload_msg)
        elif event_id == 559:  # ChatEnded
            await self._on_chat_ended(payload_msg)
            
        else:
            logger.warning(f"未知事件ID: {event_id}")

    # Connect类事件回调方法
    async def _on_connection_started(self, payload: Dict[str, Any]) -> None:
        """连接建立成功事件回调"""
        logger.info("连接建立成功")

    async def _on_connection_failed(self, payload: Dict[str, Any]) -> None:
        """连接建立失败事件回调"""
        error_msg = payload.get("error", "未知错误")
        logger.error(f"连接建立失败: {error_msg}")

    async def _on_connection_finished(self, payload: Dict[str, Any]) -> None:
        """连接结束事件回调"""
        logger.info("连接已结束")

    # Session类事件回调方法
    async def _on_session_started(self, payload: Dict[str, Any]) -> None:
        """会话启动成功事件回调"""
        dialog_id = payload.get("dialog_id", "")
        logger.info(f"会话启动成功，dialog_id: {dialog_id}")

    async def _on_session_finished(self, payload: Dict[str, Any]) -> None:
        """会话结束事件回调"""
        logger.info("会话已结束")
        self.is_session_finished = True

    async def _on_session_failed(self, payload: Dict[str, Any]) -> None:
        """会话失败事件回调"""
        error_msg = payload.get("error", "未知错误")
        logger.error(f"会话失败: {error_msg}")
        self.is_session_finished = True

    # TTS类事件回调方法
    async def _on_tts_sentence_start(self, payload: Dict[str, Any]) -> None:
        """TTS句子开始事件回调"""
        tts_type = payload.get("tts_type", "")
        text = payload.get("text", "")
        logger.info(f"TTS句子开始 - 类型: {tts_type}, 文本: {text[:50]}...")

    async def _on_tts_sentence_end(self, payload: Dict[str, Any]) -> None:
        """TTS句子结束事件回调"""
        logger.info("TTS句子结束")

    async def _on_tts_response(self, payload: Dict[str, Any]) -> None:
        """TTS音频响应事件回调"""
        # 这里payload应该是二进制音频数据
        audio_data = payload if isinstance(payload, bytes) else b""
        logger.info(f"收到TTS音频数据: {len(audio_data)} 字节")
        
        # 缓冲服务器TTS响应
        self.server_tts_response = audio_data
        
        # 选择最终结果并发送给客户端
        final_result = self._select_tts_result()
        if final_result["type"] == "aura_tts":
            # 发送aura的TTS结果
            await self.websocket_send_callback({
                "type": "stream_chunk",
                "content": self.aura_chat_response,
                "chat_id": self.chat_id,
                "source": "aura",
                "final": True
            })
        elif final_result["type"] == "server_tts":
            # 发送服务器的TTS结果
            await self.websocket_send_callback({
                "type": "tts_audio",
                "audio_data": audio_data,
                "chat_id": self.chat_id,
                "source": "server"
            })
        
        await self.websocket_send_callback({
            "type": "tts_response",
            "audio_size": len(audio_data),
            "chat_id": self.chat_id,
            "source": "server"
        })

    async def _on_tts_ended(self, payload: Dict[str, Any]) -> None:
        """TTS结束事件回调"""
        logger.info("TTS合成结束")
        await self.websocket_send_callback({
            "type": "tts_ended",
            "chat_id": self.chat_id,
            "source": "server"
        })

    # ASR类事件回调方法
    async def _on_asr_info(self, payload: Dict[str, Any]) -> None:
        """ASR信息事件回调 - 识别出首字"""
        logger.info("ASR识别出首字")
        await self.websocket_send_callback({
            "type": "asr_info",
            "chat_id": self.chat_id,
            "source": "server"
        })

    async def _on_asr_response(self, payload: Dict[str, Any]) -> None:
        """ASR响应事件回调 - 识别出文本内容"""
        results = payload.get("results", [])
        if results:
            for result in results:
                text = result.get("text", "")
                is_interim = result.get("is_interim", False)
                logger.info(f"ASR识别结果: {text} (临时: {is_interim})")
                
                if not is_interim:  # 最终结果
                    self.server_asr_result = text
                    
                    # 如果有ASR结果，启动aura聊天处理
                    if self.server_asr_result and not self.aura_task:
                        self.aura_task = asyncio.create_task(
                            self._process_aura_chat(self.server_asr_result)
                        )
        
        await self.websocket_send_callback({
            "type": "asr_response",
            "results": results,
            "chat_id": self.chat_id,
            "source": "server"
        })

    async def _on_asr_ended(self, payload: Dict[str, Any]) -> None:
        """ASR结束事件回调"""
        logger.info("ASR识别结束")
        await self.websocket_send_callback({
            "type": "asr_ended",
            "chat_id": self.chat_id,
            "source": "server"
        })

    # Chat类事件回调方法
    async def _on_chat_response(self, payload: Dict[str, Any]) -> None:
        """聊天响应事件回调"""
        content = payload.get("content", "")
        logger.info(f"收到聊天响应: {content[:50]}...")
        
        # 缓冲服务器聊天响应
        self.server_chat_response = content
        
        await self.websocket_send_callback({
            "type": "chat_response",
            "content": content,
            "chat_id": self.chat_id,
            "source": "server"
        })

    async def _on_chat_ended(self, payload: Dict[str, Any]) -> None:
        """聊天结束事件回调"""
        logger.info("聊天响应结束")
        await self.websocket_send_callback({
            "type": "chat_ended",
            "chat_id": self.chat_id,
            "source": "server"
        })

    async def _server_receive_loop(self):
        """服务器响应接收循环"""
        try:
            while self.is_running and not self.is_session_finished:
                response = await self.client.receive_server_response()
                await self._handle_server_response(response)
                await asyncio.sleep(0.01)  # 避免CPU过度使用
        except asyncio.CancelledError:
            logger.info("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息错误: {e}")

    async def process_audio_input(self, audio_data: bytes) -> None:
        """处理音频输入"""
        try:
            self.last_input_time = time.time()
            await self.client.task_request(audio_data)
            logger.info(f"已发送音频数据: {len(audio_data)} 字节")
        except Exception as e:
            logger.error(f"发送音频数据失败: {e}")

    async def send_say_hello(self, content: str) -> None:
        """发送打招呼消息"""
        try:
            await self.client.say_hello(content)
            logger.info(f"已发送打招呼消息: {content}")
        except Exception as e:
            logger.error(f"发送打招呼消息失败: {e}")

    async def send_chat_tts_text(self, content: str, start: bool = True, end: bool = True) -> None:
        """发送聊天TTS文本"""
        try:
            await self.client.chat_tts_text(content, start, end)
            logger.info(f"已发送TTS文本: {content[:50]}...")
        except Exception as e:
            logger.error(f"发送TTS文本失败: {e}")

    async def restart_session(self, bot_name: str = "豆包", dialog_id: str = None, strict_audit: bool = True) -> None:
        """重新启动会话"""
        try:
            # 先结束当前会话
            await self.client.finish_session()
            
            # 等待会话结束
            await asyncio.sleep(0.1)
            
            # 重新启动会话
            await self.client.start_session(bot_name, dialog_id, strict_audit)
            logger.info(f"已重新启动会话: bot_name={bot_name}, dialog_id={dialog_id}")
        except Exception as e:
            logger.error(f"重新启动会话失败: {e}")

    async def get_session_info(self) -> Dict[str, Any]:
        """获取会话信息"""
        return {
            "chat_id": self.chat_id,
            "session_id": self.session_id,
            "is_running": self.is_running,
            "is_session_finished": self.is_session_finished,
            "latency_stats": self.latency_stats.copy()
        }

    async def start(self) -> None:
        """启动对话会话"""
        try:
            logger.info(f"启动对话会话: {self.chat_id}")
            await self.client.connect()
            
            # 启动服务器响应接收任务
            self.server_receive_task = asyncio.create_task(self._server_receive_loop())
            
            # 等待会话结束
            while self.is_running and not self.is_session_finished:
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"对话会话错误: {e}")
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """清理资源"""
        try:
            # 取消任务
            if self.aura_task:
                self.aura_task.cancel()
            if self.server_receive_task:
                self.server_receive_task.cancel()
            
            # 结束会话
            if not self.is_session_finished:
                await self.client.finish_session()
                while not self.is_session_finished:
                    await asyncio.sleep(0.1)
            
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
            
            logger.info(f"对话会话已清理: {self.chat_id}")
            
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")

    def print_latency_summary(self) -> None:
        """打印延迟统计摘要"""
        if self.latency_stats['total_requests'] > 0:
            logger.info(f"=== 延迟统计摘要 ===")
            logger.info(f"总请求数: {self.latency_stats['total_requests']}")
            logger.info(f"平均延迟: {self.latency_stats['avg_latency']:.3f}秒")
            logger.info(f"最小延迟: {self.latency_stats['min_latency']:.3f}秒")
            logger.info(f"最大延迟: {self.latency_stats['max_latency']:.3f}秒")
            logger.info(f"总延迟: {self.latency_stats['total_latency']:.3f}秒")
        else:
            logger.info("没有延迟统计数据") 