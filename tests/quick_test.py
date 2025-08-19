#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试脚本

用于快速验证配置导入导出功能是否正常工作
"""

import sys
import os
# 自动添加src到sys.path，保证包内导入正常
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

import json
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from agents.agent_memory.configuration.config_import_export import ConfigImportExport

def quick_test():
    """快速测试配置导入导出功能"""
    print("🚀 开始快速测试配置导入导出功能...")
    
    # 创建工具实例
    tool = ConfigImportExport()
    
    # 测试文件路径
    test_file = "quick_test_configs.json"
    
    try:
        # 1. 列出当前配置
        # print("\n📋 1. 列出当前配置...")
        # tool.list_configs(environment="production")
        
        # 2. 导出配置到文件
        # print(f"\n📤 2. 导出配置到文件: {test_file}")
        # configs = tool.export_configs(environment="production", output_file=test_file)
        
        # 检查导出结果
        # exported_count = len(configs) if configs else 0
        # print(f"✓ 成功导出 {exported_count} 个配置")
        
        # if exported_count > 0:
        # 3. 预览一个配置
        # print("\n👀 3. 预览内存配置...")
        # tool.preview_config("memory", environment="production")
        # tool.preview_config("model", environment="test")
        # return True
        # 4. 从文件重新导入（测试环境）
        # print(f"\n📥 4. 从文件导入配置到测试环境...")
        success = tool.import_from_file(test_file, environment="production", overwrite=True)
        
        # if success:
        #     print("✓ 导入成功")
            
        #     # 5. 验证导入的配置
        #     print("\n✅ 5. 验证导入的配置...")
        #     tool.list_configs(environment="test")
            
        #     tool.preview_config("model", environment="test")

        #     print("\n🎉 快速测试完成！所有功能正常")
        #     return True
        # else:
        #     print("❌ 导入失败")
        #     return False
        # else:
        #     print("⚠ 没有配置可导出，可能需要先初始化配置")
        #     return False
            
    except Exception as e:
        print(f"❌ 测试过程中出错: {e}")
        return False
    
    finally:
        # 可选：清理测试文件（注释掉以保留文件）
        # if os.path.exists(test_file):
        #     os.remove(test_file)
        #     print(f"🧹 清理测试文件: {test_file}")
        pass

def test_specific_config():
    """测试特定配置"""
    print("\n🔧 测试特定配置...")
    
    tool = ConfigImportExport()
    
    # 测试配置分类
    test_categories = ["memory", "chat", "bot"]
    
    for category in test_categories:
        print(f"\n测试配置: {category}")
        try:
            # 预览配置
            tool.preview_config(category, environment="production")
        except Exception as e:
            print(f"❌ 测试 {category} 失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("配置导入导出快速测试工具")
    print("=" * 60)
    
    # 运行快速测试
    success = quick_test()
    
    # if success:
    #     # 测试特定配置
    #     test_specific_config()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 所有测试通过！配置系统工作正常")
    else:
        print("❌ 测试失败，请检查配置和数据库连接")
    print("=" * 60)
    
    return success

if __name__ == "__main__":
    exit(0 if main() else 1) 