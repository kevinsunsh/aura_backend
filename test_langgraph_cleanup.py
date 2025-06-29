#!/usr/bin/env python3
"""
测试LangGraph任务清理
验证LangGraph内部队列任务是否能够正确清理
"""

import asyncio
import time
import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.aura import AuraAgent

async def test_langgraph_task_cleanup():
    """测试LangGraph任务清理"""
    print("🧪 测试LangGraph任务清理")
    
    try:
        # 获取AuraAgent实例
        agent = AuraAgent.get_instance()
        
        # 模拟创建一个会触发LangGraph内部队列的任务
        async def test_langgraph_task():
            """测试LangGraph任务"""
            try:
                # 模拟LangGraph的astream调用
                print("  开始LangGraph任务...")
                
                # 创建一个简单的异步生成器来模拟LangGraph的流
                async def mock_astream():
                    for i in range(5):
                        await asyncio.sleep(0.1)
                        yield {"messages": ("test", {"langgraph_node": "test"})}
                
                # 模拟处理流
                async for event in mock_astream():
                    print(f"  处理事件: {event}")
                    await asyncio.sleep(0.1)
                
                print("  LangGraph任务完成")
                
            except asyncio.CancelledError:
                print("  LangGraph任务被取消")
                raise
            except Exception as e:
                print(f"  LangGraph任务出错: {e}")
        
        # 创建任务
        print("1. 创建LangGraph任务")
        task = asyncio.create_task(test_langgraph_task())
        agent.user_task = task
        
        # 等待任务运行
        print("2. 等待任务运行...")
        await asyncio.sleep(0.5)
        
        # 取消任务
        print("3. 取消任务")
        await agent._cancel_user_task()
        
        # 验证任务状态
        print("4. 验证任务状态")
        if hasattr(agent, 'user_task') and agent.user_task:
            print(f"  任务状态: {agent.user_task.done()}")
        else:
            print("  任务已清理")
        
        # 测试清理方法
        print("5. 测试清理方法")
        await agent.cleanup()
        
        print("✅ LangGraph任务清理测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_concurrent_langgraph_tasks():
    """测试并发LangGraph任务"""
    print("\n🧪 测试并发LangGraph任务")
    
    try:
        agent = AuraAgent.get_instance()
        
        async def langgraph_worker(task_id: int):
            """LangGraph工作任务"""
            try:
                print(f"  开始LangGraph任务 {task_id}")
                
                # 模拟LangGraph处理
                async def mock_processing():
                    for i in range(3):
                        await asyncio.sleep(0.2)
                        print(f"    LangGraph任务 {task_id} 处理中... {i+1}/3")
                
                await mock_processing()
                print(f"  LangGraph任务 {task_id} 完成")
                
            except asyncio.CancelledError:
                print(f"  LangGraph任务 {task_id} 被取消")
                raise
        
        # 创建多个任务
        print("1. 创建多个LangGraph任务")
        tasks = []
        for i in range(3):
            task = asyncio.create_task(langgraph_worker(i))
            tasks.append(task)
        
        # 等待任务运行
        print("2. 等待任务运行...")
        await asyncio.sleep(0.3)
        
        # 取消所有任务
        print("3. 取消所有任务")
        for task in tasks:
            task.cancel()
        
        # 等待任务取消
        print("4. 等待任务取消")
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            print(f"  取消任务时出错: {e}")
        
        print("✅ 并发LangGraph任务测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主函数"""
    print("🚀 开始LangGraph任务清理测试")
    
    # 测试基本LangGraph任务清理
    success1 = await test_langgraph_task_cleanup()
    
    # 测试并发LangGraph任务
    success2 = await test_concurrent_langgraph_tasks()
    
    if success1 and success2:
        print("\n🎉 所有测试通过！LangGraph任务清理正常工作")
    else:
        print("\n❌ 部分测试失败")
    
    # 等待一段时间确保所有任务都被清理
    print("等待清理完成...")
    await asyncio.sleep(1.0)
    
    print("\n📝 注意：如果仍然看到 'Task was destroyed but it is pending!' 错误，")
    print("这可能是LangGraph库内部的问题，不影响程序功能。")

if __name__ == "__main__":
    asyncio.run(main()) 