"""
简单的消息存储类
"""

class MessageStore:
    def __init__(self):
        self.messages = {}
    
    def get_or_create_chat_stream(self, chat_id: str):
        """获取或创建聊天流"""
        if chat_id not in self.messages:
            self.messages[chat_id] = []
        return self.messages[chat_id]
    
    def acquire_message_process_lock(self, chat_id: str):
        """获取消息处理锁（简化版本，总是返回False）"""
        return False
    
    def get_and_update_chat_stream_messages(self, chat_id: str):
        """获取并更新聊天流消息"""
        if chat_id not in self.messages:
            self.messages[chat_id] = []
        return self.messages[chat_id] 