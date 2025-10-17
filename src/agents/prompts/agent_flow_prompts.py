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
<Character description>
{character_description}
</Character description>

<Current goal>
{current_goal}
</Current goal>

<Execution history>
{action_history}
</Execution history>

<Related Items>
{related_items}
</Related Items>

<Task>
请根据角色描述，当前目标，行动历史，相关物品，制定接下来可以采取的动作。动作应该：
1. 基于角色描述，当前目标，行动历史，相关物品，制定接下来可以采取的动作
2. 符合角色的长期目标
3. 需要重点关注的是历史记录里已采取的行动，注意不要进入逻辑死循环
4. 注意related_items里的物品都是目前已知的目标，但是还有很多未知目标，所以需要通过走到有关联的已知目标去发现未知目标，比如如果目标是找凳子，但是related_items里没有凳子，或者是没有更多的凳子了，就要找到可能有凳子的地方去发现凳子。
5. Finished action表示已经执行了动作，并且已经到达了目标，所以不需要再采取相同行动
</Task>

<Rules>
补充规则：
1. <Related Items>里任何常识上可以坐的物品，都可以接受"sit"动作，除此之外只能接受可接受动作列表里的动作
2. move_to动作是指移动自己到目标物品所在位置
3. 额外可以选择"turn"动作,在人物需要观察周围环境时使用，选择"turn"动作时, action_target_id为["left", "right", "back"], action_target_description为"None"
4. 额外可以选择"move_forward"动作,在人物需要移动自己向前时使用，选择"move_forward"动作时, action_target_id为"self", action_target_description为"None"
</Rules>

<Format>
Call the NextAction tool with the following format:
{format}
</Format>
"""

FEEDBACK_ANALYSIS_PROMPT = """
<Character description>
{character_description}
</Character description>

<Current goal>
{current_goal}
</Current goal>

<Execution history>
{action_history}
</Execution history>

<Task>
请根据角色描述，当前目标，动作历史，制定接下来可以采取的行动。
1. Finished action表示已经执行了动作，并且已经到达了目标，所以不需要再采取相同行动
</Task>

<Format>
Call the FeedbackAnalysis tool with the following format:
{format}
</Format>
"""

EXAMINE_PROMPT = """
框出所有符合{target_description}描述的位置，输出对应的 bounding box 的坐标
"""
