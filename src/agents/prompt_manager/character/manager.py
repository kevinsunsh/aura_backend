import json
import uuid
import time
from typing import Optional, List
from sqlalchemy.orm import Session
from .models import CharacterModel, CharacterBookModel, CharacterBookEntryModel
# 导入数据库相关模块
from agents.agent_memory.database.database import Database
from agents.agent_memory.database.connection_config import DatabaseConfigManager
from configuration import get_chat_model_by_type
from langchain_core.messages import SystemMessage

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

class DBManager:
    """
    支持数据库的角色管理器，负责加载和管理角色卡
    支持从文件系统导入到数据库，以及从数据库加载角色
    """
    def __init__(self):
        self.current_character: Optional[CharacterModel] = None
        self.db: Optional[Database] = None
        self.db_session: Optional[Session] = None
    
    def _get_db_session(self) -> Session:
        """获取数据库实例"""
        if self.db is None:
            # 创建数据库连接
            db_conn_string = DatabaseConfigManager.get_config_by_environment().get_connection_string()
            self.db = Database(db_conn_string)
            self.db_session = self.db.get_db()
        return self.db_session
    
    def create_character(self, character_data: dict) -> str:
        """创建角色"""
        character_id = str(uuid.uuid4())
        current_time = int(time.time() * 1000)
        
        # 创建主角色记录
        character = CharacterModel(
            id=character_id,
            name=character_data.get('name', ''),
            description=character_data.get('description', ''),
            personality=character_data.get('personality', ''),
            scenario=character_data.get('scenario', ''),
            first_mes=character_data.get('first_mes', ''),
            mes_example=character_data.get('mes_example', ''),
            avatar=character_data.get('avatar', 'none'),
            create_date=character_data.get('create_date', ''),
            talkativeness=character_data.get('talkativeness', '0.5'),
            fav=character_data.get('fav', False),
            creator_notes=character_data.get('creator_notes', ''),
            system_prompt=character_data.get('system_prompt', ''),
            post_history_instructions=character_data.get('post_history_instructions', ''),
            tags=character_data.get('tags', []),
            creator=character_data.get('creator', ''),
            alternate_greetings=character_data.get('alternate_greetings', []),
            group_only_greetings=character_data.get('group_only_greetings', []),
            character_version=character_data.get('character_version', ''),
            world=character_data.get('world', ''),
            depth_prompt=character_data.get('depth_prompt', {}),
            spec=character_data.get('spec', 'chara_card_v3'),
            spec_version=character_data.get('spec_version', '3.0')
        )
        
        # 如果有data字段，处理详细信息
        data = character_data.get('data', {})
        if data:
            # 覆盖主要字段
            character.description = data.get('description', character.description)
            character.personality = data.get('personality', character.personality)
            character.scenario = data.get('scenario', character.scenario)
            character.first_mes = data.get('first_mes', character.first_mes)
            character.mes_example = data.get('mes_example', character.mes_example)
            character.creator_notes = data.get('creator_notes', character.creator_notes)
            character.system_prompt = data.get('system_prompt', character.system_prompt)
            character.post_history_instructions = data.get('post_history_instructions', character.post_history_instructions)
            character.creator = data.get('creator', character.creator)
            character.character_version = data.get('character_version', character.character_version)
        
        # 先提交角色到数据库
        self._get_db_session().add(character)
        self._get_db_session().commit()
        
        # 然后处理角色书（如果有的话）
        if data and data.get('character_book'):
            self._create_character_book(character_id, data['character_book'], current_time)
            self._get_db_session().commit()
        
        return character_id
    
    def _create_character_book(self, character_id: str, character_book_data: dict, current_time: int):
        """创建角色书"""
        book = CharacterBookModel(
            id=character_id,  # 使用角色ID作为角色书ID
            character_id=character_id,  # 添加外键关联
            name=character_book_data.get('name', '')
        )
        self._get_db_session().add(book)
        self._get_db_session().flush()  # 获取book.id
        
        # 创建角色书条目
        entries = character_book_data.get('entries', [])
        for entry_data in entries:
            self._create_character_book_entry(character_id, entry_data, current_time)
    
    def _create_character_book_entry(self, book_id: str, entry_data: dict, current_time: int):
        """创建角色书条目"""
        # 处理扩展信息
        extensions = entry_data.get('extensions', {})
        book_entry = CharacterBookEntryModel(
            character_book_id=book_id,
            keys=entry_data.get('keys', []),
            secondary_keys=entry_data.get('secondary_keys', []),
            comment=entry_data.get('comment', ''),
            content=entry_data.get('content', ''),
            constant=entry_data.get('constant', False),
            selective=entry_data.get('selective', True),
            insertion_order=entry_data.get('insertion_order', 100),
            enabled=entry_data.get('enabled', True),
            position=entry_data.get('position', 'before_char'),
            use_regex=entry_data.get('use_regex', False),
            # 展开扩展信息到具体字段
            ext_position=extensions.get('position', 0),
            ext_exclude_recursion=extensions.get('exclude_recursion', False),
            ext_display_index=extensions.get('display_index', 0),
            ext_probability=extensions.get('probability', 100),
            ext_use_probability=extensions.get('useProbability', True),
            ext_depth=extensions.get('depth', 4),
            ext_selective_logic=extensions.get('selectiveLogic', 0),
            ext_group=extensions.get('group', ''),
            ext_group_override=extensions.get('group_override', False),
            ext_group_weight=extensions.get('group_weight', 100),
            ext_prevent_recursion=extensions.get('prevent_recursion', False),
            ext_delay_until_recursion=extensions.get('delay_until_recursion', False),
            ext_scan_depth=extensions.get('scan_depth'),
            ext_match_whole_words=extensions.get('match_whole_words'),
            ext_use_group_scoring=extensions.get('use_group_scoring', False),
            ext_case_sensitive=extensions.get('case_sensitive'),
            ext_automation_id=extensions.get('automation_id', ''),
            ext_role=extensions.get('role', 0),
            ext_vectorized=extensions.get('vectorized', False),
            ext_sticky=extensions.get('sticky', 0),
            ext_cooldown=extensions.get('cooldown', 0),
            ext_delay=extensions.get('delay', 0),
            ext_match_persona_description=extensions.get('match_persona_description', False),
            ext_match_character_description=extensions.get('match_character_description', False),
            ext_match_character_personality=extensions.get('match_character_personality', False),
            ext_match_character_depth_prompt=extensions.get('match_character_depth_prompt', False),
            ext_match_scenario=extensions.get('match_scenario', False),
            ext_match_creator_notes=extensions.get('match_creator_notes', False),
            ext_triggers=extensions.get('triggers', [])
        )
        self._get_db_session().add(book_entry)
    
    def get_character_by_name(self, name: str) -> Optional[CharacterModel]:
        """根据名称获取角色"""
        return self._get_db_session().query(CharacterModel).filter(CharacterModel.name == name).first()
    
    def get_character_by_id(self, id: str) -> Optional[CharacterModel]:
        """根据ID获取角色"""
        return self._get_db_session().query(CharacterModel).filter(CharacterModel.id == id).first()
    
    def char_turn_process(self, content: str) -> str:
        """
        处理角色说话内容
        """
        chat_model = get_chat_model_by_type("pfc_chat")
        response = chat_model.invoke([
            SystemMessage(
                content=CHARACTER_TURN_PROMPT.format(
                    INSERT_INPUT_TEXT_HERE=content
                )
            )
        ])
        cleaned_content = response.content.replace('\n', '')
        cleaned_content = cleaned_content.replace('>*', '>').replace('*<', '<').replace('>"', '>').replace('"<', '<')
        return cleaned_content
    
    def load_character_from_file(self, file_path: str) -> Optional[CharacterModel]:
        """
        从文件加载角色卡
        
        Args:
            file_path (str): 角色卡文件路径
            
        Returns:
            Optional[CharacterModel]: 加载的角色模型，如果失败返回None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 使用DAO创建角色到数据库并返回
            if self._get_db_session() is None:
                print("错误: 无法创建数据库连接")
                return None
            
            character = self.get_character_by_name(data['name'])
            if character:
                print(f"从数据库加载角色卡: {character.name}")
                return character
            data["data"]["first_mes"] = self.char_turn_process(data["data"]["first_mes"])
            # 处理description，找出所有的{{char}}:并逐一处理
            description = data["data"]["description"]
            char_pattern = "{{char}}:"
            processed_description = description
            
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
                    processed_content = self.char_turn_process(extracted_content) + "\n"
                    # 用处理后的内容替换掉原来的内容
                    processed_description = processed_description[:content_start] + processed_content + processed_description[next_line_pos:].lstrip('\n')
                else:
                    extracted_content = processed_description[content_start:].strip()
                    print(f"提取的内容: {extracted_content}")
                    processed_content = self.char_turn_process(extracted_content) + "\n"
                    # 如果没有找到换行符，替换掉{{char}}:到字符串末尾
                    processed_description = processed_description[:content_start] + processed_content
                # 下一次仅在 start_pos 之前继续查找
                search_end = start_pos
            
            data["data"]["description"] = processed_description
            character_id = self.create_character(data)
            character = self.get_character_by_id(character_id)
            print(f"成功加载角色卡到数据库: {character.name} (ID: {character_id})")
            return character
        except FileNotFoundError:
            print(f"错误: 角色卡文件未找到 {file_path}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            print(f"错误: 解析角色卡文件失败 {file_path}: {e}")
            return None
