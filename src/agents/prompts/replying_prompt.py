# 回复生成提示词 - 直接回复
REPLYING_TASK_PROMPT = """
你的任务是根据输入信息，任务状态和可执行任务，按要求回复对方。
输入信息：
{input_info}
要求：
{requirement}
请严格按照以下xml格式回复：
<response>
<mood>
{mood}
</mood>
<mood_level>
{mood_level}
</mood_level>
<speech_rate>
{speech_rate}
</speech_rate>
<action>
{action}
</action>
<content>
# response content here in string
</content>
<request_tasks>
{request_tasks_prompt}
</request_tasks>
<dismiss_tasks>
{dismiss_tasks_prompt}
</dismiss_tasks>
</response>
"""

REPLYING_REQUIREMENT_PROMPT = """
回复应该：
1. 选择合适的情绪，语速和动作，避免过于平淡
2. 以"你"的角度发言（不要自己与自己对话！）
3. 符合你的性格特征和身份细节
4. 可以适当利用相关知识，但不要生硬引用

任务使用要求：
1. 同样的任务同样参数不要重复request
2. request任务的事不用告诉用户
3. 通过聊天向用户收集足够的参数
4. 对于running状态的任务，请用户耐心等待结果
5. 对于finished状态的任务，找机会告诉用户结果即可
6. 告诉过用户结果的任务或者觉得用户不需要结果的任务记得dismiss
"""

REPLYING_CHECK_PROMPT = """
根据最近的聊天记录，判断是否已经能理解用户意图，能理解返回"true"，不能理解返回"false"
最近的聊天记录：{chat_history_str}
只输出"true"或"false"，不要输出任何其他内容。
"""