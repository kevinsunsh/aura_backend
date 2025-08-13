import sys
import os
import asyncio
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(project_root)
sys.path.insert(0, project_root)

from agents.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from agents.prompt_manager.character.models import CharacterModel as CharacterCard
from agents.prompt_manager.character.manager import DBManager as CharacterManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.prompt_manager.system_preset.manager import DBManager as SystemPresetManager
from agents.prompt_manager.system_preset.models import SystemPresetModel
from configuration import get_chat_model_by_type
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger
from datetime import datetime
import re
from api_protocol.constant import *

class StreamingTagParser:
    def __init__(self, tag_callback=None):
        self.buffer = ""
        self.state = "OUTSIDE"
        self.current_tag = None
        self.attributes = {}
        self.tag_callback = tag_callback

    async def feed(self, chunk: str):
        """接收新的文本块"""
        self.buffer += chunk
        await self._process_state()

    async def _process_state(self):
        """状态机处理"""
        if self.state == "OUTSIDE":
            await self._handle_outside()
        elif self.state == "CONTENT_STREAMING":
            await self._handle_content_streaming()

    async def _handle_outside(self):
        """处理 OUTSIDE 状态"""
        # 查找开始标签 '<'
        pos = self.buffer.find('<')
        if pos == -1:
            return  # 等待更多内容
        # 输出标签前的纯文本内容（如果有）
        if pos > 0:
            self.buffer = self.buffer[pos:]
            return
        # 检查是否是标签开始
        match = re.match(r'<(\w+)([^>]*?)>', self.buffer)
        if match:
            tag_name = match.group(1)
            attr_str = match.group(2)
            self.current_tag = tag_name
            # 简化属性解析，直接去掉外层引号
            self.attributes = {}
            if attr_str.strip():
                # 使用正则表达式匹配，然后去掉外层引号
                self.attributes = self._parse_attributes_simple(attr_str)
            # 发送标签开始事件
            await self._send_tag_start()
            # 进入内容流式处理状态
            self.state = "CONTENT_STREAMING"
            self.buffer = self.buffer[match.end():]
            await self._process_state()  # 继续处理

    async def _handle_content_streaming(self):
        """处理 CONTENT_STREAMING 状态"""
        # 查找结束标签
        close_tag = f"</{self.current_tag}>"
        end_pos = self.buffer.find(close_tag)
        
        if end_pos != -1:
            # 找到结束标签，发送剩余内容并结束
            content = self.buffer[:end_pos]
            if content:
                await self._send_content_chunk(content)
            
            # 发送标签结束事件
            await self._send_tag_end()
            
            # 重置状态
            self.state = "OUTSIDE"
            self.current_tag = None
            self.attributes = {}
            self.buffer = self.buffer[end_pos + len(close_tag):]
            await self._process_state()  # 继续处理
        else:
            # 没找到结束标签，检查部分匹配
            partial_match_len = self._get_partial_match_len(close_tag)
            safe_len = len(self.buffer) - partial_match_len
            
            if safe_len > 0:
                # 有安全内容可以发送
                content = self.buffer[:safe_len]
                await self._send_content_chunk(content)
                self.buffer = self.buffer[safe_len:]
            # 如果没有安全内容，等待更多输入

    def _get_partial_match_len(self, close_tag: str) -> int:
        """计算 buffer 尾部与 close_tag 的最大前缀匹配长度"""
        max_check = min(len(self.buffer), len(close_tag))
        matched = 0
        for i in range(max_check):
            if self.buffer[-max_check + i] == close_tag[i]:
                matched += 1
            else:
                break
        return matched

    def _parse_attributes_simple(self, attr_str: str) -> dict:
        """
        简化属性解析，直接去掉外层引号
        
        Args:
            attr_str: 属性字符串，如 'name="value" params="上海当前天气 2025年8月12日"'
            
        Returns:
            dict: 解析后的属性字典
        """
        attributes = {}
        
        # 匹配 name="value" 或 name='value' 或 name=value 格式
        # 使用正则表达式匹配，然后去掉外层引号
        # 修复：无引号的值应该匹配到下一个属性或标签结束，而不是到空格
        pattern = r'(\w+)=([\'"])(.*?)\2'
        matches = re.findall(pattern, attr_str)
        
        for key, quote, value in matches:
            attributes[key] = value.strip()
        return attributes

    async def _send_tag_start(self):
        """发送标签开始事件"""
        if not self.tag_callback:
            return
        await self.tag_callback({
            "tag": self.current_tag,
            "status": "start",
            "attributes": self.attributes
        })

    async def _send_content_chunk(self, content: str):
        """发送内容块"""
        if not self.tag_callback or not content:
            return
        await self.tag_callback({
            "tag": self.current_tag,
            "status": "streaming",
            "content": content
        })

    async def _send_tag_end(self):
        """发送标签结束事件"""
        if not self.tag_callback:
            return
        await self.tag_callback({
            "tag": self.current_tag,
            "status": "end"
        })

async def tag_callback(payload):
    print(payload)

async def main():
    parser = StreamingTagParser(tag_callback=tag_callback)
    character = CharacterManager().get_character_by_name("Seraphina")
    system_preset = SystemPresetManager().get_system_preset_by_name("deepseek-R1 北棱预设v1.2 test(角色扮演特化)")
    generator = PromptManager(
        chat_id="test_user_123444",
        user_id="test_user_123444",
        system_preset=system_preset,
        character=character,
        world_info_scanner=WorldInfoScanner()
    )
    prompts = await generator.generate(GenerationType.NORMAL, GenerationOptions())
    chat_model = get_chat_model_by_type("pfc_chat")
    messages = []
    for prompt in prompts[0]:
        if prompt["role"] == "user":
            messages.append(HumanMessage(content=prompt["content"]))
        elif prompt["role"] == "assistant":
            messages.append(AIMessage(content=prompt["content"]))
        else:
            messages.append(SystemMessage(content=prompt["content"]))
    for chunk in chat_model.stream(messages, extra_body={"thinking": {"type": "disabled"}}):
        if hasattr(chunk, 'content'):
            await parser.feed(chunk.content)

if __name__ == "__main__":
    asyncio.run(main())