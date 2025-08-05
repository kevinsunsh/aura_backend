#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EntorhinalCortex类的数据库操作
"""

import sys
import os
# 自动添加src到sys.path，保证包内导入正常
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

import asyncio
from loguru import logger
from agents.agent_memory.Hippocampus import EntorhinalCortex, Hippocampus, GraphNodes, GraphEdges
from agents.agent_memory.message_store import MessageStore

async def test_entorhinal_cortex_db_operations():
    """测试EntorhinalCortex类的数据库操作"""
    print("🧪 开始测试EntorhinalCortex数据库操作...")
    
    try:
        # 初始化Hippocampus和EntorhinalCortex
        hippocampus = Hippocampus()
        hippocampus.initialize()
        entorhinal_cortex = EntorhinalCortex(hippocampus)
        
        # 测试1: 从数据库同步数据到内存
        print("📥 测试从数据库同步数据到内存...")
        entorhinal_cortex.sync_memory_from_db()
        print(f"✅ 内存中的节点数量: {len(entorhinal_cortex.memory_graph.G.nodes())}")
        print(f"✅ 内存中的边数量: {len(entorhinal_cortex.memory_graph.G.edges())}")
        
        # 测试2: 添加一些测试数据到内存
        print("➕ 添加测试数据到内存...")
        entorhinal_cortex.memory_graph.add_dot("测试概念1", ["记忆项1", "记忆项2"])
        entorhinal_cortex.memory_graph.add_dot("测试概念2", ["记忆项3", "记忆项4"])
        entorhinal_cortex.memory_graph.connect_dot("测试概念1", "测试概念2")
        
        print(f"✅ 添加后内存中的节点数量: {len(entorhinal_cortex.memory_graph.G.nodes())}")
        print(f"✅ 添加后内存中的边数量: {len(entorhinal_cortex.memory_graph.G.edges())}")
        
        # 测试3: 同步内存数据到数据库
        print("📤 测试同步内存数据到数据库...")
        await entorhinal_cortex.sync_memory_to_db()
        print("✅ 同步到数据库完成")
        
        # 测试4: 验证数据库中的数据
        print("🔍 验证数据库中的数据...")
        session = MessageStore.get_instance().db.get_db()
        try:
            nodes_count = session.query(GraphNodes).count()
            edges_count = session.query(GraphEdges).count()
            print(f"✅ 数据库中的节点数量: {nodes_count}")
            print(f"✅ 数据库中的边数量: {edges_count}")
            
            # 查询具体的节点
            test_node = session.query(GraphNodes).filter(
                GraphNodes.concept == "测试概念1"
            ).first()
            if test_node:
                print(f"✅ 找到测试节点: {test_node.concept}")
                print(f"✅ 节点数据: {test_node.memory_items}")
            else:
                print("❌ 未找到测试节点")
                
        except Exception as e:
            print(f"❌ 验证数据库数据时出错: {e}")
        finally:
            session.close()
        
        # 测试5: 重新同步数据到内存
        print("🔄 测试重新同步数据到内存...")
        entorhinal_cortex.memory_graph.G.clear()  # 清空内存
        entorhinal_cortex.sync_memory_from_db()
        print(f"✅ 重新同步后内存中的节点数量: {len(entorhinal_cortex.memory_graph.G.nodes())}")
        print(f"✅ 重新同步后内存中的边数量: {len(entorhinal_cortex.memory_graph.G.edges())}")
        
        print("🎉 所有测试完成！")
        
    except Exception as e:
        print(f"❌ 测试过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_entorhinal_cortex_db_operations()) 