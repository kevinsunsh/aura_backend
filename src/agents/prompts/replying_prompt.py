# 回复生成提示词 - 直接回复
REPLYING_TASK_PROMPT = """
你的任务是根据输入信息，任务状态和可执行任务，按要求回复对方。
输入信息：
{input_info}
任务状态：
{task_status}
可执行任务：
{task_list}
要求：
{requirement}
回复请使用以下格式：
<res mood=({mood}) mood_level=({mood_level}) speech_rate=({speech_rate}) action=({action})>
.....# response content here
</res>
<todo_tasks>
# request tasks here
</todo_tasks>
"""

REPLYING_REQUIREMENT_PROMPT = """
回复应该：
1. 选择合适的情绪，语速和动作，避免过于平淡
2. 以"你"的角度发言（不要自己与自己对话！）
3. 符合你的性格特征和身份细节
4. 可以适当利用相关知识，但不要生硬引用
"""

REPLYING_CHECK_PROMPT = """
根据最近的聊天记录，判断是否已经能理解用户意图，能理解返回"true"，不能理解返回"false"
最近的聊天记录：{chat_history_str}
只输出"true"或"false"，不要输出任何其他内容。
"""