import re
import uuid
import copy
import httpx
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from agents.agent_memory.task.task_manager import TaskManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner
from agents.agent_memory.message_store import MessageStore, MessageModel
from agents.prompt_manager.character.models import CharacterModel as CharacterCard
from agents.prompt_manager.utils import count_tokens_openai, get_response_format_prompt
from agents.prompt_manager.system_preset.models import SystemPresetModel, PromptModel, InjectionPosition
from agents.agent_memory.summary_mem.manager import DBManager as MemoryManager

class GenerationType(Enum):
    NORMAL = "normal"
    REGENERATE = "regenerate"
    SWIPE = "swipe"
    IMPERSONATE = "impersonate"
    QUIET = "quiet"
    CONTINUE = "continue"

class ExtensionPromptTypes:
    NONE = -1
    IN_PROMPT = 0
    IN_CHAT = 1
    BEFORE_PROMPT = 2

class ExtensionPromptRoles:
    SYSTEM = 0
    USER = 1
    ASSISTANT = 2

@dataclass
class GenerationOptions:
    quiet_to_loud: bool = False
    skip_wian: bool = False
    force_chid: Optional[int] = None
    signal: Optional[object] = None
    quiet_name: Optional[str] = None
    json_schema: Optional[Dict] = None
    depth: int = 0

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

class ChatCompletion:
    """聊天完成类 - 复刻SillyTavern的ChatCompletion功能"""
    
    def __init__(self):
        self.logging_enabled = False
        self.max_context = 4096
        self.max_tokens = 512
        self.chat_messages = []

    def enable_logging(self):
        """启用日志记录"""
        self.logging_enabled = True

    def log(self, message: str):
        """记录日志"""
        if self.logging_enabled:
            print(f"ChatCompletion: {message}")

    def set_token_budget(self, max_context: int, max_tokens: int):
        """设置token预算"""
        self.max_context = max_context
        self.max_tokens = max_tokens

    def get_chat(self) -> List[Dict]:
        """获取聊天消息"""
        chat = []
        total_tokens = 0
        for item in self.chat_messages:
            if "collection" in item:
                for message in item["collection"]:
                    if len(message["content"]) == 0:
                        continue
                    chat.append({
                        "role": message["role"],
                        "content": message["content"],
                        "tokens": message["tokens"]
                    })
                    total_tokens += message["tokens"]
        return chat, total_tokens
    
    async def squash_system_messages(self):
        """压缩系统消息"""
        pass

def evaluate_macros(content, env, post_process_fn=None):
    """
    替换字符串中的 {{macro}} 参数。
    :param content: 需要替换参数的字符串
    :param env: 宏名称到值的映射。如果值是函数，则调用并使用其返回值
    :param post_process_fn: 替换宏值前的处理函数
    :return: 替换后的字符串
    """
    if not content:
        return ''
    if post_process_fn is None:
        post_process_fn = lambda x: x
    raw_content = content

    # 内置宏（变量前）
    pre_env_macros = [
        # 兼容旧格式
        (re.compile(r'<USER>', re.I), lambda m: env['user']() if callable(env.get('user')) else env.get('user', '')),
        (re.compile(r'<BOT>', re.I), lambda m: env['char']() if callable(env.get('char')) else env.get('char', '')),
        (re.compile(r'<CHAR>', re.I), lambda m: env['char']() if callable(env.get('char')) else env.get('char', '')),
        (re.compile(r'<CHARIFNOTGROUP>', re.I), lambda m: env['group']() if callable(env.get('group')) else env.get('group', '')),
        (re.compile(r'<GROUP>', re.I), lambda m: env['group']() if callable(env.get('group')) else env.get('group', '')),
        # 下面这些需要你自己实现相关函数
        # getDiceRollMacro(),
        # *getInstructMacros(env),
        # *getVariableMacros(),
        (re.compile(r'{{newline}}', re.I), lambda m: '\n'),
        (re.compile(r'(?:\r?\n)*{{trim}}(?:\r?\n)*', re.I), lambda m: ''),
        (re.compile(r'{{noop}}', re.I), lambda m: ''),
        # (re.compile(r'{{input}}', re.I), lambda m: str(get_input_textarea_value())),
    ]
    # 内置宏（变量后）
    post_env_macros = [
        (re.compile(r'{{maxPrompt}}', re.I), lambda m: str(env.get('max_context', ''))),
        (re.compile(r'{{lastMessage}}', re.I), lambda m: env.get('last_message', '')),
        (re.compile(r'{{lastMessageId}}', re.I), lambda m: str(env.get('last_message_id', ''))),
        (re.compile(r'{{lastUserMessage}}', re.I), lambda m: env.get('last_user_message', '')),
        (re.compile(r'{{lastCharMessage}}', re.I), lambda m: env.get('last_char_message', '')),
        (re.compile(r'{{firstIncludedMessageId}}', re.I), lambda m: str(env.get('first_included_message_id', ''))),
        (re.compile(r'{{firstDisplayedMessageId}}', re.I), lambda m: str(env.get('first_displayed_message_id', ''))),
        (re.compile(r'{{lastSwipeId}}', re.I), lambda m: str(env.get('last_swipe_id', ''))),
        (re.compile(r'{{currentSwipeId}}', re.I), lambda m: str(env.get('current_swipe_id', ''))),
        (re.compile(r'{{reverse:(.+?)}}', re.I), lambda m: m.group(1)[::-1]),
        (re.compile(r'\{\{\/\/([\s\S]*?)\}\}', re.M), lambda m: ''),
        (re.compile(r'{{time}}', re.I), lambda m: datetime.now().strftime('%H:%M')),
        (re.compile(r'{{date}}', re.I), lambda m: datetime.now().strftime('%Y年%m月%d日')),
        (re.compile(r'{{weekday}}', re.I), lambda m: ['星期一','星期二','星期三','星期四','星期五','星期六','星期日'][datetime.now().weekday()]),
        (re.compile(r'{{isotime}}', re.I), lambda m: datetime.now().strftime('%H:%M')),
        (re.compile(r'{{isodate}}', re.I), lambda m: datetime.now().strftime('%Y-%m-%d')),
        (re.compile(r'{{datetimeformat +([^}]*)}}', re.I), lambda m: datetime.now().strftime(m.group(1))),
        (re.compile(r'{{idle_duration}}', re.I), lambda m: str(env.get('idle_duration', ''))),
        (re.compile(r'{{time_UTC([-+]\d+)}}', re.I), lambda m: (datetime.utcnow()).strftime('%H:%M')),
        # getTimeDiffMacro(),
        # getBannedWordsMacro(),
        # getRandomReplaceMacro(),
        # getPickReplaceMacro(raw_content),
    ]
    # 注册宏（env变量）
    # 这里假设env是dict
    nonce = str(uuid.uuid4())
    env_macros = []
    for var_name, param in env.items():
        regex = re.compile(r'{{' + re.escape(var_name) + r'}}', re.I)
        def make_env_replace(param):
            def env_replace(m):
                value = param(nonce) if callable(param) else param
                # 这里可以加sanitize
                return str(value)
            return env_replace
        env_macros.append((regex, make_env_replace(param)))
    # 合并所有宏
    macros = pre_env_macros + env_macros + post_env_macros
    # 依次替换
    for regex, replace in macros:
        if not content:
            break
        # 如果不是尖括号宏且没有{{，则跳过
        if not regex.pattern.startswith('<') and '{{' not in content:
            break
        try:
            content = regex.sub(lambda m: post_process_fn(replace(m)), content)
        except Exception as e:
            print(f"宏替换失败: {regex.pattern} in {content}, 错误: {e}")
    return content

