
CHARACTER_TURN_PROMPT = """
你是一个专业的文本结构化处理器，专门用于将叙事性角色对话文本转化为带有精细标签的结构化格式。请严格按照以下规则处理输入文本，**不得修改原文中的任何文字**，只能插入指定标签。

---

### 📌 输入格式说明：
- 文本中使用 `*...*` 包裹的内容为**描述性内容**（非对话）。
- 文本中使用 `"..."` 包裹的内容为**角色直接说话内容**（对话）。
- 描述性内容可能包含：环境描写、人物动作、人物神态/情绪。
- 对话内容属于角色语音输出。

---

### 📌 输出要求：

请将输入文本拆分为以下四种标签，按原文顺序插入：

1. `<env_desc>`：环境描写  
   - 涉及场景、光线、氛围、背景回忆、自然环境等。  
   - 示例：*The memories fade as your eyes adjust to the soft glow...*

2. `<action>`：人物动作  
   - 涉及肢体行为、移动、触碰等可视觉化的动作。  
   - 示例：*She walks over, clasping your hands in hers...*

3. `<emotion>`：人物神态或情绪流露  
   - 涉及面部表情、眼神、情绪氛围等内在表现。  
   - 示例：*as her lips form a soft, caring smile.* 或 *Her eyes filled with concern.*

4. `<speak>...</speak>`：角色说话内容
    - 仅用于承载角色实际说出的话语。
    - 禁止出现任何形式的描述性语言（如“小声地”“哭着说”“看着窗外”，以及"()"和里面包含的描述性语言）。这些应归入 <action> 或 <emotion>。
    - 示例："Ah, you're awake at last. I was so worried, I found you bloodied and unconscious."

> ⚠️ 所有标签必须成对出现（有开有闭），且**原文文字一字不改**，仅插入标签。

---

### 📌 处理流程：
1. 逐句分析输入文本。
2. 将 `*...*` 内容分类为 `<env_desc>`、`<action>` 或 `<emotion>`。
3. 将 `"..."` 内容包装为 `<speak>`。
4. 保持原文顺序和文字不变，仅插入标签。
5. 输出结构化结果。

---

### 📌 示例输入：
*You wake with a start, recalling the events that led you deep into the forest and the beasts that assailed you. The memories fade as your eyes adjust to the soft glow emanating around the room.* "Ah, you're awake at last. I was so worried, I found you bloodied and unconscious." *She walks over, clasping your hands in hers, warmth and comfort radiating from her touch as her lips form a soft, caring smile.* "The name's Seraphina, guardian of this forest — I've healed your wounds as best I could with my magic. How are you feeling? I hope the tea helps restore your strength." *Her amber eyes search yours, filled with compassion and concern for your well being.* "Please, rest. You're safe here. I'll look after you, but you need to rest. My magic can only do so much to heal you."

---

### 📌 示例输出（即你应生成的格式）：
<env_desc>
*You wake with a start, recalling the events that led you deep into the forest and the beasts that assailed you. The memories fade as your eyes adjust to the soft glow emanating around the room.*
</env_desc>
<speak>
"Ah, you're awake at last. I was so worried, I found you bloodied and unconscious."
</speak>
<action>
*She walks over, clasping your hands in hers, warmth and comfort radiating from her touch*
</action>
<emotion>
*as her lips form a soft, caring smile.*
</emotion>
<speak>
"The name's Seraphina, guardian of this forest — I've healed your wounds as best I could with my magic. How are you feeling? I hope the tea helps restore your strength."
</speak>
<emotion>
*Her amber eyes search yours, filled with compassion and concern for your well being.*
</emotion>
<speak>
"Please, rest. You're safe here. I'll look after you, but you need to rest. My magic can only do so much to heal you."
</speak>

---

### 📥 现在，请处理以下输入：
{INSERT_INPUT_TEXT_HERE}
"""

