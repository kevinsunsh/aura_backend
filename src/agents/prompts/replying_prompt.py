# 回复生成提示词 - 直接回复
REPLYING_GENERATOR_DIRECT_PROMPT = """{persona_text}。现在你在参与一场私聊，请根据以下信息生成一条回复：
当前对话目标：{goals_str}
{knowledge_info_str}
最近的聊天记录：
{chat_history_str}
请根据上述信息，结合聊天记录，回复对方。该回复应该：
1. 以"你"的角度发言（不要自己与自己对话！）
2. 符合你的性格特征和身份细节
3. 可以适当利用相关知识，但不要生硬引用
4. 尽量用较短的句子开场，注意合理断句，实时聊天不要出现太长的单句。
请直接输出回复内容"""

REPLYING_CHECK_PROMPT = """
根据最近的聊天记录，判断是否已经能理解用户意图，能理解返回"true"，不能理解返回"false"
最近的聊天记录：{chat_history_str}
只输出"true"或"false"，不要输出任何其他内容。
"""