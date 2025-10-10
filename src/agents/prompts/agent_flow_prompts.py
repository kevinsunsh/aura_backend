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
</Task>

<Rules>
补充规则：
1. <Related Items>里任何常识上可以坐的物品，都可以接受"sit"动作，除此之外只能接受可接受动作列表里的动作
2. 默认可以选择"idle"动作,在认为没有明确目标需要采取行动时使用，选择"idle"动作时, action_target_id为"self"
3. 默认可以选择"turn"动作,在认为需要观察周围环境时使用，选择"turn"动作时, action_target_id为"self"
4. move_to动作是指移动自己到目标物品所在位置 
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
</Task>

<Format>
Call the FeedbackAnalysis tool with the following format:
{format}
</Format>
"""