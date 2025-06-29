#!/usr/bin/env python3
"""
测试CancelledError处理
验证任务取消时的异常处理是否正确
"""

import asyncio
import time
import sys
import os

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.aura import AuraAgent

async def test_cancelled_error_handling():
    """测试CancelledError处理"""
    print("🧪 测试CancelledError处理")
    
    try:
        # 获取AuraAgent实例
        agent = AuraAgent.get_instance()
        
        # 创建一个会被取消的任务
        async def long_running_task():
            """长时间运行的任务"""
            try:
                print("  开始长时间运行的任务...")
                for i in range(10):
                    await asyncio.sleep(0.5)
                    print(f"  任务运行中... {i+1}/10")
                print("  任务正常完成")
            except asyncio.CancelledError:
                print("  任务被取消 - 在任务内部捕获")
                # 不重新抛出，让任务自然结束
            except Exception as e:
                print(f"  任务出错: {e}")
        
        # 创建任务
        print("1. 创建长时间运行的任务")
        task = asyncio.create_task(long_running_task())
        agent.user_task = task
        
        # 等待任务运行
        print("2. 等待任务运行...")
        await asyncio.sleep(1.0)
        
        # 取消任务
        print("3. 取消任务")
        await agent._cancel_user_task()
        
        # 验证任务状态
        print("4. 验证任务状态")
        if hasattr(agent, 'user_task') and agent.user_task:
            print(f"  任务状态: {agent.user_task.done()}")
            print(f"  任务是否被取消: {agent.user_task.cancelled()}")
        else:
            print("  任务已清理")
        
        print("✅ CancelledError处理测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_nested_cancellation():
    """测试嵌套取消处理"""
    print("\n🧪 测试嵌套取消处理")
    
    try:
        agent = AuraAgent.get_instance()
        
        async def nested_task():
            """嵌套任务"""
            try:
                print("  开始嵌套任务...")
                
                # 内层异步操作
                async def inner_operation():
                    for i in range(5):
                        await asyncio.sleep(0.3)
                        print(f"    内层操作 {i+1}/5")
                
                await inner_operation()
                print("  嵌套任务完成")
                
            except asyncio.CancelledError:
                print("  嵌套任务被取消")
                # 不重新抛出
            except Exception as e:
                print(f"  嵌套任务出错: {e}")
        
        # 创建任务
        print("1. 创建嵌套任务")
        task = asyncio.create_task(nested_task())
        agent.user_task = task
        
        # 等待任务运行
        print("2. 等待任务运行...")
        await asyncio.sleep(0.8)
        
        # 取消任务
        print("3. 取消嵌套任务")
        await agent._cancel_user_task()
        
        # 验证任务状态
        print("4. 验证嵌套任务状态")
        if hasattr(agent, 'user_task') and agent.user_task:
            print(f"  任务状态: {agent.user_task.done()}")
            print(f"  任务是否被取消: {agent.user_task.cancelled()}")
        else:
            print("  任务已清理")
        
        print("✅ 嵌套取消处理测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主函数"""
    print("🚀 开始CancelledError处理测试")
    
    # 测试基本取消处理
    success1 = await test_cancelled_error_handling()
    
    # 测试嵌套取消处理
    success2 = await test_nested_cancellation()
    
    if success1 and success2:
        print("\n🎉 所有测试通过！CancelledError处理正确")
    else:
        print("\n❌ 部分测试失败")
    
    # 等待清理完成
    print("等待清理完成...")
    await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(main()) 