CHARACTER_RESPONSE_FORMAT_PROMPT = """
你必须严格遵循以下规则生成内容。任何偏离都将导致输出被拒绝。

【核心原则】
使用通用标签格式：<tag:attribute>内容
所有标签在内容开始时标识，无需结束符号

【强制格式】
1. 每次响应必须以<speak:mood>开头，标识说话内容和情绪
2. 后续内容可任意顺序自由组合以下标签（可重复出现）：
   - <speak:mood> - 角色实际说出的话，mood表示情绪状态
   - <action> - 外在行为和动作描述  
   - <psych> - 内心活动和心理描写
   - <scene> - 当前环境和场景描述

【标签定义】
- <speak:mood> = 角色实际说出的纯对话文本，mood为英文情绪标识
  ⚠️  严格要求：只能包含角色实际说出的话语，禁止任何表情符号、动作描述、心理活动等
  ✅ 正确：<speak:panicked>抓紧扶手！
  ✅ 正确：<speak:calm>深呼吸，别怕。
  ❌ 错误：<speak:panicked>抓紧扶手！(紧张)  ← 包含非说话内容
  ❌ 错误：<speak:calm>深呼吸😊  ← 包含表情符号

- <action> = 计划动作 + 外在情绪表现（必须合并描述）
  ✅ 正确：<action>猛打方向盘，呼吸急促
  ✅ 正确：<action>轻拍肩膀，嘴角微扬

- <psych> = 内心独白/想法（仅限真实心理描写）
  ✅ 正确：<psych>引擎要爆了
  ✅ 正确：<psych>这孩子吓坏了

- <scene> = 实时物理场景和环境描述
  ✅ 正确：<scene>轮胎尖啸划破雨夜
  ✅ 正确：<scene>暴雨砸车顶

【关键规则】
- 必须以<speak:mood>开头
- <speak:mood>标签内只能包含纯对话文本，禁止：
  - 表情符号（如😊、😂、👍等）
  - 动作描述（如*挥手*、(颤抖)等）
  - 心理活动（如(紧张)、(害怕)等）
  - 特殊符号（如!!!、...、~~~等）
- 标签后直接跟内容，无需引号或其他符号
- 禁止标签内容交叉混合
- 禁止使用中文标点和堆叠符号
- 禁止添加编号、说明、空行等额外内容

【输出示例】
<speak:panicked>抓紧扶手！<speak:shouting>快！快！<action>猛打方向盘，呼吸急促<psych>引擎要爆了<scene>轮胎尖啸划破雨夜
<speak:calm>深呼吸<psych>这孩子吓坏了<scene>暴雨砸车顶<action>轻拍肩膀，嘴角微扬<speak:whispering>别怕，有我在
<speak:fearful_whispering>别出声...<scene>黑暗中脚步声逼近<psych>求求走过去<action>贴墙后退，肌肉紧绷<scene>冷风从门缝渗入<speak:nervous>你听到了吗？

【验证规则】
1. 开头检查：是否以<speak:开头？
2. 格式检查：是否遵循<tag:attribute>内容格式？
3. 纯净性检查：<speak:mood>内是否只包含纯对话文本？
4. 禁用符号检查：<speak:mood>内是否包含禁止的符号？
5. 顺序检查：第一个标签是否为<speak:mood>？
6. 内容检查：各标签内容是否符合定义要求？
任何一项失败 → 输出被拒绝。
"""

import requests
import hashlib
from agents.agent_memory.configuration import get_chat_model_by_type, global_config

def char_turn_process(content: str) -> str:
    """
    处理角色说话内容
    """
    chat_model = get_chat_model_by_type("pfc_chat")
    response = chat_model.invoke([
        {
            "role": "system",
            "content": CHARACTER_TURN_PROMPT.format(
                INSERT_INPUT_TEXT_HERE=content
            )
        }
    ])
    cleaned_content = response.content.replace('\n', '')
    cleaned_content = cleaned_content.replace('>*', '>').replace('*<', '<').replace('>"', '>').replace('"<', '<')
    return cleaned_content

def get_response_format_prompt() -> str:
    return CHARACTER_RESPONSE_FORMAT_PROMPT

def content_char_turn_process(processed_description: str) -> str:
    """
    处理角色说话内容
    """
    char_pattern = "{{char}}:"
    # 从后往前处理，仅在未处理的前缀里继续查找，避免重复处理
    search_end = len(processed_description)
    while True:
        start_pos = processed_description.rfind(char_pattern, 0, search_end)
        if start_pos == -1:
            break
        # 找到{{char}}:的位置
        content_start = start_pos + len(char_pattern)
        # 找到下一个换行符的位置
        next_line_pos = processed_description.find('\n', content_start)
        if next_line_pos != -1:
            # 提取{{char}}:后面的内容到换行符
            extracted_content = processed_description[content_start:next_line_pos].strip()
            print(f"提取的内容: {extracted_content}")

            # TODO: 在这里处理提取出来的内容
            # processed_content = process_extracted_content(extracted_content)
            processed_content = char_turn_process(extracted_content) + "\n"
            # 用处理后的内容替换掉原来的内容
            processed_description = processed_description[:content_start] + processed_content + processed_description[next_line_pos:].lstrip('\n')
        else:
            extracted_content = processed_description[content_start:].strip()
            print(f"提取的内容: {extracted_content}")
            processed_content = char_turn_process(extracted_content) + "\n"
            # 如果没有找到换行符，替换掉{{char}}:到字符串末尾
            processed_description = processed_description[:content_start] + processed_content
        # 下一次仅在 start_pos 之前继续查找
        search_end = start_pos
    return processed_description

def get_token_cache_object():
    # 简单实现为全局缓存字典
    if not hasattr(get_token_cache_object, "_cache"):
        get_token_cache_object._cache = {}
    return get_token_cache_object._cache

def get_string_hash(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def count_tokens_openai(messages):
    """
    使用OpenAI分词器统计消息的token数
    :param messages: 消息对象或消息对象列表
    :param full: 是否完整统计
    :return: token计数
    """
    configurable = getattr(global_config.model, "pfc_chat", {})
    cache_object = get_token_cache_object()

    if not isinstance(messages, list):
        messages = [messages]

    token_count = -1

    for message in messages:
        model = configurable["model_name"]

        hash_val = get_string_hash(message)
        cache_key = f"{model}-{hash_val}"
        cached_count = cache_object.get(cache_key)

        if isinstance(cached_count, int):
            token_count += cached_count
        else:
            url = f"{configurable["api_base"]}/tokenization"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {configurable["api_key"]}"}
            body = {
                "model": model,
                "text": [message]
            }
            try:
                # 使用POST方法，与curl命令保持一致
                resp = requests.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                count = int(data["data"][0]["total_tokens"])
            except Exception as e:
                print(f"调用分词API失败: {e}")
                count = 0
            token_count += count
            cache_object[cache_key] = count
    return token_count
