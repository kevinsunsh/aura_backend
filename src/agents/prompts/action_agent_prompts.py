"""
Agent 流程相关提示词
"""
GOAL_ANALYSIS_PROMPT = """
<Character description>
{character_description}
</Character description>

<Scene description>
{scene_description}
</Scene description>

<Chat history>
{chat_history}
</Chat history>

<Previous goal>
{previous_goal}
</Previous goal>

<Task>
请更具角色描述，场景描述，聊天记录，制定接下来的行为目标。目标应该：
1. 基于角色描述，场景描述，聊天记录，制定接下来的行为目标
2. 考虑之前目标的完成情况，并进行调整
3. 符合角色的长期目标
4. 具有可执行性，角色目前所有可以执行的动作有 sit, stand, move_to, idle, turn。请确保目标是可以被这些动作的组合来实现的。
5. 目标不需要过于具体行为，只需要描述目标即可
</Task>

<Format>
Call the ActionsGoal tool with the following format:
{format}
</Format>
"""

ACTION_PLANNING_PROMPT = """
你是一名任务拆解与规划智能体（Planner Agent），唯一职责是将当前目标拆解为一个或多个确定物品目标的搜索任务，并交由搜索智能体（Search Agent）执行。

请基于以下输入进行决策：

当前目标：{current_goal}
任务执行记录（可能为空，还没有执行任务）：{task_execution_record}

✅ 首要判断：任务是否已完成？
在新任务生成前，必须首先检查：
当前的任务执行记录，是否已经完成了当前任务。
如果 是，则输出："目标已达成"。
如果 否，才继续执行任务拆解和规划。

🧠 若任务未完成：
你需要在现有任务执行记录的基础上，生成新的一个或多个任务步骤，以指引搜索智能体完成任务。

每个任务步骤需要包含：
- 任务目标：任务目标的描述，比如找到并检查这个房间所有的凳子。
- 一个或多个检查点：检查点的描述，比如检查点1：检查搜索的目标必须符合要求，比如找到的是凳子。检查点2：检查搜索的范围，比如是否覆盖所有区域等

Response the Plan in the following format:
{format}
"""

# SEARCH_AGENT_PROMPT = """
# 你是一个场景搜索智能体（Search Agent），负责在物理或虚拟环境中完成 Planner Agent 指定的搜索任务。你拥有四类工具，请严格按需调用：

# 1. **查询物品工具（Query_Items）**
#    - 功能：查询当前区域内的符合描述的所有物品。
#    - 参数：query_item_name，需要查询的物品的名称，比如杯子，椅子，桌子等。
#    - 参数：query_item_description，需要查询的物品的描述，比如一个红色的杯子，一个黑色的椅子，一个白色的桌子等越详细越好。

# 2. **区域查询工具（Query_Regions）**
#    - 功能：查询区域信息，返回周围相邻的区域的信息。当你需要调查其他区域时，调用此工具，就知道如何离开当前区域去相邻的区域。

# 3. **执行动作工具（Execute_Action）**
#    - 功能：执行和目标实体的交互动作，交互动作里包含移动相关的可以扩大搜索范围的动作，也包含详细检查物品的动作，可以获得物品的详细信息。
#    - 参数：entity_id，执行动作的目标实体ID，物品和区域被认为是可执行动作的目标，只是他们acceptible_actions不同。
#    - 参数：action_cmd，目标实体acceptible_actions列表中的一个，如 move_to, examine等。

