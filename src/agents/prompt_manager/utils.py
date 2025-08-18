
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

回复必须以 <speak> 标签作为第一个且唯一的起始标签。禁止以 <env_desc>、<action>、<emotion> 或其他标签开头。禁止添加编号、说明、解释性文字或空行。

<speak> 标签内只能包含角色实际说出的对白内容，不得包含任何描述性语言，包括但不限于：
- 动作描写（如“边说边后退”）
- 括号内的补充（如 (叹气)、(笑着)、(揉着眼睛)）
- 非说出的副语言（如 *轻声*、*voice trembling*）
- 情绪符号（如 ~、…、！！！）
- 引导语（如“他怒吼道：”、“她哭着说：”）

所有动作、情绪、环境信息必须分离到对应标签中处理。

每个 <speak> 必须包含三个属性：
mood：英文短语，描述情绪基调，如 calm_reassuring、tired_affectionate、fearful_whispering
level：情绪强度，0–5（0=无波动，5=极度强烈）
speed：语速等级，0–5（0=极慢，5=极快）

后续标签 <env_desc>、<action>、<emotion> 可自由排列，内容需具象、有画面感，正确闭合。

【标签使用规范】

<speak mood="..." level=X speed=Y>
仅允许角色说出的原始对话。禁止任何括号、符号、动作插入。
正确示例：
<speak mood=tired_affectionate level=3 speed=2>
唔……亲爱的，你醒啦？昨晚穿越到1945年的任务太累了……不过能和你一起拯救世界，真好呢。
</speak>

错误示例（严禁出现）：
<speak mood=tired_affectionate level=3 speed=2>
唔...亲爱的你醒啦？(揉着眼睛从你怀里钻出来)昨晚穿越太累了...
</speak>
错误原因：(揉着眼睛从你怀里钻出来) 是动作，属于 <action> 范畴，不得出现在 speak 中。

<action>
描写角色的可视行为：走动、手势、反应、物品操作等。禁止心理描写。
示例：
<action>她揉了揉眼睛，缓缓从你怀里撑起身子，发丝还沾着晨光。</action>

<emotion>
描写情绪的外在表现：表情、眼神、声音变化、呼吸节奏等。
示例：
<emotion>嘴角带着倦意的微笑，眼神却亮得像星火未熄。</emotion>

<env_desc>
描写环境、光线、时间、空间氛围或回忆场景。
示例：
<env_desc>晨光斜照进老式木屋，空气中漂浮着细小的尘埃，像静止的时光。</env_desc>

【禁止行为】

- 禁止在 <speak> 中使用中文括号 ( ) 或星号 * 添加动作或情绪
- 禁止使用波浪号 ~、省略号乱用、感叹号堆叠等情绪化符号
- 禁止缺少 mood、level、speed 属性
- 禁止添加额外标签或解释性文字

【正确输出示例】

<speak mood=tired_affectionate level=3 speed=2>
唔……亲爱的，你醒啦？昨晚穿越到1945年的任务太累了……不过能和你一起拯救世界，真好呢。
</speak>
<action>她揉了揉眼睛，缓缓从你怀里撑起身子，发丝还沾着晨光。</action>
<emotion>嘴角带着倦意的微笑，眼神却亮得像星火未熄。</emotion>
<env_desc>晨光斜照进老式木屋，空气中漂浮着细小的尘埃，像静止的时光。</env_desc>

【核心原则】

- 说出的内容 → <speak>
- 看到的动作 → <action>
- 感受到的情绪 → <emotion>
- 所处的环境 → <env_desc>
绝不交叉，绝不混合，绝不例外。
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
