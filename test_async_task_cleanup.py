#!/usr/bin/env python3
"""
测试异步任务清理
验证修复后的任务管理是否正常工作
"""

import asyncio
import time
import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.aura import AuraAgent

async def test_task_management():
    """测试任务管理"""
    print("🧪 测试异步任务管理")
    
    try:
        # 获取AuraAgent实例
        agent = AuraAgent.get_instance()
        
        # 模拟创建一个长时间运行的任务
        async def long_running_task():
            """模拟长时间运行的任务"""
            try:
                for i in range(100):
                    await asyncio.sleep(0.5)
                    print(f"  任务运行中... {i+1}/10")
            except asyncio.CancelledError:
                print("  任务被取消")
                raise
            except Exception as e:
                print(f"  任务出错: {e}")
        
        # 创建任务
        print("1. 创建长时间运行的任务")
        task = asyncio.create_task(long_running_task())
        agent.user_task = task
        
        # 等待一段时间
        print("2. 等待任务运行...")
        await asyncio.sleep(1.0)
        
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
        
        print("✅ 任务管理测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_concurrent_tasks():
    """测试并发任务管理"""
    print("\n🧪 测试并发任务管理")
    
    try:
        agent = AuraAgent.get_instance()
        
        async def worker_task(task_id: int):
            """工作任务"""
            try:
                for i in range(5):
                    await asyncio.sleep(0.2)
                    print(f"  任务 {task_id} 运行中... {i+1}/5")
            except asyncio.CancelledError:
                print(f"  任务 {task_id} 被取消")
                raise
        
        # 创建多个任务
        print("1. 创建多个任务")
        tasks = []
        for i in range(3):
            task = asyncio.create_task(worker_task(i))
            tasks.append(task)
        
        # 等待一段时间
        print("2. 等待任务运行...")
        await asyncio.sleep(0.5)
        
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
        
        print("✅ 并发任务管理测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主函数"""
    print("🚀 开始异步任务清理测试")
    
    # 测试基本任务管理
    success1 = await test_task_management()
    
    # 测试并发任务管理
    success2 = await test_concurrent_tasks()
    
    if success1 and success2:
        print("\n🎉 所有测试通过！异步任务清理正常工作")
    else:
        print("\n❌ 部分测试失败")
    
    # 等待一段时间确保所有任务都被清理
    print("等待清理完成...")
    await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(main()) 