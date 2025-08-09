"""
SillyTavern Generate Logic Python Implementation
复刻SillyTavern的Generate函数逻辑到Python包中
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from agents.prompt_manager.character.models import CharacterModel as CharacterCard
from agents.prompt_manager.world_info.manager import DBManager as WorldInfoManager
from agents.prompt_manager.character.manager import DBManager as CharacterManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.agent_memory.message_store import MessageStore, Message

class GenerationType(Enum):
    NORMAL = "normal"
    REGENERATE = "regenerate"
    SWIPE = "swipe"
    IMPERSONATE = "impersonate"
    QUIET = "quiet"
    CONTINUE = "continue"

class ExtensionPromptTypes():
    NONE = -1
    IN_PROMPT = 0
    IN_CHAT = 1
    BEFORE_PROMPT = 2

class ExtensionPromptRoles():
    SYSTEM = 0
    USER = 1
    ASSISTANT = 2

@dataclass
class GenerationOptions:
    automatic_trigger: bool = False
    force_name2: bool = False
    quiet_prompt: str = ""
    quiet_to_loud: bool = False
    skip_wian: bool = False
    force_chid: Optional[int] = None
    signal: Optional[object] = None
    quiet_image: Optional[str] = None
    quiet_name: Optional[str] = None
    json_schema: Optional[Dict] = None
    depth: int = 0
    dry_run: bool = False

@dataclass
class CharacterCardFields:
    system: str = ""
    mes_examples: str = ""
    description: str = ""
    personality: str = ""
    persona: str = ""
    scenario: str = ""
    jailbreak: str = ""
    version: str = ""
    char_depth_prompt: str = ""
    creator_notes: str = ""

class GenerateManager:
    """生成管理器 - 复刻SillyTavern的Generate函数逻辑"""

    def __init__(self, chat_id: str, user_id: str, character: CharacterCard,
                world_info_scanner: Optional[WorldInfoScanner] = None):
        self.character = character
        self.world_info_scanner = world_info_scanner
        # 配置参数
        self.chat_id = chat_id
        self.name1 = user_id
        self.name2 = character.name
        self.main_api = "openai"
        self.is_instruct = False
        self.power_user_settings = {
            "prefer_character_prompt": True,
            "prefer_character_jailbreak": True,
            "instruct": {"enabled": False},
            "sysprompt": {"enabled": True, "content": ""},
            "context": {"names_as_stop_strings": True},
            "collapse_newlines": False,
            "force_name2": False
        }
        # 状态变量
        self.generation_started = None
        self.is_send_press = False
        self.chat_metadata = {}
        self.generated_prompt_cache = ""

        # 生成过程中的变量
        self.chat = []
        self.mes_send = []
        self.story_string = ""
        self.mes_examples_string = ""
        self.prompt_bias = ""
        self.quiet_prompt = ""

        # 世界书相关变量
        self.world_info_string = ""
        self.world_info_before = ""
        self.world_info_after = ""
        self.world_info_examples = []
        self.world_info_depth = []
        # 深度提示相关变量
        self.extension_prompts = {}
        self.depth_prompt_depth_default = 4
        self.depth_prompt_role_default = "system"
    
    def remove_depth_prompts(self):
        """移除所有深度提示 - 复刻removeDepthPrompts函数"""
        keys_to_remove = []
        for key in self.extension_prompts.keys():
            if key.startswith('DEPTH_PROMPT'):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.extension_prompts[key]
    
    def inject_depth_prompts_into_chat(self, chat_messages: List[Dict], is_continue: bool = False) -> List[int]:
        """将深度提示注入到聊天历史中 - 复刻doChatInject函数"""
        injected_indices = []
        total_inserted_messages = 0

        # 反转消息列表以便从后往前处理
        chat_messages.reverse()

        max_depth = self.get_extension_prompt_max_depth()

        for i in range(max_depth + 1):
            # 按角色优先级排序
            roles = ["system", "user", "assistant"]
            role_messages = []

            for role in roles:
                # 查找当前深度和角色的提示
                for key, prompt in self.extension_prompts.items():
                    if (prompt.get("depth") == i and
                        prompt.get("role") == role and
                        prompt.get("value")):

                        role_messages.append({
                            "name": "" if role == "system" else (self.name1 if role == "user" else self.name2),
                            "is_user": role == "user",
                            "mes": prompt["value"],
                            "extra": {
                                "type": "narrator" if role == "system" else None,
                            },
                        })

            if role_messages:
                depth = 1 if (is_continue and i == 0) else i
                inject_idx = depth + total_inserted_messages

                # 插入消息
                for j, message in enumerate(role_messages):
                    chat_messages.insert(inject_idx + j, message)
                    injected_indices.append(inject_idx + j)

                total_inserted_messages += len(role_messages)

        # 恢复消息列表顺序
        chat_messages.reverse()
        return injected_indices
    
    def substitute_params(self, content: str, name1: str = None, name2: str = None) -> str:
        """参数替换函数"""
        if not content:
            return ""

        # 基本环境变量
        environment = {
            "user": name1 or self.name1,
            "char": name2 or self.name2,
            "group": name2 or self.name2,
            "model": "gpt-3.5-turbo",
        }

        # 执行宏替换
        for key, value in environment.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        return content

    def get_character_card_fields(self) -> CharacterCardFields:
        """获取角色卡片字段"""
        result = CharacterCardFields()
        # 获取用户数据
        result.persona = self.base_chat_replace("")
        if not self.character:
            return result
        # 基础字段
        scenarioText = self.chat_metadata.get('scenario', getattr(self.character, 'scenario', ''))
        scenarioText = scenarioText if scenarioText else ""
        result.description = self.base_chat_replace(getattr(self.character, 'description', '').strip())
        result.scenario = self.base_chat_replace(scenarioText.strip())
        result.mes_examples = self.base_chat_replace(getattr(self.character, 'mes_example', '').strip())
        result.system = self.base_chat_replace(getattr(self.character, 'system_prompt', '').strip())
        result.jailbreak = self.base_chat_replace(getattr(self.character, 'post_history_instructions', '').strip())
        result.personality = self.base_chat_replace(getattr(self.character, 'personality', '').strip())
        result.version = getattr(self.character, 'character_version', '')
        depth_prompt = getattr(self.character, 'depth_prompt', None)
        depth_prompt_text = depth_prompt.get('prompt', '').strip() if depth_prompt else ''
        result.char_depth_prompt = self.base_chat_replace(depth_prompt_text)
        result.creator_notes = self.base_chat_replace(getattr(self.character, 'creator_notes', '').strip())
        return result

    def base_chat_replace(self, value: str) -> str:
        """基础聊天替换"""
        if not value or len(value) == 0:
            return ""

        # 参数替换
        value = self.substitute_params(value)

        # 换行符处理
        if self.power_user_settings["collapse_newlines"]:
            value = self.collapse_newlines(value)

        value = value.replace('\r', '')
        return value

    def collapse_newlines(self, text: str) -> str:
        """压缩换行符"""
        return re.sub(r'\n+', '\n', text)

    def build_chat_history(self, is_continue: bool = False) -> List[Dict]:
        """构建聊天历史 - 复刻SillyTavern的chat2构建逻辑"""
        history = self.chat_manager.get_history()
        chat2 = []

        # 按照SillyTavern的逻辑，按时间顺序构建（从最早到最新）
        for i in range(len(history.messages)):
            message = history.messages[i]
            formatted_message = self.format_message_history_item(message, self.is_instruct)
            chat2.append({
                "message": formatted_message,
                "extensionPrompts": []
            })

        return chat2

    def format_message_history_item(self, message, is_instruct: bool) -> str:
        """格式化消息历史项"""
        if is_instruct:
            if message.role == 'user':
                return f"{self.name1}: {message.content}\n"
            else:
                return f"{self.name2}: {message.content}\n"
        else:
            return f"{message.content}\n"

    def modify_last_prompt_line(self, last_mes_string: str, generation_type: GenerationType,
                               quiet_prompt: str = "", prompt_bias: str = "") -> str:
        """修改最后提示行 - 复刻modifyLastPromptLine逻辑"""
        # 添加静默提示
        if quiet_prompt and len(quiet_prompt) > 0:
            if self.is_instruct:
                last_mes_string += f"\n{quiet_prompt}"
            else:
                last_mes_string += f"\n{quiet_prompt}"

        # 指令模式处理
        if self.is_instruct and generation_type != GenerationType.CONTINUE:
            name = self.name1 if generation_type == GenerationType.IMPERSONATE else self.name2
            last_mes_string += f"\n{name}:"

        # 非指令模式处理
        if not self.is_instruct and generation_type == GenerationType.IMPERSONATE:
            if not last_mes_string.endswith('\n'):
                last_mes_string += '\n'
            last_mes_string += f"{self.name1}:"

        # 强制添加角色名称
        if not self.is_instruct and self.power_user_settings["force_name2"]:
            if not last_mes_string.endswith('\n'):
                last_mes_string += '\n'
            last_mes_string += f"{self.name2}:"

        return last_mes_string

    def parse_mes_examples(self, examples_str: str, is_instruct: bool) -> List[str]:
        """解析消息示例"""
        if not examples_str or len(examples_str) == 0 or examples_str == '<START>':
            return []

        if not examples_str.startswith('<START>'):
            examples_str = '<START>\n' + examples_str.strip()

        split_examples = re.split(r'<START>', examples_str, flags=re.IGNORECASE)[1:]
        return [f'<START>\n{block.strip()}\n' for block in split_examples]

    def get_combined_prompt(self, mes_send: List[Dict], generation_type: GenerationType,
                           story_string: str = "", mes_examples_string: str = "") -> str:
        """获取组合提示 - 复刻getCombinedPrompt逻辑"""
        # 修改最后一行
        if mes_send:
            last_message = mes_send[-1]["message"]
            modified_message = self.modify_last_prompt_line(
                last_message, generation_type, self.quiet_prompt, self.prompt_bias
            )
            mes_send[-1]["message"] = modified_message

        # 构建消息字符串
        mes_send_string = ""
        for item in mes_send:
            extension_prompts = "".join(item.get("extensionPrompts", []))
            mes_send_string += f"{extension_prompts}{item['message']}"

        # 添加聊天分隔符
        mes_send_string = self.add_chats_separator(mes_send_string)

        # 添加聊天前导
        mes_send_string = self.add_chats_preamble(mes_send_string)

        # 组合最终提示 - 包含世界书内容
        combined_prompt = (
            self.world_info_before +  # 世界书Before内容
            story_string +
            self.world_info_after +   # 世界书After内容
            mes_examples_string +
            mes_send_string +
            self.generated_prompt_cache
        )

        # 清理换行符
        combined_prompt = combined_prompt.replace('\r', '')

        if self.power_user_settings["collapse_newlines"]:
            combined_prompt = self.collapse_newlines(combined_prompt)

        return combined_prompt

    def add_chats_separator(self, mes_send_string: str) -> str:
        """添加聊天分隔符"""
        # 这里可以添加自定义分隔符逻辑
        return mes_send_string

    def add_chats_preamble(self, mes_send_string: str) -> str:
        """添加聊天前导"""
        # 这里可以添加自定义前导逻辑
        return mes_send_string

    def render_story_string(self, params: Dict) -> str:
        """渲染故事字符串"""
        story_parts = []

        if params.get("description"):
            story_parts.append(f"Description: {params['description']}")

        if params.get("personality"):
            story_parts.append(f"Personality: {params['personality']}")

        if params.get("scenario"):
            story_parts.append(f"Scenario: {params['scenario']}")

        if params.get("system"):
            story_parts.append(f"System: {params['system']}")

        return "\n".join(story_parts) + "\n" if story_parts else ""

    def set_extension_prompt(self, key, value, position, depth, scan = False, role = ExtensionPromptRoles.SYSTEM, filter = None):
        self.extension_prompts[key] = {
            "value": str(value),
            "position": int(position),
            "depth": int(depth),
            "scan": scan,
            "role": int(role),
            "filter": filter,
        }
    
    def get_extension_prompt_role_by_name(self, roleName) -> int:
        if isinstance(roleName, int) and roleName in ExtensionPromptRoles:
            return roleName
        if roleName == 'system':
            return ExtensionPromptRoles.SYSTEM
        if roleName == 'user':
            return ExtensionPromptRoles.USER
        if roleName == 'assistant':
            return ExtensionPromptRoles.ASSISTANT
        return ExtensionPromptRoles.SYSTEM
    
    async def generate(self, generation_type: GenerationType = GenerationType.NORMAL,
                      options: GenerationOptions = None) -> str:
        """主要生成函数 - 复刻Generate函数逻辑"""
        if options is None:
            options = GenerationOptions()

        print(f"Generate entered: {generation_type.value}")
        self.generation_started = datetime.now()

        # 处理静默提示
        self.quiet_prompt = options.quiet_prompt
        if self.quiet_prompt:
            self.quiet_prompt = self.substitute_params(self.quiet_prompt)
        # 获取角色卡片字段
        character_fields = self.get_character_card_fields()
        # 构建故事字符串
        story_string_params = {
            "description": character_fields.description,
            "personality": character_fields.personality,
            "persona": character_fields.persona,
            "scenario": character_fields.scenario,
            "mesExamples": character_fields.mes_examples,
            "system": character_fields.system,
            "jailbreak": character_fields.jailbreak,
            "charDepthPrompt": character_fields.char_depth_prompt,
            "creatorNotes": character_fields.creator_notes,
        }
        self.remove_depth_prompts()

        # 1v1 聊天
        depthPromptText = character_fields.char_depth_prompt or ''
        depthPromptDepth = self.character.depth_prompt.depth if self.character.depth_prompt else self.depth_prompt_depth_default
        depthPromptRole = self.get_extension_prompt_role_by_name(self.character.depth_prompt.role if self.character.depth_prompt else self.depth_prompt_role_default)
        self.set_extension_prompt('DEPTH_PROMPT', depthPromptText, ExtensionPromptTypes.IN_CHAT, depthPromptDepth, True, depthPromptRole)

        # 1v1 聊天，第一条消息反应用户/角色设置变化
        messages = MessageStore.get_instance().get_recent_messages(chat_id=self.chat_id, limit=100)
        print(messages)
        if len(self.chat) > 0:
            self.chat[0]["message"] = self.substitute_params(self.chat[0]["message"])
        coreChat = [x for x in self.chat if not x.get("is_system")]
        # setFloatingPrompt();
        # // Add persona description to prompt
        # addPersonaDescriptionExtensionPrompt();
        self.set_extension_prompt('QUIET_PROMPT', self.quiet_prompt, ExtensionPromptTypes.IN_PROMPT, 0, True)
        chatForWI = [f"{x.get('name')}: {x.get('message')}" if x.get('name') else x.get('message') for x in coreChat]
        chatForWI.reverse()
        globalScanData = {
            "personaDescription": character_fields.persona,
            "characterDescription": character_fields.description,
            "characterPersonality": character_fields.personality,
            "characterDepthPrompt": depthPromptText,
            "scenario": character_fields.scenario,
            "creatorNotes": character_fields.creator_notes,
            "trigger": 'normal',
        }
        activatedWorldInfo = await self.world_info_scanner.get_world_info_prompt(chatForWI, 4000, options.dry_run, globalScanData)
        self.world_info_before = activatedWorldInfo.world_info_before
        self.world_info_after = activatedWorldInfo.world_info_after
        self.world_info_string = activatedWorldInfo.world_info_string
        self.world_info_examples = activatedWorldInfo.world_info_examples if activatedWorldInfo.world_info_examples else []
        self.world_info_depth = activatedWorldInfo.world_info_depth if activatedWorldInfo.world_info_depth else []
        self.an_before = activatedWorldInfo.an_before if activatedWorldInfo.an_before else []
        self.an_after = activatedWorldInfo.an_after if activatedWorldInfo.an_after else []
       
        self.set_extension_prompt('QUIET_PROMPT', '', ExtensionPromptTypes.IN_PROMPT, 0, True)
        self.story_string = self.render_story_string(story_string_params)
        # 构建聊天历史
        is_continue = generation_type == GenerationType.CONTINUE
        self.mes_send = self.build_chat_history(is_continue)

        if not self.mes_send:
            print("No chat history available")
            return ""

        
        # 处理世界书信息
        chat_messages = [msg["message"] for msg in self.mes_send]
        self.process_world_info(chat_messages, options.dry_run)

        # 解析消息示例
        mes_examples_array = self.parse_mes_examples(character_fields.mes_examples, self.is_instruct)
        self.mes_examples_string = "".join(mes_examples_array)

        # 构建消息数组格式的提示
        messages = self.build_messages_array(character_fields, generation_type)

        # 发送生成请求
        if not options.dry_run:
            try:
                response = await self.ai_client.generate(messages)
                return response
            except Exception as e:
                print(f"Generation failed: {e}")
                return ""
        else:
            # 在dry_run模式下返回格式化的消息数组
            return self.format_messages_for_display(messages)

    def build_messages_array(self, character_fields, generation_type: GenerationType) -> list:
        """构建消息数组 - 复刻SillyTavern的消息格式"""
        messages = []

        # 1. 系统提示词
        if character_fields.system:
            messages.append({
                "role": "system",
                "content": character_fields.system
            })

        # 2. 角色描述和示例
        character_content = ""
        if character_fields.description:
            character_content += character_fields.description + "\n"
        if self.mes_examples_string:
            character_content += self.mes_examples_string

        if character_content:
            messages.append({
                "role": "system",
                "content": character_content
            })

        # 3. 开始新聊天标记
        messages.append({
            "role": "system",
            "content": "[Start a new Chat]"
        })

        # 4. 角色的第一条消息（如果有）
        if hasattr(self.character, 'first_mes') and self.character.first_mes:
            messages.append({
                "role": "assistant",
                "content": self.character.first_mes
            })

        # 5. 聊天历史
        history = self.chat_manager.get_history()
        for message in history.messages:
            if message.role == 'user':
                messages.append({
                    "role": "user",
                    "content": message.content
                })
            else:
                messages.append({
                    "role": "assistant",
                    "content": message.content
                })

        return messages

    def format_messages_for_display(self, messages: list) -> str:
        """格式化消息数组用于显示"""
        result = "=== FULL REQUEST BODY ===\n"
        result += "{\n"
        result += '  "messages": [\n'

        for i, message in enumerate(messages):
            result += '    {\n'
            result += f'      "role": "{message["role"]}",\n'
            # 处理content中的换行符
            content = message["content"].replace('\n', '\\n').replace('"', '\\"')
            result += f'      "content": "{content}"\n'
            result += '    }'
            if i < len(messages) - 1:
                result += ','
            result += '\n'

        result += '  ],\n'
        result += '  "model": "deepseek-v3-250324",\n'
        result += '  "temperature": 1,\n'
        result += '  "max_tokens": 300,\n'
        result += '  "stream": true,\n'
        result += '  "presence_penalty": 0,\n'
        result += '  "frequency_penalty": 0,\n'
        result += '  "top_p": 1\n'
        result += '}\n'
        result += "=== END AI REQUEST ==="

        return result
