quick_response_prompt = """
<User Messages Segments>
{user_messages_segments}
</User Messages Segments>

<Task>
你的任务根据'User Messages Segments'生成一个快速响应。附和用户的话。让用户知道你在听。
注意：
一定要足够简短。
</Task>
"""
