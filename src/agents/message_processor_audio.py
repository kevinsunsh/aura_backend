import asyncio
import logging
import uuid
from typing import Dict, Any, Callable
from datetime import datetime

from .aura_memory.message_store import MessageStore, Message
from .aura_memory.chat_stream import ChatStream, ChatStreamManager
from .doubao_client.dialog_session import DialogSession
from .message_processor_text import MessageProcessorText
from .doubao_client.config import ws_connect_config
logger = logging.getLogger(__name__)

class MessageProcessorAudio:
    """音频消息处理器，负责处理音频消息并启动ASR相关任务"""
    
    def __init__(self, 
                 message_store: MessageStore,
                 chat_stream_manager: ChatStreamManager,
                 db_conn_string: str,
                 websocket_send_callback: Callable[[Dict[str, Any]], None] = None):
        self.message_store = message_store
        self.chat_stream_manager = chat_stream_manager
        self.dialog_session = None
        self.db_conn_string = db_conn_string
        self.websocket_send_callback = websocket_send_callback
        self.processing_task = None  # 存储正在处理的任务
        self.task_lock = asyncio.Lock()
        self.is_running = True
        self.is_session_finished = False
        
        # 创建文本处理器用于处理ASR结果
        self.text_processor = MessageProcessorText(
            message_store=message_store,
            chat_stream_manager=chat_stream_manager,
            db_conn_string=db_conn_string,
            websocket_send_callback=websocket_send_callback
        )
    
    async def handle_audio_message(self, 
                                  message_data: Dict[str, Any], 
                                  chat_stream: ChatStream) -> Dict[str, Any]:
        """处理音频消息并启动异步任务接收ASR相关消息"""
        try:
            if self.dialog_session is None:
                self.dialog_session = DialogSession(chat_id=chat_stream.chat_id, ws_config=ws_connect_config, message_store=self.message_store, chat_stream_manager=self.chat_stream_manager, db_conn_string=self.db_conn_string, websocket_send_callback=self.websocket_send_callback)
                await self.dialog_session.start()
  
            
            await self.dialog_session.process_audio_input(message_data)
            
            logger.info(f"已启动音频消息处理任务: chat_id={chat_stream.chat_id}")
            
            return {
                "success": True,
                "action": "audio_task_started",
                "chat_id": chat_stream.chat_id
            }
            
        except Exception as e:
            logger.error(f"启动音频消息处理任务失败: {e}")
            return {
                "success": False,
                "error": f"启动音频处理任务失败: {str(e)}"
            }

    async def _cancel_existing_task(self):
        """取消现有的处理任务"""
        task_to_cancel = None
        try:
            async with self.task_lock:
                if self.processing_task:
                    task_to_cancel = self.processing_task
                    if not task_to_cancel.done():
                        logger.info(f"取消现有的处理任务")
                        task_to_cancel.cancel()
                    
                    # 清理任务记录
                    self.processing_task = None
            
            # 在锁外等待任务完成，避免死锁
            if task_to_cancel and not task_to_cancel.done():
                try:
                    await asyncio.wait_for(task_to_cancel, timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning(f"取消任务超时")
                except asyncio.CancelledError:
                    logger.debug(f"任务已成功取消")
                except Exception as e:
                    logger.error(f"取消任务时出错: {e}")
        except Exception as e:
            logger.error(f"取消任务时发生异常: {e}")

    async def _process_audio_task(self, 
                                chat_stream: ChatStream):
        """处理音频消息并启动aura聊天任务"""
        try:
            while self.is_running and not self.is_session_finished:
                response = await self.realtime_client.receive_server_response()
                await self._handle_server_response(response, chat_stream)
                await asyncio.sleep(0.01)  # 避免CPU过度使用
        except asyncio.CancelledError:
            logger.info("服务器接收任务已取消")
        except Exception as e:
            logger.error(f"服务器接收消息错误: {e}")

    async def _handle_server_response(self, response: Dict[str, Any], chat_stream: ChatStream):
        """处理服务器响应"""
        try:
            if not response or 'payload_msg' not in response:
                return
            
            payload = response['payload_msg']
            if not isinstance(payload, dict):
                return
            
            # 处理ASR相关消息
            if 'event' in payload:
                event_type = payload['event']
                
                if event_type == 450:  # ASRInfo - 首字识别
                    logger.info("收到ASRInfo事件：首字识别")
                    # 可以在这里处理首字识别逻辑
                    
                elif event_type == 451:  # ASRResponse - 语音识别结果
                    logger.info("收到ASRResponse事件：语音识别结果")
                    await self._handle_asr_response(payload, chat_stream)
                    
                elif event_type == 459:  # ASREnded - 语音识别结束
                    logger.info("收到ASREnded事件：语音识别结束")
                    await self._handle_asr_ended(payload, chat_stream)
                    
        except Exception as e:
            logger.error(f"处理服务器响应失败: {e}")

    async def _handle_asr_response(self, payload: Dict[str, Any], chat_stream: ChatStream):
        """处理ASR响应消息"""
        try:
            if 'results' in payload and payload['results']:
                result = payload['results'][0]
                text = result.get('text', '')
                is_interim = result.get('is_interim', False)
                
                if text and not is_interim:  # 只处理最终结果
                    logger.info(f"ASR最终识别结果: {text}")
                    
                    # 将识别结果存储到message_store
                    message = Message(
                        msg_id=str(uuid.uuid4()),
                        chat_id=chat_stream.chat_id,
                        user_id=chat_stream.chat_id,
                        platform="default",
                        m_type="asr_text",
                        content=text,
                        data={"source": "asr", "is_interim": is_interim},
                        created_at=int(datetime.now().timestamp() * 1000)
                    )
                    self.message_store.add_message(message)
                    
                    # 启动文本处理任务
                    await self.text_processor.process_text_message(chat_stream)
                    
        except Exception as e:
            logger.error(f"处理ASR响应失败: {e}")

    async def _handle_asr_ended(self, payload: Dict[str, Any], chat_stream: ChatStream):
        """处理ASR结束消息"""
        try:
            logger.info("ASR识别结束")
            self.is_session_finished = True
            
            # 可以在这里添加会话结束的处理逻辑
            
        except Exception as e:
            logger.error(f"处理ASR结束失败: {e}")

    async def cleanup(self):
        """清理资源"""
        try:
            await self._cancel_existing_task()
            await self.text_processor.cleanup()
            logger.info("MessageProcessor资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时发生异常: {e}")