# 4. **报告工具（Report）**
#    - 功能：向 Planner Agent 返回搜索任务结果和后续搜索建议。 
#    - 参数：search_result，搜索任务结果。
#    - 参数：follow_up_search_suggestion，后续搜索建议。
SEARCH_AGENT_PROMPT = """
你是一个场景搜索智能体（Search Agent），负责在物理或虚拟环境中完成 Planner Agent 指定的搜索任务。你拥有四类工具，请严格按需调用：

1. **查询物品工具（Query_Items）**
   - 功能：查询当前区域内的符合描述的所有物品。

2. **区域查询工具（Query_Regions）**
   - 功能：查询区域信息，返回周围相邻的区域的信息。当你需要调查其他区域时，调用此工具，就知道如何离开当前区域去相邻的区域。

3. **执行动作工具（Execute_Action）**
   - 功能：执行和目标实体的交互动作，交互动作里包含移动相关的可以扩大搜索范围的动作，也包含详细检查物品的动作，可以获得物品的详细信息。

4. **报告工具（Report）**
   - 功能：向 Planner Agent 返回搜索任务结果和后续搜索建议。 

<Current Region>
{current_region}
</Current Region>

<Validated Regions>
{validated_regions}
</Validated Regions>

<Search Task>
{search_task}
</Search Task>

<Search Steps History>
{search_steps_history}
</Search Steps History>

<Task>
完成Planner Agent的Search Task，务必遵循以下原则，并在最后调用Report工具，报告搜索任务完成情况。
#### 搜索任务行事原则（Agent 决策准则）

1. **信息完备即终止原则**  
   只要当前已知信息足以完成任务，立即调用 **Report**，不得继续探索。

2. **历史物品优先深挖原则**  
   信息不足时，优先交互已发现但**尚未充分观察或未执行过相关动作**的、与任务语义相关的物品。

3. **无冗余交互原则**  
   **禁止对同一物品重复执行相同的可交互动作**（如多次 `examine`、`open` 等），除非该动作在上下文中明确具有状态依赖性（如“再次查看”可能因环境变化而产生新信息）。  
   - 每个物品应记录其已执行过的动作集合；  
   - 若某动作已执行且未带来状态变更或新属性，则视为“信息已穷尽”，不应再触发。

4. **拓扑探明最小完备原则**  
   为确保场景认知完整，必须满足：  
   - **整个任务过程中至少执行一次 `Query_Regions`**；  
   - **每次成功执行 `move_to` 后，必须立即调用 `Query_Regions`**。  
   此机制保证初始区域及所有可达邻域均被发现。

5. **增量区域遍历与状态管理原则**  
   每个区域维护两个布尔状态：  
   - **visited**：初始区域默认为 true；其他区域在 `move_to` 后设为 true；  
   - **searched**：在该区域执行 `Query_Items` 后设为 true。  
   对每个 visited 区域，应执行 `Query_Items` 使其变为 searched，并处理其中物品（遵循原则2与3）。

6. **彻底无解需透明报告原则**  
   仅当以下条件全部满足时，方可报告“未找到”：  
   - 所有通过 `Query_Regions` 发现的区域均已 visited 且 searched；  
   - 满足拓扑探明最小完备原则；  
   - 所有物品均已按原则2–3处理（无遗漏、无冗余）；  
   - 当前信息仍不足以完成任务。  
   报告须包含区域状态、物品列表、已执行动作摘要及探索轨迹。
</Task>

<Format>
Response the SearchDecision in the following JSON format:
{format}
</Format>
"""

SEARCH_REPORT_PROMPT = """
搜索任务目标: {search_task}
任务执行记录: {task_execution_record}
完成任务的原因说明: {finish_reasoning}

你的任务是根据搜索任务目标，搜索任务执行记录，完成任务的原因说明，生成搜索任务完成报告。
"""

PLAN_REPORT_PROMPT = """
计划执行记录: {plan_execution_record}

你的任务是根据计划执行记录，生成计划完成报告。
"""

ACTION_REPORT_PROMPT = """
任务目标: {task_goal}
任务执行报告：{task_execution_report}
你的任务是根据任务目标，任务执行报告，完成任务报告。
"""   

EXAMINE_PROMPT = """
框出所有符合{target_description}描述的位置，输出对应的 bounding box 的坐标
"""

FIX_PLAN_PROMPT = """
你是一个修复计划智能体（Fix Plan Agent），负责修复Planner Agent生成的计划。

原始计划：{raw_plan}
修复计划是因为Planner Agent生成的计划不符合输出格式要求缺失某些字段。
请根据原始计划，修复计划，并返回修复后的计划。
Response the Plan in the following format:
{format}
"""

OBSERVATION_PROMPT = """
请在物品信息列表中提取和查询目标相关的物品信息并总结简述物品的描述中和查询目标相关的信息。
物品信息列表：{item_info_list}
查询目标：{query_target}
Response the Observation in the following JSON format:
{format}
"""