class PromptManager:
    """生成管理器 - 复刻SillyTavern的Generate函数逻辑"""

    def __init__(self, chat_id: str, user_id: str, system_preset: SystemPresetModel, character: CharacterCard,
                world_info_scanner: Optional[WorldInfoScanner] = None, process_timer: Any = None):
        self.system_preset = system_preset
        self.character = character
        self.character_fields = None
        self.character_id = 100001
        self.world_info_scanner = world_info_scanner
        self.activated_prompts = []
        for entry in self._get_prompt_order_for_character():
            if entry["enabled"]:
                self.activated_prompts.append(entry["identifier"])
        # 配置参数
        self.chat_id = chat_id
        self.name1 = user_id
        self.name2 = character.name
        self.language = "ZH-CN"
        self.main_api = "openai"
        self.default_sysprompt_content = "Write {{char}}\'s next reply in a fictional chat between {{char}} and {{user}}."
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
        self.process_timer = process_timer
    
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
    
    def parse_mes_examples(self, examples_str: str) -> List[str]:
        """解析消息示例"""
        if not examples_str or len(examples_str) == 0 or examples_str == '<START>':
            return []
        if not examples_str.startswith('<START>'):
            examples_str = '<START>\n' + examples_str.strip()
        split_examples = re.split(r'<START>', examples_str, flags=re.IGNORECASE)[1:]
        return [f'<START>\n{block.strip()}\n' for block in split_examples]
    
    def substitute_params(
        self,
        content: str,
        _name1: str = None,
        _name2: str = None,
        _original: str = None,
        _group: str = None,
        _replace_character_card: bool = True,
        additional_macro: dict = None,
        post_process_fn=None
    ) -> str:
        """
        替换字符串中的{{macro}}参数。
        :param content: 需要替换参数的字符串
        :param _name1: 用户名，未提供则使用self.name1
        :param _name2: 角色名，未提供则使用self.name2
        :param _original: 用于{{original}}替换的原始消息
        :param _group: 群组成员列表
        :param _replace_character_card: 是否替换角色卡片宏
        :param additional_macro: 额外的环境变量
        :param post_process_fn: 对每个替换宏的后处理函数
        :return: 替换参数后的字符串
        """
        if not content:
            return ""
        
        environment = {}
        # 处理original宏，确保只替换一次
        if isinstance(_original, str):
            original_substituted = {"used": False}
            def original_func():
                if original_substituted["used"]:
                    return ""
                original_substituted["used"] = True
                return _original
            environment["original"] = original_func
        
        def get_group_value(include_muted: bool):
            # 这里只实现字符串和self.name2的简单逻辑，复杂群组逻辑需根据实际项目补充
            if isinstance(_group, str):
                return _group
            # 假设没有复杂群组，直接返回_name2或self.name2
            return _name2 if _name2 is not None else getattr(self, "name2", "")
        
        if _replace_character_card:
            fields = self.character_fields
            environment["charPrompt"] = getattr(fields, "system", "") or ""
            environment["charInstruction"] = getattr(fields, "jailbreak", "") or ""
            environment["charJailbreak"] = getattr(fields, "jailbreak", "") or ""
            environment["description"] = getattr(fields, "description", "") or ""
            environment["personality"] = getattr(fields, "personality", "") or ""
            environment["scenario"] = getattr(fields, "scenario", "") or ""
            environment["persona"] = getattr(fields, "persona", "") or ""
            def mes_examples_func(*args):
                # 这里假设power_user和main_api等全局变量已在self中定义
                mes_examples_array = self.parse_mes_examples(getattr(fields, "mes_examples", ""))
                return "".join(mes_examples_array)
            environment["mesExamples"] = mes_examples_func
            environment["mesExamplesRaw"] = getattr(fields, "mes_examples", "") or ""
            environment["charVersion"] = getattr(fields, "version", "") or ""
            environment["char_version"] = getattr(fields, "version", "") or ""
            environment["charDepthPrompt"] = getattr(fields, "char_depth_prompt", "") or ""
            environment["creatorNotes"] = getattr(fields, "creator_notes", "") or ""
        # 必须最后替换，以便在{{description}}等内部也能被替换
        environment["user"] = _name1 if _name1 is not None else getattr(self, "name1", "")
        environment["char"] = _name2 if _name2 is not None else getattr(self, "name2", "")
        environment["group"] = environment["charIfNotGroup"] = get_group_value(True)
        environment["groupNotMuted"] = get_group_value(False)
        # 假设有get_generating_model方法
        if hasattr(self, "get_generating_model"):
            environment["model"] = self.get_generating_model()
        else:
            environment["model"] = ""

        if additional_macro and isinstance(additional_macro, dict):
            environment.update(additional_macro)
        # evaluate_macros需实现宏替换逻辑
        if post_process_fn is None or not callable(post_process_fn):
            post_process_fn = lambda x: x
        
        return evaluate_macros(content, environment, post_process_fn)
    
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
        value = self.substitute_params(value, _name1=self.name1, _name2=self.name2, _original=None, _group=None, _replace_character_card=False)
        # 换行符处理
        value = self.collapse_newlines(value)
        value = value.replace('\r', '')
        return value
    
    def collapse_newlines(self, text: str) -> str:
        """压缩换行符"""
        return re.sub(r'\n+', '\n', text)
    
    def build_chat_history(self) -> List[Dict]:
        """构建聊天历史 - 复刻SillyTavern的chat2构建逻辑"""
        messages = MessageStore.get_instance().get_recent_messages(chat_id=self.chat_id, limit=10)
        chat2 = []
        # 按照SillyTavern的逻辑，按时间顺序构建（从最早到最新）
        for i in range(len(messages)):
            message = messages[i]
            formatted_message = self.format_message_history_item(message)
            chat2.append({
                "message": formatted_message,
                "extensionPrompts": []
            })
        return chat2
    
    def format_message_history_item(self, message) -> str:
        """格式化消息历史项"""
        return f"{message.content}\n"
    
    def modify_last_prompt_line(self, last_mes_string: str, generation_type: GenerationType) -> str:
        """修改最后提示行 - 复刻modifyLastPromptLine逻辑"""
        # 指令模式处理
        if generation_type == GenerationType.IMPERSONATE:
            last_mes_string += f"\n{self.name1}:"
        return last_mes_string
    
    def get_combined_prompt(self, mes_send: List[Dict], generation_type: GenerationType,
                           story_string: str = "", mes_examples_string: str = "") -> str:
        """获取组合提示 - 复刻getCombinedPrompt逻辑"""
        # 修改最后一行
        if mes_send:
            last_message = mes_send[-1]["message"]
            modified_message = self.modify_last_prompt_line(
                last_message, generation_type
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
    
    @dataclass
    class PrepareMessagesParams:
        """准备消息的参数类 - 复刻SillyTavern的prepareOpenAIMessages参数"""
        name2: str = ""
        char_description: str = ""
        char_description_tokens: int = 0
        char_personality: str = ""
        char_personality_tokens: int = 0
        scenario: str = ""
        scenario_tokens: int = 0
        world_info_before: str = ""
        world_info_before_tokens: int = 0
        world_info_after: str = ""
        world_info_after_tokens: int = 0
        bias: str = ""
        type: str = ""
        cycle_prompt: str = ""
        system_prompt_override: Optional[str] = None
        jailbreak_prompt_override: Optional[str] = None
        extension_prompts: Dict = field(default_factory=dict)
        messages: List[MessageModel] = field(default_factory=list)
        message_examples: List[str] = field(default_factory=list)
        tool_calls: List[str] = field(default_factory=list)

    class TokenBudgetExceededError(Exception):
        """Token预算超出异常"""
        pass

    class InvalidCharacterNameError(Exception):
        """角色名称无效异常"""
        pass

    async def prepare_openai_messages(self, params: PrepareMessagesParams) -> tuple[List[Dict], Any]:
        """
        准备OpenAI消息的主函数 - 复刻SillyTavern的prepareOpenAIMessages逻辑
        处理提示词、准备聊天历史、管理token预算和处理各种用户设置
        Args:
            params: 包含所有消息准备参数的数据类
        Returns:
            包含准备好的聊天消息和token计数的元组
        Raises:
            TokenBudgetExceededError: 当强制提示超出上下文大小时
            InvalidCharacterNameError: 当角色名称包含非法字符时
        """
        # 如果没有选择角色且为测试运行，无法准确计算token
        if not self.character:
            return [None, False]

        chat_completion = ChatCompletion()
        user_settings = self.get_user_settings()
        chat_completion.set_token_budget(
            user_settings.get("openai_max_context", 4096),
            user_settings.get("openai_max_tokens", 512)
        )
        try:
            # 合并标记和有序用户提示与系统提示
            prompts = await self.prepare_prompts_for_chat_completion({
                "scenario": params.scenario,
                "scenario_tokens": params.scenario_tokens,
                "char_personality": params.char_personality,
                "char_personality_tokens": params.char_personality_tokens,
                "name2": params.name2,
                "world_info_before": params.world_info_before,
                "world_info_before_tokens": params.world_info_before_tokens,
                "world_info_after": params.world_info_after,
                "world_info_after_tokens": params.world_info_after_tokens,
                "char_description": params.char_description,
                "char_description_tokens": params.char_description_tokens,
                "bias": params.bias,
                "extension_prompts": params.extension_prompts,
                "system_prompt_override": params.system_prompt_override,
                "jailbreak_prompt_override": params.jailbreak_prompt_override,
                "type": params.type,
            })
            # 在预算允许的范围内填充聊天完成内容
            await self.populate_chat_completion(prompts, chat_completion, {
                "bias": params.bias,
                "type": params.type,
                "cycle_prompt": params.cycle_prompt,
                "messages": params.messages,
                "message_examples": params.message_examples
            })
        except self.TokenBudgetExceededError as error:
            print("强制提示超出上下文大小")
            chat_completion.log("Mandatory prompts exceed the context size.")
            self.error = "强制提示的token不足。请提高token限制或禁用自定义提示。"
        except self.InvalidCharacterNameError as error:
            print("计算token时出错：角色名称无效")
            chat_completion.log("Invalid character name")
            self.error = "至少一个角色的名称包含空格或特殊字符。请检查您的用户名和角色名。"
        except Exception as error:
            print("计算token时发生未知错误。更多信息可能在控制台中可用。")
            chat_completion.log("----- 准备提示时发生意外错误 -----")
            chat_completion.log(str(error))
            chat_completion.log("----------------------------------------------------")
        finally:
            # 将聊天完成传递给提示管理器进行检查
            self.set_chat_completion(chat_completion)
            if self.get_squash_system_messages():
                await chat_completion.squash_system_messages()
        
        chat, total_tokens = chat_completion.get_chat()
        return [chat, total_tokens]
    
    def get_user_settings(self) -> Dict[str, Any]:
        """获取用户设置"""
        return {
            "openai_max_context": 4096,
            "openai_max_tokens": 512,
        }
    
    def set_chat_completion(self, chat_completion):
        """设置聊天完成对象"""
        self.chat_completion = chat_completion
    
    def get_squash_system_messages(self) -> bool:
        """获取是否压缩系统消息的设置"""
        return False
    
    async def prepare_prompts_for_chat_completion(self, options: Dict) -> Dict:
        """
        合并系统提示与提示管理器提示 - 复刻SillyTavern的preparePromptsForChatCompletion详细实现
        Args:
            options: 包含可选设置的字典，包括：
                - scenario: 场景或对话上下文
                - char_personality: 角色性格描述  
                - name2: 消息中使用的第二个名称
                - world_info_before: 主对话前添加的世界信息
                - world_info_after: 主对话后添加的世界信息
                - char_description: 角色描述
                - bias: 对话中添加的偏置
                - extension_prompts: 包含额外提示的对象
                - system_prompt_override: 角色卡片覆盖的主提示
                - jailbreak_prompt_override: 角色卡片覆盖的PHI
                - type: 触发提示的生成类型
        Returns:
            包含准备好并合并的系统和用户定义提示的字典
        """
        scenario = options.get("scenario", "")
        scenario_tokens = options.get("scenario_tokens", "")
        char_personality = options.get("char_personality", "")
        char_personality_tokens = options.get("char_personality_tokens", "")
        name2 = options.get("name2", "")
        world_info_before = options.get("world_info_before", "")
        world_info_before_tokens = options.get("world_info_before_tokens", "")
        world_info_after = options.get("world_info_after", "")
        world_info_after_tokens = options.get("world_info_after_tokens", "")
        char_description = options.get("char_description", "")
        char_description_tokens = options.get("char_description_tokens", "")
        bias = options.get("bias", "")
        extension_prompts = options.get("extension_prompts", {})
        system_prompt_override = options.get("system_prompt_override", "")
        jailbreak_prompt_override = options.get("jailbreak_prompt_override", "")
        generation_type = options.get("type", "")
        # 处理场景和性格文本格式化
        scenario_text = self._format_scenario_text(scenario)
        char_personality_text = self._format_personality_text(char_personality)
        # 创建系统提示条目
        system_prompts = [
            # 有序提示，应该存在标记
            {"role": "system", "content": self._format_world_info(world_info_before), "tokens": world_info_before_tokens, "identifier": "worldInfoBefore", "system_prompt": True},
            {"role": "system", "content": self._format_world_info(world_info_after), "tokens": world_info_after_tokens, "identifier": "worldInfoAfter", "system_prompt": True},
            {"role": "system", "content": char_description, "tokens": char_description_tokens, "identifier": "charDescription", "system_prompt": True},
            {"role": "system", "content": char_personality_text, "tokens": char_personality_tokens, "identifier": "charPersonality", "system_prompt": True},
            {"role": "system", "content": scenario_text, "tokens": scenario_tokens, "identifier": "scenario", "system_prompt": True},
            # 无序提示，无标记
            {"role": "assistant", "content": bias, "identifier": "bias", "system_prompt": True},
        ]
        # 处理扩展提示 - Tavern Extras Summary
        summary = extension_prompts.get("1_memory")
        if summary and summary.get("value"):
            system_prompts.append({
                "role": self._get_prompt_role(summary.get("role")),
                "content": summary["value"],
                "identifier": "summary",
                "position": self._get_prompt_position(summary.get("position")),
                "system_prompt": True
            })
        # 作者注释
        authors_note = extension_prompts.get("2_floating_prompt")
        if authors_note and authors_note.get("value"):
            system_prompts.append({
                "role": self._get_prompt_role(authors_note.get("role")),
                "content": authors_note["value"],
                "identifier": "authorsNote",
                "position": self._get_prompt_position(authors_note.get("position")),
                "system_prompt": True
            })
        # 向量记忆
        vectors_memory = extension_prompts.get("3_vectors")
        if vectors_memory and vectors_memory.get("value"):
            system_prompts.append({
                "role": "system",
                "content": vectors_memory["value"],
                "identifier": "vectorsMemory",
                "position": self._get_prompt_position(vectors_memory.get("position")),
                "system_prompt": True
            })
        vectors_data_bank = extension_prompts.get("4_vectors_data_bank")
        if vectors_data_bank and vectors_data_bank.get("value"):
            system_prompts.append({
                "role": self._get_prompt_role(vectors_data_bank.get("role")),
                "content": vectors_data_bank["value"],
                "identifier": "vectorsDataBank",
                "position": self._get_prompt_position(vectors_data_bank.get("position")),
                "system_prompt": True
            })
        # 智能上下文 (ChromaDB)
        smart_context = extension_prompts.get("chromadb")
        if smart_context and smart_context.get("value"):
            system_prompts.append({
                "role": "system",
                "content": smart_context["value"],
                "identifier": "smartContext",
                "position": self._get_prompt_position(smart_context.get("position")),
                "system_prompt": True
            })
        # 用户描述
        # system_prompts.append({
        #     "role": "system",
        #     "content": f"User is {self.name1}, in ShangHai, China, time is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        #     "identifier": "personaDescription",
        #     "system_prompt": True
        # })
        # 工具调用
        tool_results = TaskManager.get_instance().get_all_tasks_status_prompt_for_llm(self.name1).replace('{', '').replace('}', '').replace('"', '')
        system_prompts.append({
            "role": "system",
            "content": tool_results,
            "identifier": "toolResults",
            "system_prompt": True
        })
        valid_tool_types = self._get_valid_tool_types()
        valid_tools = ""
        for tool_type in valid_tool_types:
            valid_tools += TaskManager.get_instance().get_task_prompt_for_llm_by_type(tool_type)
        system_prompts.append({
            "role": "system",
            "content": valid_tools,
            "identifier": "validTool",
            "system_prompt": True
        })
        tool_calls = TaskManager.get_instance().get_request_tasks_prompt()
        system_prompts.append({
            "role": "system",
            "content": tool_calls,
            "identifier": "toolCalls",
            "system_prompt": True
        })
        tool_dismiss = TaskManager.get_instance().get_dismiss_tasks_prompt()
        system_prompts.append({
            "role": "system",
            "content": tool_dismiss,
            "identifier": "toolDismiss",
            "system_prompt": True
        })
        system_prompts.append({
            "role": "system",
            "content": get_response_format_prompt(),
            "identifier": "responseFormat",
            "system_prompt": True
        })
        # 已知扩展提示列表
        known_extension_prompts = [
            "1_memory",
            "2_floating_prompt", 
            "3_vectors",
            "4_vectors_data_bank",
            "chromadb",
            "PERSONA_DESCRIPTION",
            "DEPTH_PROMPT",
        ]
        # 处理未知扩展提示
        for key, prompt in extension_prompts.items():
            if key in known_extension_prompts:
                continue
            if not prompt.get("value"):
                continue
            if prompt.get("position") not in [ExtensionPromptTypes.BEFORE_PROMPT, ExtensionPromptTypes.IN_PROMPT]:
                continue
            # 检查过滤器
            has_filter = prompt.get("filter") is not None
            if has_filter and callable(prompt["filter"]):
                if not await prompt["filter"]():
                    continue
            system_prompts.append({
                "identifier": re.sub(r'\W', '_', key),
                "position": self._get_prompt_position(prompt.get("position")),
                "role": self._get_prompt_role(prompt.get("role")),
                "content": prompt["value"],
                "extension": True,
                "system_prompt": True
            })
        # 获取用户定义的提示顺序
        prompts = self.get_prompt_collection(generation_type)
        # 合并系统提示与提示管理器提示
        for prompt in system_prompts:
            collection_prompt = prompts["collection"].get(prompt["identifier"])
            # 如果在提示管理器中设置了覆盖，则应用系统提示角色/深度覆盖
            if collection_prompt:
                # In-Chat / 相对位置
                prompt["injection_position"] = getattr(collection_prompt, "injection_position", prompt.get("injection_position"))
                # In-Chat 深度
                prompt["injection_depth"] = getattr(collection_prompt, "injection_depth", prompt.get("injection_depth"))
                # In-Chat 优先级
                prompt["injection_order"] = getattr(collection_prompt, "injection_order", prompt.get("injection_order"))
                # 角色 (system, user, assistant)
                prompt["role"] = getattr(collection_prompt, "role", prompt.get("role"))
            prepared_prompt = PromptModel(**prompt)
            prepared_prompt.content = self.substitute_params(prepared_prompt.content, self.name1, self.name2)
            prompts["collection"][prepared_prompt.identifier] = prepared_prompt
        # 应用角色特定的主提示
        system_prompt = prompts["collection"].get("main")
        # is_system_prompt_disabled = self._is_prompt_disabled_for_active_character("main")
        # 处理系统提示覆盖
        # if system_prompt_override and not is_system_prompt_disabled:
        if system_prompt is None:
            prompts["collection"]["main"] = PromptModel(
                identifier="main",
                role="system", 
                content=system_prompt_override,
                position=0,
                system_prompt=True
            )
        # 应用角色特定的越狱提示
        jailbreak_prompt = prompts["collection"].get("jailbreak")
        is_jailbreak_disabled = self._is_prompt_disabled_for_active_character("jailbreak")
        if jailbreak_prompt_override and not is_jailbreak_disabled:
            if jailbreak_prompt:
                jailbreak_prompt.content = jailbreak_prompt_override
            else:
                prompts["collection"]["jailbreak"] = PromptModel(
                    identifier="jailbreak",
                    role="system",
                    content=jailbreak_prompt_override, 
                    position=999,
                    system_prompt=True
                )
        return prompts
    
    def _format_scenario_text(self, scenario: str) -> str:
        """格式化场景文本"""
        if not scenario:
            return ""
        return self.substitute_params(scenario)
    
    def _format_personality_text(self, personality: str) -> str:
        """格式化性格文本"""
        if not personality:
            return ""
        return self.substitute_params(personality)
    
    def _format_world_info(self, world_info: str) -> str:
        """格式化世界信息"""
        if not world_info:
            return ""
        return self.substitute_params(world_info.strip(), self.name1, self.name2)
    
    def _get_prompt_role(self, role) -> str:
        """获取提示角色"""
        if role == ExtensionPromptRoles.USER:
            return "user"
        elif role == ExtensionPromptRoles.ASSISTANT:
            return "assistant"
        else:
            return "system"
    
    def _get_prompt_position(self, position) -> int:
        """获取提示位置"""
        if position is None:
            return 0
        return int(position)
    
    def _get_default_prompt_order(self) -> List[Dict]:
        """获取默认提示顺序"""
        return [
            {
                'identifier': 'main',
                'enabled': True,
            },
            {
                'identifier': 'worldInfoBefore',
                'enabled': True,
            },
            {
                'identifier': 'personaDescription',
                'enabled': True,
            },
            {
                'identifier': 'charDescription',
                'enabled': True,
            },
            {
                'identifier': 'charPersonality',
                'enabled': True,
            },
            {
                'identifier': 'scenario',
                'enabled': True,
            },
            {
                'identifier': 'enhanceDefinitions',
                'enabled': False,
            },
            {
                'identifier': 'nsfw',
                'enabled': True,
            },
            {
                'identifier': 'worldInfoAfter',
                'enabled': True,
            },
            {
                'identifier': 'dialogueExamples',
                'enabled': True,
            },
            {
                'identifier': 'chatHistory',
                'enabled': True,
            },
            {
                'identifier': 'jailbreak',
                'enabled': True,
            },
        ]

    def get_prompt_collection(self, generation_type: str = "normal") -> Dict:
        """
        返回一个完整的提示列表，其中内容标记已被替换
        
        Args:
            generation_type: 生成类型，例如 'continue' 或 'quiet'
            
        Returns:
            提示集合字典
        """
        generation_type = str(generation_type or 'normal').lower().strip()
        prompt_collection = {"collection": {}, "overriddenPrompts": []}
        prompt_order = self._get_prompt_order_for_character()
        if not prompt_order:
            return prompt_collection
        
        for entry in prompt_order:
            prompt = self._get_prompt_by_id(entry["identifier"])
            # allowed_trigger = entry["enabled"] and self._should_trigger(prompt, generation_type)
            allowed_trigger = entry["enabled"]
            if not prompt:
                continue
            if allowed_trigger:
                prepared_prompt = self._prepare_prompt(prompt)
                prompt_collection["collection"][entry["identifier"]] = prepared_prompt
            elif entry["identifier"] == 'main':
                replacementPrompt = copy.deepcopy(prompt)
                replacementPrompt.content = ""
                prompt_collection["collection"][entry["identifier"]] = replacementPrompt
        
        front_items = {
            "toolResults": PromptModel(identifier="toolResults", enabled=True, role="system", system_prompt=True),
            "validTool": PromptModel(identifier="validTool", enabled=True, role="system", system_prompt=True),
            "toolCalls": PromptModel(identifier="toolCalls", enabled=True, role="system", system_prompt=True),
            "toolDismiss": PromptModel(identifier="toolDismiss", enabled=True, role="system", system_prompt=True),
            "summary": PromptModel(identifier="summary", enabled=True, role="system", system_prompt=True),
            # "authorsNote": PromptModel(identifier="authorsNote", enabled=True, role="system", system_prompt=True),
            # "vectorsMemory": PromptModel(identifier="vectorsMemory", enabled=True, role="system", system_prompt=True),
            # "vectorsDataBank": PromptModel(identifier="vectorsDataBank", enabled=True, role="system", system_prompt=True),
            # "smartContext": PromptModel(identifier="smartContext", enabled=True, role="system", system_prompt=True)
        }
        end_items = {
            "responseFormat": PromptModel(identifier="responseFormat", enabled=True, role="system", system_prompt=True)
        }
        prompt_collection["collection"] = {**front_items, **prompt_collection["collection"], **end_items}
        return prompt_collection
    
    def _get_prompt_order_for_character(self) -> List[Dict]:
        """获取角色的提示顺序"""
        prompt_orders = self.system_preset.prompt_orders
        for prompt_order in prompt_orders:
            if prompt_order.character_id == self.character_id:
                return prompt_order.order
        return self._get_default_prompt_order()  # 如果没有找到匹配的角色，返回空列表
    
    def _get_valid_tool_types(self) -> List[str]:
        return ["search_info"]
    
    def _get_prompt_by_id(self, identifier: str) -> Optional[PromptModel]:
        """根据ID获取提示"""
        for prompt in self.system_preset.prompts:
            if prompt.identifier == identifier:
                return prompt
        return None
    
    def _should_trigger(self, prompt: Optional[PromptModel], generation_type: str) -> bool:
        """检查提示是否应该被触发"""
        if not prompt:
            return False
        
        # 根据生成类型决定是否触发提示
        if generation_type == 'quiet' and prompt.identifier in ['jailbreak', 'nsfw']:
            return False
        
        if generation_type == 'continue' and prompt.identifier == 'main':
            return False
            
        return prompt.enabled

    def _override_prompt(self, prompt_collection: Dict, prompt: PromptModel, index: int):
        """覆盖指定索引的提示"""
        keys = list(prompt_collection["collection"].keys())
        if 0 <= index < len(keys):
            key = keys[index]
            prompt_collection["collection"][key] = prompt
            if key not in prompt_collection["overriddenPrompts"]:
                prompt_collection["overriddenPrompts"].append(key)

    def _is_prompt_disabled_for_active_character(self, prompt_type: str) -> bool:
        """检查提示是否为活动角色禁用"""
        if prompt_type in self.activated_prompts:
            return False
        return True

    def _prepare_prompt(self, prompt: PromptModel) -> PromptModel:
        """准备提示"""
        preparedPrompt = copy.deepcopy(prompt)
        preparedPrompt.content = self.substitute_params(prompt.content, self.name1, self.name2)
        return preparedPrompt

    async def populate_chat_completion(self, prompts: Dict, chat_completion: ChatCompletion, options: Dict):
        """
        填充聊天完成内容 - 复刻SillyTavern的populateChatCompletion逻辑
        
        Args:
            prompts: 准备好的提示词字典
            chat_completion: 聊天完成对象
            options: 包含以下选项的字典：
                - bias: 偏置提示
                - type: 生成类型
                - cycle_prompt: 循环提示
                - messages: 聊天消息
                - message_examples: 消息示例
        """
        bias = options.get("bias", "")
        generation_type = options.get("type", "")
        cycle_prompt = options.get("cycle_prompt", "")
        messages = options.get("messages", [])
        message_examples = options.get("message_examples", [])
        # 辅助函数：向聊天完成中添加提示
        async def add_to_chat_completion(source: str, target: str = None):
            """向聊天完成中添加提示 - 复刻addToChatCompletion逻辑"""
            # 检查提示是否存在于提示集合中
            if not prompts["collection"].get(source):
                return
            # 检查提示是否为当前角色禁用
            if self._is_prompt_disabled_for_active_character(source) and source not in ['main', 'toolResults', 'validTool', 'toolCalls', 'toolDismiss', 'responseFormat', 'summary']:
                chat_completion.log(f"跳过提示 {source}，因为它已被禁用")
                return
            prompt = prompts["collection"].get(source)
            if not prompt:
                return
            # 检查是否为绝对位置提示
            if getattr(prompt, 'injection_position', None) == InjectionPosition.ABSOLUTE:
                chat_completion.log(f"跳过提示 {source}，因为它是绝对位置提示")
                return
            # 获取索引并添加到聊天完成
            index = self._get_prompt_index(prompts, source)
            message_collection = self._create_message_collection(source)
            message = await self._message_from_prompt_async(prompt)
            message_collection["collection"].append(message)
            chat_completion.chat_messages[index] = message_collection
        # 预留3个token的预算（每个回复都以<|start|>assistant<|message|>开始）
        chat_completion.reserve_budget = getattr(chat_completion, 'reserve_budget', lambda x: None)
        chat_completion.reserve_budget(3)
        chat_completion.chat_messages.extend([{}] * len(prompts["collection"]))
        # 角色和世界信息
        await add_to_chat_completion('worldInfoBefore')
        await add_to_chat_completion('main')
        await add_to_chat_completion('worldInfoAfter')
        await add_to_chat_completion('charDescription')
        await add_to_chat_completion('charPersonality')
        await add_to_chat_completion('scenario')
        await add_to_chat_completion('personaDescription')
        await add_to_chat_completion('toolResults')
        await add_to_chat_completion('validTool')
        await add_to_chat_completion('toolCalls')
        await add_to_chat_completion('toolDismiss')
        await add_to_chat_completion('responseFormat')
        # 添加有序的系统和用户提示
        system_prompts = ['nsfw', 'jailbreak']
        user_relative_prompts = []
        absolute_prompts = []
        # 过滤提示集合
        collection = prompts.get("collection", {})
        for prompt in collection.values():
            if (not prompt.system_prompt and 
                prompt.injection_position != InjectionPosition.ABSOLUTE):
                user_relative_prompts.append(prompt.identifier)
            elif prompt.injection_position == InjectionPosition.ABSOLUTE:
                absolute_prompts.append(prompt.identifier)
        # # 添加系统和用户相关提示
        for identifier in system_prompts + user_relative_prompts:
            await add_to_chat_completion(identifier)
        # 聊天：动态提示
        # await add_to_chat_completion('vectorsMemory')
        # await add_to_chat_completion('summary')
        # await add_to_chat_completion('authorsNote')
        # await add_to_chat_completion('smartContext')
        # await add_to_chat_completion('vectorsDataBank')
        # 聊天：对话示例和对话
        # await add_to_chat_completion('impersonate')
        # await add_to_chat_completion('quietPrompt')
        # await add_to_chat_completion('groupNudge')
        # 检查是否有对话示例
        has_dialogue_examples = bool(prompts.get("collection", {}).get('dialogueExamples'))
        if has_dialogue_examples:
            await add_to_chat_completion('dialogueExamples')
        # 控制提示集合（始终位于最后）
        # control_prompts = self._create_message_collection('controlPrompts')
        # 添加增强定义指令
        if collection.get('enhanceDefinitions'):
            await add_to_chat_completion('enhanceDefinitions')

        # 偏置
        if bias and bias.strip():
            await add_to_chat_completion('bias')

        # Tavern Extras - 摘要、作者注释等定位提示
        # positioned_prompts = ['summary', 'authorsNote', 'vectorsMemory', 'vectorsDataBank', 'smartContext']
        # for prompt_name in positioned_prompts:
        #     await self._handle_positioned_prompt(prompts, chat_completion, prompt_name)

        # 其他相对扩展提示
        # for prompt in collection.values():
        #     if (isinstance(prompt, dict) and 
        #         prompt.get("extension") and 
        #         prompt.get("position")):
        #         message = await self._message_from_prompt_async(prompt)
        #         self._insert_message(chat_completion, message, 'main', prompt["position"])
        # 工具数据的预分配token
        # if self._can_perform_tool_calls(generation_type):
        #     tool_tokens = await self._calculate_tool_tokens()
        #     chat_completion.reserve_budget(tool_tokens)
        # input_template += TaskManager.get_instance().get_all_tasks_status_prompt_for_llm(self.user_id).replace('{', '').replace('}', '').replace('"', '')
        # logger.bind(tag="DELAY").info(f"Task status delay: {int((datetime.now().timestamp() - self.process_timer.value) * 1000)}ms")
        # input_template += TaskManager.get_instance().get_task_prompt_for_llm_by_type("search_info")
        # 添加聊天内注入
        messages = await self._populate_injection_prompts(absolute_prompts, messages)
        await self._populate_chat_history(messages, prompts, chat_completion, generation_type, cycle_prompt)
        await self._populate_dialogue_examples(prompts, chat_completion, message_examples)
    
    def _create_message_collection(self, source: str) -> Dict:
        """创建消息集合"""
        return {"identifier": source, "collection": []}
    
    async def _message_from_prompt_async(self, prompt: PromptModel) -> Dict:
        """从提示异步创建消息"""
        return {
            "content": prompt.content.strip(),
            "role": prompt.role,
            "tokens": prompt.tokens
        }
    
    def _get_prompt_index(self, prompts: Dict, identifier: str) -> int:
        """获取提示索引"""
        return list(prompts["collection"].keys()).index(identifier)
    
    async def _get_prompts_for_character(self) -> List[str]:
        """获取角色的提示"""
        return []

    def _is_image_inlining_supported(self) -> bool:
        """检查是否支持图像内联"""
        return False

    async def _add_image_to_message(self, message: Dict, image_data):
        """向消息添加图像"""
        pass

    async def _handle_positioned_prompt(self, prompts: Dict, chat_completion, prompt_name: str):
        """处理定位提示"""
        collection = prompts.get("collection", {})
        if collection.get(prompt_name):
            prompt = collection[prompt_name]
            if prompt.position is not None:
                message = await self._message_from_prompt_async(prompt)
                if message:
                    self._insert_message(chat_completion, message, 'main', prompt["position"])

    def _insert_message(self, chat_completion, message: Dict, target: str, position: int):
        """在指定位置插入消息"""
        if message:
            chat_completion.chat_messages.append(message)

    def _can_perform_tool_calls(self, generation_type: str) -> bool:
        """检查是否可以执行工具调用"""
        return False

    async def _calculate_tool_tokens(self) -> int:
        """计算工具token数量"""
        return 0

    async def _populate_injection_prompts(self, absolute_prompts: List, messages: List) -> List:
        """填充注入提示"""
        return messages

    async def _populate_dialogue_examples(self, prompts: Dict, chat_completion, message_examples: List):
        """填充对话示例"""
        for example in message_examples:
            if isinstance(example, str) and example.strip():
                example_message = {"role": "assistant", "content": example.strip()}
                chat_completion.chat_messages.append(example_message)

    async def _populate_chat_history(self, messages: List[MessageModel], prompts: Dict, chat_completion, generation_type: str, cycle_prompt: str):
        """填充聊天历史"""
        index = self._get_prompt_index(prompts, 'chatHistory')
        message_collection = self._create_message_collection('chatHistory')
        start_system_prompt = f"[Start a new Chat, please reply in {self.language}]"
        start_system_prompt_tokens = count_tokens_openai(start_system_prompt)
        message_collection["collection"].append({
            "content": start_system_prompt,
            "role": "system",
            "tokens": start_system_prompt_tokens
        })
        # 从消息存储获取历史消息
        if not messages:
            messages = MessageStore.get_instance().get_recent_messages(chat_id=self.chat_id, limit=10)
        
        # 使用提供的消息
        for message in messages:
            # cleaned_text = re.sub(r'<env_desc>.*?</env_desc>\s*', '', message.content, flags=re.DOTALL)
            message_collection["collection"].append({
                "content": message.content,
                "role": message.role,
                "tokens": message.tokens
            })
        # end_system_prompt = f"[From now on, the mood attribute of speak tag is limited to: {"|".join(speaker_config["female_1"]["mood_code"])}]"
        # end_system_prompt_tokens = count_tokens_openai(end_system_prompt)
        # message_collection["collection"].append({
        #     "content": end_system_prompt,
        #     "role": "system",
        #     "tokens": end_system_prompt_tokens
        # })
        chat_completion.chat_messages[index] = message_collection
    
    def get_extension_prompt_max_depth(self) -> int:
        """获取扩展提示的最大深度"""
        if not self.extension_prompts:
            return 0
        
        max_depth = 0
        for prompt in self.extension_prompts.values():
            depth = prompt.get("depth", 0)
            if depth > max_depth:
                max_depth = depth
        
        return max_depth
    
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
    
    def get_memory_summary(self, char_id: str, user_id: str) -> str:
        """
        调用远程API获取记忆摘要（同步实现）
        """
        memory_summary = MemoryManager().get_summary_mem(char_id, user_id)
        if memory_summary:
            return memory_summary.summary
        return ""
        # url = "https://sd2hgpu4cck1fc4kbq14g.apigateway-cn-beijing.volceapi.com/v1/search_summary_mem"
        # headers = {
        #     "Content-Type": "application/json"
        # }
        # payload = {
        #     "char_id": char_id,
        #     "user_id": user_id
        # }
        # try:
        #     with httpx.Client(timeout=10) as client:
        #         response = client.post(url, json=payload, headers=headers)
        #         response.raise_for_status()
        #         data = response.json()
        #         return data.get("result", "")
        # except Exception as e:
        #     print(f"获取记忆摘要时出错: {e}")
        #     return ""
    
    async def generate(self, generation_type: GenerationType = GenerationType.NORMAL,
                      options: GenerationOptions = None) -> list[dict]:
        """主要生成函数 - 复刻Generate函数逻辑"""
        if options is None:
            options = GenerationOptions()
        print(f"Generate entered: {generation_type.value}")
        self.generation_started = datetime.now()
        # 获取角色卡片字段
        self.character_fields = self.get_character_card_fields()
        if len(self.character_fields.system) == 0:
            self.character_fields.system = self.base_chat_replace(self.default_sysprompt_content)
        self.remove_depth_prompts()
        self.set_extension_prompt("1_memory", self.get_memory_summary(self.name2, self.name1), 0, 0, False, ExtensionPromptRoles.SYSTEM);
        # 1v1 聊天
        depthPromptText = self.character_fields.char_depth_prompt or ''
        depthPromptDepth = self.character.depth_prompt.depth if self.character.depth_prompt else self.depth_prompt_depth_default
        depthPromptRole = self.get_extension_prompt_role_by_name(self.character.depth_prompt.role if self.character.depth_prompt else self.depth_prompt_role_default)
        self.set_extension_prompt('DEPTH_PROMPT', depthPromptText, ExtensionPromptTypes.IN_CHAT, depthPromptDepth, True, depthPromptRole)
        # 1v1 聊天，第一条消息反应用户/角色设置变化
        coreChat = MessageStore.get_instance().get_recent_messages(chat_id=self.chat_id, limit=10)
        if len(coreChat) == 0 or coreChat[0].role == "user":
            coreChat.insert(0, MessageModel(
                msg_id=str(uuid.uuid4()),
                chat_id=self.chat_id,
                user_id=self.character.name,
                platform="default",
                m_type="text",
                content=self.character.first_mes,
                tokens=self.character.first_mes_tokens,
                role="assistant",
                data={},
                created_at=0
            ))
        # coreChat.append(Message(
        #     msg_id=str(uuid.uuid4()),
        #     chat_id=self.chat_id,
        #     user_id=self.name1,
        #     platform="default",
        #     m_type="text",
        #     content="知道我这里的天气么",
        #     data={
        #         "role": "user"
        #     },
        #     created_at=0
        # ))
        # setFloatingPrompt();
        # // Add persona description to prompt
        # addPersonaDescriptionExtensionPrompt();
        chatForWI = [f"{x.user_id}: {x.content}" if x.user_id else x.content for x in coreChat]
        chatForWI.reverse()
        globalScanData = {
            "personaDescription": self.character_fields.persona,
            "characterDescription": self.character_fields.description,
            "characterPersonality": self.character_fields.personality,
            "characterDepthPrompt": depthPromptText,
            "scenario": self.character_fields.scenario,
            "creatorNotes": self.character_fields.creator_notes,
            "trigger": 'normal',
        }
        activatedWorldInfo = await self.world_info_scanner.get_world_info_prompt(chatForWI, 4000, globalScanData)
        self.world_info_before = activatedWorldInfo.get('worldInfoBefore', '')
        self.world_info_before_tokens = activatedWorldInfo.get('worldInfoBeforeTokens', 0)
        self.world_info_after = activatedWorldInfo.get('worldInfoAfter', '')
        self.world_info_after_tokens = activatedWorldInfo.get('worldInfoAfterTokens', 0)
        self.world_info_string = activatedWorldInfo.get('worldInfoString', '')
        self.world_info_examples = activatedWorldInfo.get('worldInfoExamples', [])
        self.world_info_depth = activatedWorldInfo.get('worldInfoDepth', [])
        self.an_before = activatedWorldInfo.get('anBefore', [])
        self.an_after = activatedWorldInfo.get('anAfter', [])
        params = self.PrepareMessagesParams()
        params.name2 = self.character.name
        params.char_description = self.character_fields.description
        params.char_description_tokens = self.character.description_tokens
        params.char_personality = self.character_fields.personality
        params.char_personality_tokens = self.character.personality_tokens
        params.scenario = self.character_fields.scenario
        params.scenario_tokens = self.character.scenario_tokens
        params.world_info_before = self.world_info_before
        params.world_info_before_tokens = self.world_info_before_tokens
        params.world_info_after = self.world_info_after
        params.world_info_after_tokens = self.world_info_after_tokens
        params.extension_prompts = self.extension_prompts
        params.bias = ''
        params.type = 'normal'
        params.cycle_prompt = ''
        params.system_prompt_override = self.character_fields.system
        params.jailbreak_prompt_override = self.character_fields.jailbreak
        params.messages = coreChat
        params.message_examples = self.world_info_examples
        result = await self.prepare_openai_messages(params)
        return result
    
    def build_messages_array(self, character_fields) -> list:
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
        history = MessageStore.get_instance().get_recent_messages(chat_id=self.chat_id, limit=10)
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
