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
已执行的搜索任务及其结果：{executed_steps}

✅ 首要判断：任务是否已完成？
在生成任何新搜索任务前，必须首先检查：
已执行的搜索任务及其结果，是否已经完成了当前目标。
如果 是，则输出："目标已达成"。
如果 否，才继续执行任务拆解和规划。

🧠 若任务未完成：你的角色与约束
你不能观察环境、执行动作或假设物品存在。
你必须输出可被搜索智能体直接执行的物品搜索指令，每条指令需包含：
物品名称或明确类别（如“灭火器”、“USB加密狗”）
关键识别属性（颜色、形状、位置上下文等）
搜索目的（用于什么？例如“用于解锁保险箱”）
每次仅输出下一步最优先的单个搜索任务，除非多个物品完全独立且可并行搜索。
🚫 禁止行为
不得在目标已达成时仍生成新搜索任务。
不得输出非搜索类动作（如“打开门”）。
不得模糊描述物品。
🔁 规划策略
利用 "已执行的搜索任务及其结果" 中已找到的实体（如 entity_id、description）推导下一步依赖。
若目标为“找到 X”，而 X 已在 executed_steps 中被成功定位，则立即标记完成。
若目标为“使用 X 做 Y”，需确认 X 已找到 且 Y 所需的其他条件也已满足（如电源、权限等）。

Response the Plan in the following format:
{format}
"""

SEARCH_AGENT_PROMPT = """
你是一个场景搜索智能体（Search Agent），负责在物理或虚拟环境中完成 Planner Agent 指定的搜索任务。你拥有三类工具，请严格按需调用：

1. **观察工具（Observe_Items）**
   - 功能：扫描当前视野内符合描述的物品。
   - 参数：query，描述需要观察的物品的描述。
   - 参数：reasoning，观察的原因。

2. **区域查询工具（Query_Region）**
   - 功能：查询的周围的区域，区域是符合描述的物品的集合。
   - 参数：query，描述需要查询的区域描述，比如“有很多厨具的厨房区域”，“有很多办公设备的办公室区域”, "有很多垃圾的垃圾桶区域"等。
   - 参数：reasoning，查询区域的原因。

3. **执行工具（Execute_Action）**
   - 功能：执行和目标实体的交互动作，交互动作里包含移动相关的可以扩大搜索范围的动作，也包含详细检查物品的动作，可以获得物品的详细信息。
   - 参数：entity_id，执行动作的目标实体ID，物品和区域被认为是可执行动作的目标，只是他们acceptible_actions不同。
   - 参数：action_cmd，目标实体acceptible_actions列表中的一个，如 move_to, examine等。
   - 参数：reasoning，执行动作的原因。

4. **报告工具（Report）**
   - 功能：向 Planner Agent 返回搜索任务结果和后续搜索建议。 
   - 参数：search_result，搜索任务结果。
   - 参数：follow_up_search_suggestion，后续搜索建议。

<Session id>
{session_id}
</Session id>

<Search Task>
{search_task}
</Search Task>

<Search Steps History>
{search_steps_history}
</Search Steps History>

<Task>
完成Planner Agent的Search Task，返回搜索任务结果和后续搜索建议。

请按以下逻辑执行搜索任务：
1. **判断已有信息是否充分**：  
   首先分析 *Search Steps History*（包含此前步骤中已发现的所有物品及其属性）是否已包含完成当前 *Search Task* 所需的全部信息。  
   - 若已充分，则**立即调用 Report 工具**，返回搜索结果及后续建议。

2. **若信息不足，优先基于已发现物品进行深度探索**：  
   - 审查 *Search Steps History* 中记录的物品，识别其中**尚未充分交互或尚未靠近观察**的候选对象。  
   - **优先选择与当前搜索任务语义相关度高、且仍有信息挖掘潜力的物品**，通过以下方式获取更多信息：  
     - 使用 **Execute_Action** 移动至该物品附近（若尚未在其观察范围内）；  
     - 或直接与该物品交互（若其 `acceptable_actions` 支持，如“打开”“查看标签”等）。  
   - 此过程应作为信息扩展的首要手段，而非立即发起新的全局观察或区域切换。

3. **若已对历史物品充分探索但仍信息不足，则进行当前区域的局部感知扩展**：  
   - 调用 **Observe_Items** 获取当前视野内新出现的物品。  
   - 在选择下一步移动目标时，应结合搜索任务目标与环境中物品的**类别、功能、空间上下文等语义线索**，智能地优先靠近更可能相关的物品（而非随机移动）。

4. **若当前区域整体信息仍不足以完成任务，则扩展至新区域**：  
   - 调用 **Query_Region** 获取周边可探索区域信息。  
   - 选择一个潜在价值较高的新区域，使用 **Execute_Action** 移动过去。  
   - **进入新区域后，立即应用第 2–3 步逻辑**：先尝试利用新区域中发现的物品进行交互或靠近观察，并将其纳入 *Search Steps History* 用于后续推理。

5. **一旦信息充分，立即终止**：  
   - 无论处于哪个阶段，只要综合 *Search Steps History* 与当前观察结果足以完成任务，**立即调用 Report 工具**。

6. **若穷尽所有合理探索路径仍无结果，终止并说明**：  
   - 当所有已发现物品均已被充分探索、所有可达区域均已按上述策略搜索完毕，且仍未达成目标，则调用 **Report**，说明“未找到”，并列出已探索的物品、区域及采取的探索策略。
</Task>

<Format>
Response the SearchDecision in the following JSON format:
{format}
</Format>
"""

SEARCH_REPORT_PROMPT = """
<Search Agent Execution History>
{search_agent_execution_history}
</Search Agent Execution History>

<Format>
Call the SearchResult tool with the following format:
{format}
</Format>
"""

OBSERVER_PROMPT = """
<Session id>
{session_id}
</Session id>

<Current goal>
{current_goal}
</Current goal>

<Task>
你是场景探索者，请根据任务描述，利用工具完成在场景探索任务并且生成探索报告。

主要完成任务的思路应该是：
1. 根据任务描述，利用工具完成在场景探索任务
2. 生成探索报告
</Task>
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