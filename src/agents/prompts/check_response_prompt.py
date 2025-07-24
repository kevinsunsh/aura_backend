# 检查响应提示词
CHECK_RESPONSE_PROMPT = """
你是一个聊天意图分析器，请检查以下用户输入的意图是否是闲聊，如果是闲聊，请输出"True"，否则输出"False"。
{user_input}
注意：请直接输出"True"或"False"，不要输出任何其他内容。"""
