"""
Agent 流程使用示例
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any

from agents.graphs.agent_flow_graph import (
    agent_flow_graph,
    create_initial_state,
    run_agent_flow,
    update_execution_result
)


async def example_usage():
    """使用示例"""
    
    # 模拟聊天记录
    chat_history = [
        {
            "role": "user",
            "content": "我想了解一下今天的天气情况",
            "timestamp": "2024-01-01 10:00:00"
        },
        {
            "role": "assistant", 
            "content": "好的，我来帮您查询今天的天气信息",
            "timestamp": "2024-01-01 10:00:01"
        },
        {
            "role": "user",
            "content": "然后帮我制定一个适合的出行计划",
            "timestamp": "2024-01-01 10:00:30"
        }
    ]
    
    # 之前的目标
    previous_goals = [
        {
            "goal_id": "weather_query",
            "goal_type": "information_gathering",
            "priority": "high",
            "description": "查询今天天气情况",
            "expected_outcome": "获得准确的天气信息",
            "dependencies": [],
            "time_limit": "5",
            "success_criteria": "获得完整的天气数据"
        }
    ]
    
    # 上下文信息
    context_info = {
        "user_location": "北京",
        "available_resources": {
            "weather_api": True,
            "calendar_api": True,
            "map_api": True
        },
        "user_preferences": {
            "outdoor_activities": True,
            "temperature_preference": "comfortable"
        }
    }
    
    print("开始运行 Agent 流程...")
    
    try:
        # 运行 Agent 流程
        result = await run_agent_flow(
            user_id="user_123",
            chat_id="chat_456",
            chat_history=chat_history,
            previous_goals=previous_goals,
            context_info=context_info
        )
        
        print("Agent 流程完成!")
        print(f"最终状态: {result}")
        
    except Exception as e:
        print(f"运行 Agent 流程时出错: {e}")


async def example_with_interruption():
    """带中断的示例"""
    
    # 创建初始状态
    initial_state = await create_initial_state(
        user_id="user_123",
        chat_id="chat_456",
        chat_history=[
            {
                "role": "user",
                "content": "帮我发送一条消息给朋友",
                "timestamp": datetime.now().isoformat()
            }
        ]
    )
    
    print("开始运行带中断的 Agent 流程...")
    
    try:
        # 运行图直到中断
        config = {"configurable": {"thread_id": "thread_123"}}
        result = await agent_flow_graph.ainvoke(initial_state, config)
        
        print(f"流程中断，当前状态: {result}")
        
        # 模拟客户端返回执行结果
        execution_result = {
            "action_id": "send_message",
            "execution_time": datetime.now().isoformat(),
            "status": "success",
            "result_data": {
                "message_id": "msg_789",
                "delivery_status": "delivered",
                "recipient_response": "好的，收到了"
            }
        }
        
        # 更新执行结果并继续
        updated_state = await update_execution_result(
            session_id=result.get("session_id", ""),
            execution_result=execution_result,
            execution_status="success"
        )
        
        # 继续运行
        final_result = await agent_flow_graph.ainvoke(updated_state, config)
        
        print(f"流程完成，最终状态: {final_result}")
        
    except Exception as e:
        print(f"运行带中断的 Agent 流程时出错: {e}")


def print_state_summary(state: Dict[str, Any]):
    """打印状态摘要"""
    print("\n=== Agent 状态摘要 ===")
    print(f"用户ID: {state.get('user_id', 'N/A')}")
    print(f"聊天ID: {state.get('chat_id', 'N/A')}")
    print(f"当前步骤: {state.get('current_step', 'N/A')}")
    print(f"迭代次数: {state.get('iteration_count', 0)}")
    print(f"是否继续: {state.get('should_continue', False)}")
    
    current_goals = state.get('current_goals', [])
    if current_goals:
        print(f"\n当前目标 ({len(current_goals)} 个):")
        for goal in current_goals:
            print(f"  - {goal.get('goal_id', 'N/A')}: {goal.get('description', 'N/A')}")
    
    action_plan = state.get('action_plan', [])
    if action_plan:
        print(f"\n行动计划 ({len(action_plan)} 个):")
        for action in action_plan:
            print(f"  - {action.get('action_id', 'N/A')}: {action.get('description', 'N/A')}")
    
    execution_result = state.get('execution_result', {})
    if execution_result:
        print(f"\n执行结果:")
        print(f"  - 状态: {execution_result.get('status', 'N/A')}")
        print(f"  - 消息: {execution_result.get('message', 'N/A')}")
    
    validation_result = state.get('validation_result', {})
    if validation_result:
        print(f"\n验证结果:")
        print(f"  - 是否成功: {validation_result.get('is_successful', False)}")
        print(f"  - 置信度: {validation_result.get('confidence_score', 0)}")


async def main():
    """主函数"""
    print("=== Agent 流程示例 ===\n")
    
    # 运行基本示例
    await example_usage()
    
    print("\n" + "="*50 + "\n")
    
    # 运行带中断的示例
    await example_with_interruption()


if __name__ == "__main__":
    asyncio.run(main())
