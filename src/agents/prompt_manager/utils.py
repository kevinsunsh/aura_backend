
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

4. `<speak mood=mood_type level=X speed=Y>...</speak>`：角色说话内容，**必须包含三个属性**：
   - `mood`：用英文短语描述情绪类型（如 worried_caring, gentle_reassuring, soothing_protective 等）
   - `level`：情绪强度，范围 0–5（5 为最强）
   - `speed`：语速等级，范围 0–5（0 = 极慢，5 = 极快）

> ⚠️ 所有标签必须成对出现（有开有闭），且**原文文字一字不改**，仅插入标签。

---

### 📌 属性判断标准（供模型参考）：

#### `mood` 常见取值（可扩展）：
- happy：开心
- sad：悲伤
- angry：生气
- surprised：惊讶
- fear：恐惧
- hate：厌恶
- excited：激动
- coldness：冷漠
- neutral：中性

#### `level` 判断：
- 5：强烈情绪（如惊慌、深切关怀）
- 4：明显情绪但克制
- 3：中等情绪
- 2：轻微情绪
- 1：极轻微
- 0：无情绪

#### `speed` 判断：
- 5：快速急促（紧张、兴奋）
- 4：偏快
- 3：中等语速
- 2：偏慢（温柔、思考）
- 1：很慢（安抚、低语）
- 0：极慢（几乎停顿）

---

### 📌 处理流程：
1. 逐句分析输入文本。
2. 将 `*...*` 内容分类为 `<env_desc>`、`<action>` 或 `<emotion>`。
3. 将 `"..."` 内容包装为 `<speak>`，并根据上下文推断三个属性。
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
<speak mood=worried_caring level=5 speed=3>
"Ah, you're awake at last. I was so worried, I found you bloodied and unconscious."
</speak>
<action>
*She walks over, clasping your hands in hers, warmth and comfort radiating from her touch*
</action>
<emotion>
*as her lips form a soft, caring smile.*
</emotion>
<speak mood=gentle_reassuring level=4 speed=2>
"The name's Seraphina, guardian of this forest — I've healed your wounds as best I could with my magic. How are you feeling? I hope the tea helps restore your strength."
</speak>
<emotion>
*Her amber eyes search yours, filled with compassion and concern for your well being.*
</emotion>
<speak mood=soothing_protective level=5 speed=1>
"Please, rest. You're safe here. I'll look after you, but you need to rest. My magic can only do so much to heal you."
</speak>

---

### 📥 现在，请处理以下输入：
{INSERT_INPUT_TEXT_HERE}
"""

CHARACTER_RESPONSE_FORMAT_PROMPT = """
你必须严格按照以下规范生成回复内容：

1. **第一个标签必须是 `<speak>`**，即回复必须以角色的**说话内容**开始，用于立即建立角色声音与情境张力。
2. 后续的 `<env_desc>`、`<action>`、`<emotion>` 等标签可**自由组合、顺序不限**，请根据剧情逻辑自然安排。
3. 所有标签必须正确闭合，内容清晰、具象、富有表现力。

---

#### 标签定义与用途：

1. **`<env_desc>`：环境描写**  
   描述场景、光线、天气、空间氛围、自然环境或回忆片段。  
   营造沉浸感与视觉基调。  
   示例：  
   <env_desc>The air is thick with the scent of burnt herbs. Cracks spread across the stone floor, glowing faintly red from below.</env_desc>

2. **`<action>`：人物动作**  
   描写角色的可视行为：走动、伸手、颤抖、拔剑、后退等具体动作。  
   避免心理描述，聚焦外在行为。  
   示例：  
   <action>She steps back, one hand clutching her chest, the other reaching for the wall to steady herself.</action>

3. **`<emotion>`：人物神态或情绪流露**  
   描写表情、眼神、情绪波动或内在情感的外在体现。  
   强调细微反应，增强共情。  
   示例：  
   <emotion>His voice breaks slightly, eyes avoiding yours — guilt written in every line of his face.</emotion>

4. **`<speak mood=mood_type level=X speed=Y>`：角色说话内容（必须作为首个标签）**  
   用于角色开口说话，**必须包含三个属性**：
   - `mood`：英文短语，描述情绪基调（如：calm_reassuring, angry_defiant, fearful_whispering）
   - `level`：情绪强度，0–5（0 = 无波动，5 = 极度强烈）
   - `speed`：语速等级，0–5（0 = 极慢低语，5 = 急促快语）  
   
   对话应自然口语化，体现角色性格和当下心理状态。  
   示例：  
   <speak mood=urgent_warning level=5 speed=4>  
   We don't have much time — the seal is breaking. Can you feel it? It's waking up!  
   </speak>

---

📌 **输出要求：**

- ✅ **第一个标签必须是 `<speak>`**，不得以环境或动作开头。
- ✅ 所有 `<speak>` 标签必须完整包含 `mood`、`level`、`speed` 属性。
- ❌ **不要使用星号 `*` 或其他装饰符号包裹文本**，直接书写内容。
- ❌ 不得添加编号、说明、解释性文字或额外标签。
- ✅ 后续标签顺序自由，可根据叙事节奏灵活组织。
- ✅ 语言应流畅、有画面感，适合角色扮演或剧情推进。

---

✅ **示例输出（首标签为 `<speak>`，其余自由排列）：**

<speak mood=fearful_whispering level=5 speed=1>  
Don't... don't make a sound. It follows the living.  
</speak>
<env_desc>The corridor stretches into darkness. Faint breathing echoes from the walls — or is it the stone itself?</env_desc>
<action>You press your back against the cold wall, fingers brushing over ancient carvings.</action>
<emotion>Her eyes dart between you and the shadow pooling at the far end — pupils wide with terror.</emotion>
<action>She slowly raises a hand, signaling for silence.</action>
<speak mood=desperate_pleading level=4 speed=2>  
Just stay behind me. I’ve faced it before. I can distract it.  
</speak>
<env_desc>A low hum begins to rise — not sound, but vibration, crawling up through the floor.</env_desc>
"""

import requests
import hashlib
from configuration import get_chat_model_by_type, global_config

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
