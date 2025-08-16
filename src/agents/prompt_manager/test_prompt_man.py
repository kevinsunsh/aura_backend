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

start_time = datetime.now()

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
        # print(f"feed delay {self.buffer}: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
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
            attr_str: 属性字符串，如 'name=value params="上海当前天气 2025年8月12日"'
            
        Returns:
            dict: 解析后的属性字典
        """
        attributes = {}
        
        # 匹配两种格式：
        # 1. name=value（值以空格结束，如：mood=happy level=3）
        # 2. name="value" 或 name='value'（值可以包含空格，如：params="上海当前天气 2025年8月12日"）
        pattern = r'(\w+)=(?:([^\s]+)|([\'"])(.*?)\3)'
        matches = re.findall(pattern, attr_str)
        
        for match in matches:
            key = match[0]
            # 如果第二个组有值（无引号），使用它；否则使用第四个组（有引号）
            value = match[1] if match[1] else match[3]
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
    if payload["tag"] == "speak":
        if payload["status"] == "start":
            # print(f"speak start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"speak streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"speak end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "env_desc":
        if payload["status"] == "start":
            # print(f"env_desc start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"env_desc streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"env_desc end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "action":
        if payload["status"] == "start":
            # print(f"action start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"action streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"action end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "emotion":
        if payload["status"] == "start":
            # print(f"emotion start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"emotion streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"emotion end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "request_task":
        if payload["status"] == "start":
            # print(f"request_task start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"request_task streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"request_task end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "dismiss_task":
        if payload["status"] == "start":
            # print(f"dismiss_task start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            # print(f"dismiss_task streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            # print(f"dismiss_task end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass

async def main():
    print(f"start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    parser = StreamingTagParser(tag_callback=tag_callback)
    character = CharacterManager().get_character_by_name("Nova")
    print(f"fetch character time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    # system_preset = SystemPresetManager().get_system_preset_by_name("deepseek-R1 北棱预设v1.2 test(角色扮演特化)")
    system_preset = SystemPresetManager().get_system_preset_by_name("（全能2.3）王のdeepseek-R1预设")
    print(f"fetch system preset time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    generator = PromptManager(
        chat_id="test_user_333555",
        user_id="test_user_333555",
        system_preset=system_preset,
        character=character,
        world_info_scanner=WorldInfoScanner()
    )
    print(f"prompt manager init time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    prompts = await generator.generate(GenerationType.NORMAL, GenerationOptions())
    print(f"prompt generate tokens =======: {prompts[1]}")
    chat_model = get_chat_model_by_type("pfc_chat")
    # messages = []
    # for prompt in prompts[0]:
    #     print(prompt)
    #     if prompt["role"] == "user":
    #         messages.append(HumanMessage(content=prompt["content"]))
    #     elif prompt["role"] == "assistant":
    #         messages.append(AIMessage(content=prompt["content"]))
    #     else:
    #         messages.append(SystemMessage(content=prompt["content"]))
    first_chunk = True
    first_chunk_time = datetime.now().timestamp()
    print(f"start generate time =======: {first_chunk_time}ms")
    async for chunk in chat_model.astream(prompts[0], extra_body={"thinking": {"type": "disabled"}}):
        if hasattr(chunk, 'content'):
            # if first_chunk:
            #     first_chunk = False
            print(f"first chunk time =======: {int((datetime.now().timestamp() - first_chunk_time) * 1000)}ms, {chunk.content}")
            first_chunk_time = datetime.now().timestamp()
            await parser.feed(chunk.content)
    first_chunk = True
    second_chunk_time = datetime.now().timestamp()
    print(f"start generate time =======: {second_chunk_time}ms")
    async for chunk in chat_model.astream(prompts[0], extra_body={"thinking": {"type": "disabled"}}):
        if hasattr(chunk, 'content'):
            # if first_chunk:
            #     first_chunk = False
            print(f"second chunk time =======: {int((datetime.now().timestamp() - second_chunk_time) * 1000)}ms, {chunk.content}")
            second_chunk_time = datetime.now().timestamp()
            await parser.feed(chunk.content)

if __name__ == "__main__":
    asyncio.run(main())
