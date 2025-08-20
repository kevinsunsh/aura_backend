import sys
import os
import asyncio
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(project_root)
sys.path.insert(0, project_root)

from agents.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from agents.prompt_manager.character.manager import DBManager as CharacterManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.prompt_manager.system_preset.manager import DBManager as SystemPresetManager
from agents.agent_memory.configuration import get_chat_model_by_type
from datetime import datetime
from api_protocol.constant import *

start_time = datetime.now()
from typing import List, Optional

class StreamingTagParser:
    def __init__(self, tag_callback=None):
        self.buffer: List[str] = []  # 保持完整的token列表
        self.state = "OUTSIDE"  # 初始状态：OUTSIDE
        self.tag_callback = tag_callback
        
        # 标签相关状态
        self.current_tag_type: str = ""  # 'speak', 'action', 'psych', 'scene'
        self.current_tag_attribute: str = ""  # 标签的属性值（如mood）
    # 接收新的文本块并处理（保持token完整性）
    async def feed(self, chunk: str):
        """接收新的文本块并处理（保持token完整性）"""
        # 不分割token，直接将完整chunk作为单个token处理
        if chunk:  # 只有非空chunk才添加
            self.buffer.append(chunk)
        await self._process_buffer()
    # 处理缓冲区内容
    async def _process_buffer(self):
        """处理缓冲区内容"""
        while self.buffer:
            processed = False
            
            if self.state == "OUTSIDE":
                processed = await self._handle_outside()
            elif self.state == "IN_TAG_NAME":
                processed = await self._handle_in_tag_name()
            elif self.state == "IN_TAG_ATTRIBUTE":
                processed = await self._handle_in_tag_attribute()
            elif self.state == "IN_TAG_CONTENT":
                processed = await self._handle_in_tag_content()
                
            if not processed:
                break
    # 处理OUTSIDE状态：查找<开始符
    async def _handle_outside(self):
        """处理OUTSIDE状态：查找<开始符"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找第一个<的位置
        tag_start_pos = token.find('<')
        if tag_start_pos != -1:
            # 找到了开始符
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果<前面有内容，根据规范应该忽略
            
            # 如果<后面还有内容，放回剩余部分
            if tag_start_pos + 1 < len(token):
                self.buffer.insert(0, token[tag_start_pos + 1:])
            
            self.state = "IN_TAG_NAME"
            self.current_tag_type = ""
            self.current_tag_attribute = ""
            return True
        else:
            # 没找到<，忽略整个token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_NAME状态：查找标签名称
    async def _handle_in_tag_name(self):
        """处理标签名称"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找:或>的位置
        colon_pos = token.find(':')
        close_pos = token.find('>')
        
        if colon_pos != -1 and (close_pos == -1 or colon_pos < close_pos):
            # 找到:且在>之前
            tag_name = self.current_tag_type + token[:colon_pos]
            self.current_tag_type = tag_name
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果:后面还有内容，放回剩余部分
            if colon_pos + 1 < len(token):
                self.buffer.insert(0, token[colon_pos + 1:])
            
            self.state = "IN_TAG_ATTRIBUTE"
            return True
        elif close_pos != -1:
            # 找到>，没有属性
            tag_name = self.current_tag_type + token[:close_pos]
            self.current_tag_type = tag_name
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果>后面还有内容，放回剩余部分
            if close_pos + 1 < len(token):
                self.buffer.insert(0, token[close_pos + 1:])
            
            # 发送标签开始事件
            if self.tag_callback:
                attributes = {}
                if len(self.current_tag_attribute) > 0:
                    # 如果是speak标签，attribute就是mood
                    if self.current_tag_type == "speak":
                        attributes["mood"] = self.current_tag_attribute
                    else:
                        attributes["attribute"] = self.current_tag_attribute
                
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "start",
                    "attributes": attributes
                })
            
            self.state = "IN_TAG_CONTENT"
            return True
        else:
            # 没找到:或>，整个token都是标签名的一部分
            self.current_tag_type += token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_ATTRIBUTE状态：查找标签属性
    async def _handle_in_tag_attribute(self):
        """处理标签属性"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找>的位置
        close_pos = token.find('>')
        if close_pos != -1:
            # 找到>
            attribute = self.current_tag_attribute + token[:close_pos]
            self.current_tag_attribute = attribute
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 如果>后面还有内容，放回剩余部分
            if close_pos + 1 < len(token):
                self.buffer.insert(0, token[close_pos + 1:])
            
            # 发送标签开始事件
            if self.tag_callback:
                attributes = {}
                if len(self.current_tag_attribute) > 0:
                    attributes["attribute"] = self.current_tag_attribute
                
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "start",
                    "attributes": attributes
                })
            
            self.state = "IN_TAG_CONTENT"
            return True
        else:
            # 没找到>，整个token都是属性的一部分
            self.current_tag_attribute += token
            self.buffer.pop(0)
            return True
    # 处理IN_TAG_CONTENT状态：查找标签内容
    async def _handle_in_tag_content(self):
        """处理标签内容直到遇到下一个<"""
        if not self.buffer:
            return False
            
        token = self.buffer[0]
        
        # 查找下一个<的位置（新标签开始）
        next_tag_pos = token.find('<')
        if next_tag_pos != -1:
            # 找到下一个标签开始，当前标签内容结束
            content = token[:next_tag_pos]
            
            if content and self.tag_callback:
                # 发送标签内容流
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "streaming",
                    "content": content
                })
            # 发送标签结束事件
            await self.tag_callback({
                "tag": self.current_tag_type,
                "status": "end"
            })
            
            # 移除已处理的token
            self.buffer.pop(0)
            
            # 将剩余部分放回缓冲区
            if next_tag_pos < len(token):
                self.buffer.insert(0, token[next_tag_pos:])
            
            # 重置状态，准备处理下一个标签
            self.current_tag_type = ""
            self.current_tag_attribute = ""
            self.state = "OUTSIDE"  # 重置状态，准备处理下一个标签
            return True
        else:
            # 没找到下一个<，整个token都是当前标签内容
            if token and self.tag_callback:
                await self.tag_callback({
                    "tag": self.current_tag_type,
                    "status": "streaming",
                    "content": token
                })
            self.buffer.pop(0)
            return True

async def tag_callback(payload):
    if payload["tag"] == "speak":
        if payload["status"] == "start":
            print(f"speak start: {payload['attributes']}")
            # print(f"speak start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            print(f"speak streaming: {payload['content']}")
            # print(f"speak streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            print(f"speak end")
            # print(f"speak end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "scene":
        if payload["status"] == "start":
            print(f"scene start")
            # print(f"env_desc start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            print(f"env_desc streaming: {payload['content']}")
            # print(f"env_desc streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            print(f"scene end")
            # print(f"env_desc end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "action":
        if payload["status"] == "start":
            print(f"action start")
            # print(f"action start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            print(f"action streaming: {payload['content']}")
            # print(f"action streaming time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            print(f"action end")
            # print(f"action end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "psych":
        if payload["status"] == "start":
            print(f"psych start")
            # print(f"emotion start time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "streaming":
            print(f"psych streaming: {payload['content']}")
            # print(f"action streaming time =======: {int((datetime.now() + start_time).total_seconds() * 1000)}ms")
            pass
        elif payload["status"] == "end":
            print(f"psych end")
            # print(f"emotion end time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
            pass
    elif payload["tag"] == "request_task":
        if payload["status"] == "start":
            print(f"request_task start")
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
    character = CharacterManager().get_character_by_name("Eva")
    print(f"fetch character time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    # system_preset = SystemPresetManager().get_system_preset_by_name("deepseek-R1 北棱预设v1.2 test(角色扮演特化)")
    # system_preset = SystemPresetManager().get_system_preset_by_name("（全能2.3）王のdeepseek-R1预设")
    system_preset = SystemPresetManager().get_system_preset_by_name("BreakLimitV3")
    print(f"fetch system preset time =======: {int((datetime.now() - start_time).total_seconds() * 1000)}ms")
    generator = PromptManager(
        chat_id="test_user_002",
        user_id="test_user_002",
        system_preset=system_preset,
        character=character,
        world_info_scanner=WorldInfoScanner(activate_world_books=["Aura0_1"])
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
