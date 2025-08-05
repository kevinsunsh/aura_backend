#!/usr/bin/env python3
"""
TaskManager测试工具
直接使用TaskManager类的方法进行数据库操作
"""

import json
import uuid
import time
from typing import Dict, Any, Optional, List
from loguru import logger

# 添加项目根目录到Python路径
import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from agents.agent_memory.task.task_manager import TaskManager, TaskStateType

def print_task_info(task):
    """打印任务信息（测试工具专用）"""
    print(f"""
任务管理器信息:
  ID: {task.task_id}
  类型: {task.task_type}
  名称: {task.task_name}
  描述: {task.task_type_description}
  请求URL: {task.task_request_url}
  请求方法: {task.task_request_method}
  请求头: {json.dumps(task.task_request_headers, indent=2, ensure_ascii=False)}
  请求参数描述: {task.task_request_params_description}
  请求参数格式: {json.dumps(task.task_request_params_schema, indent=2, ensure_ascii=False)}
  响应参数描述: {task.task_response_description}
  响应参数格式: {json.dumps(task.task_response_schema, indent=2, ensure_ascii=False)}
  是否激活: {task.task_is_active}
  创建时间: {task.created_at}
  更新时间: {task.updated_at}
""")

def print_task_instance_info(task):
    """打印任务信息（测试工具专用）"""
    print(f"""
任务管理器信息:
  ID: {task.task_instance_id}
  状态: {task.task_state}
  结果: {task.task_result}
  创建时间: {task.created_at}
  更新时间: {task.updated_at}
""")

def main():
    """主函数 - 演示TaskManager的使用"""
    # 获取TaskManager实例
    task_manager = TaskManager.get_instance()
    task_manager.initialize()
    # 重建表（可选，用于清理数据）
    # print("=== 重建表 ===")
    # recreate_success = task_manager.recreate_tables()
    # print(f"重建表: {'成功' if recreate_success else '失败'}")
    
    # try:
    #     # 添加查询天气任务
    #     weather_success = task_manager.register_task(
    #         task_id=str(uuid.uuid4()),
    #         task_type="search_info",
    #         task_name="web_search",
    #         task_type_description="调用搜索引擎搜索信息",
    #         task_request_url="https://api.coze.cn/v1/workflow/stream_run",
    #         task_request_method="POST",
    #         task_request_headers={"Content-Type": "application/json",
    #                              "Authorization": "Bearer pat_9qFaDWjr3h1BbJfGjte4U7tO2AyBC3okUOZLLgCXMBADLQ0sL5WqBBeQxhZ1LmHm"},
    #         task_request_params_description="提供搜索内容",
    #         task_request_params_schema={
    #             "type": "object",
    #             "properties": {
    #                 "workflow_id": {"type": "string", "description": "工作流ID", "default": "7534616931148890122"},
    #                 "app_id": {"type": "string", "description": "应用ID", "default": "7534611500569346057"},
    #                 "parameters": {
    #                     "type": "object",
    #                     "properties": {
    #                         "BOT_USER_INPUT": {"type": "string", "description": "用户输入", "default": "上海的天气"},
    #                         "query": {"type": "string", "description": "查询内容", "default": "上海的天气"}
    #                     },
    #                     "required": ["BOT_USER_INPUT", "query"]
    #                 }
    #             },
    #             "required": ["workflow_id", "app_id", "parameters"]
    #         },
    #         task_response_description="返回搜索结果",
    #         task_response_schema={
    #             "type": "object",
    #             "properties": {
    #                 "result": {"type": "string", "description": "搜索结果"}
    #             }
    #         },
    #         task_is_active=True
    #     )
        
    #     print("=== 添加任务结果 ===")
    #     print(f"搜索信息任务: {'成功' if weather_success else '失败'}")
        
    #     # 获取激活的任务
    #     print("\n=== 激活的任务 ===")
    #     active_tasks = task_manager.get_all_active_tasks()
    #     for task in active_tasks:
    #         print_task_info(task)
    try:
        print("\n=== 查询特定任务 ===")
        weather_tasks = task_manager.get_task_instances_by_state("test_user_123444", TaskStateType.STARTED)
        for weather_task in weather_tasks:
            print_task_instance_info(weather_task)
            task_manager.set_task_state_and_result(weather_task.user_id, weather_task.task_instance_id, TaskStateType.DISMISSED, "running")
        # 查询特定任务
    #     print("\n=== 查询特定任务 ===")
    #     weather_tasks = task_manager.get_tasks_by_type("search_info")
    #     for weather_task in weather_tasks:
    #         if weather_task:
    #             print(f"""
    # 查询到的任务:
    # ID: {weather_task.task_id}
    # 类型: {weather_task.task_type}
    # 名称: {weather_task.task_name}
    # 描述: {weather_task.task_type_description} 
    # 请求URL: {weather_task.task_request_url}
    # 请求方法: {weather_task.task_request_method}
    # 请求头: {json.dumps(weather_task.task_request_headers, indent=2, ensure_ascii=False)}
    # 请求参数描述: {weather_task.task_request_params_description}
    # 请求参数格式: {json.dumps(weather_task.task_request_params_schema, indent=2, ensure_ascii=False)}
    # 响应参数描述: {weather_task.task_response_description}
    # 响应参数格式: {json.dumps(weather_task.task_response_schema, indent=2, ensure_ascii=False)}
    # """)
    except Exception as e:
        logger.error(f"运行示例时出错: {e}")

if __name__ == "__main__":
    main()
