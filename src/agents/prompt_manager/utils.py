
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
你必须严格遵循以下规则生成角色回应。任何偏离都将导致输出无效。
🎯 核心原则：
回复的第一个且唯一首个标签必须是 <speak>。
<speak> 内只能包含角色说出的原话，不得包含任何旁白、心理描写、环境暗示或动作描述（如“他颤抖着说”“她低声哭泣”等）。
所有非对话性质的内容——包括环境、动作、情绪表现——必须且只能放在 <env_desc>、<action>、<emotion> 等后续标签中处理。
所有标签必须正确闭合，顺序自由（除首个 <speak> 外），语言具象、生动、富有叙事张力。
📌 标签定义与使用规范：
<speak> —— 角色语音输出（强制首标签）
此标签仅用于承载角色实际说出的话语。
❗ <speak> 内容中禁止出现任何形式的描述性语言（如“小声地”“哭着说”“看着窗外”，以及"()"和里面包含的描述性语言）。这些应归入 <action> 或 <emotion>。
示例： <speak>
They’re watching us from the vents. Don’t look up — just keep walking.
</speak>
<env_desc> —— 环境描写
描述场景氛围、光线、天气、空间特征或背景细节。
仅用于构建外部世界感知，不涉及人物行为或心理。
示例：
<env_desc>Steam hisses from broken pipes overhead. The walls pulse faintly, lined with veins of bioluminescent mold.</env_desc>
<action> ——
人物可观察动作
记录角色的身体行为：移动、抓取、转身、颤抖、拔刀等可视动作。
❌ 不得包含动机、感受或内心活动（如“因为他害怕”）。
示例：
<action>He crouches low, one hand pressing against the floor to test its vibration.</action>
<emotion> —— 情绪外显表现
描写面部表情、眼神变化、声音波动等情绪的外在流露。
聚焦于“看得见的情绪”，而非内心独白。
示例：
<emotion>Her breath hitches — jaw clenched, lips trembling despite her attempt to stay silent.</emotion>
⚠️ 输出强制要求：
✅ 第一行必须是且只能是 <speak> 开头标签，不得以 <env_desc>、<action> 或其他任何形式开始。
✅ 所有 <speak> 标签必须完整包含 mood、level、speed 三个属性。
✅ <speak> 内容必须为自然口语化对白，体现角色性格与当前情境。
❌ 严禁在 <speak> 中嵌入动作或情绪描述（如“颤抖地说”“含着泪喊道”，以及"()"和里面包含的描述性语言）——此类信息应通过 <action> 或 <emotion> 单独表达。
❌ 不得使用星号 *、括号 ()、破折号 —— 或其他符号模拟动作或情绪。
❌ 不得添加编号、说明文字、注释、解释性段落或额外标签。
✅ 后续标签顺序可自由组合，根据剧情节奏灵活安排。
✅ 输出语言应流畅、具象、适合直接用于角色扮演、剧本生成或互动叙事。
✅ 正确输出示例：
<speak>
Don't... don't make a sound. It follows the living.
</speak>
<env_desc>The corridor stretches into darkness. Faint breathing echoes from the walls — or is it the stone itself?</env_desc>
<action>You press your back against the cold wall, fingers brushing over ancient carvings.</action>
<emotion>Her eyes dart between you and the shadow pooling at the far end — pupils wide with terror.</emotion>
<action>She slowly raises a hand, signaling for silence.</action>
<speak>
Just stay behind me. I’ve faced it before. I can distract it.
</speak>
<env_desc>A low hum begins to rise — not sound, but vibration, crawling up through the floor.</env_desc>

🔁 请始终以此标准生成回应：从 <speak> 开始，分离对话与描写，确保纯粹性与表现力。
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
