#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新创建数据库表脚本

用于重新创建配置系统的数据库表，使用新的复合主键设计
"""

import sys
import os
from agents.aura_memory.database.database import Database
from configuration.database_models import ConfigurationModel, ConfigurationHistoryModel, ConfigurationTemplateModel
from configuration.config import get_db_conn_string

def recreate_tables():
    """重新创建数据库表"""
    print("🔄 开始重新创建数据库表...")
    
    try:
        # 获取数据库连接字符串
        conn_string = get_db_conn_string()
        
        print(f"🔗 连接字符串: {conn_string}")
        
        # 创建数据库实例
        db = Database(conn_string)
        
        # 删除所有表
        print("🗑️ 删除现有表...")
        with db.get_session() as session:
            # 删除配置相关的表
            session.execute("DROP TABLE IF EXISTS configurations CASCADE")
            session.execute("DROP TABLE IF EXISTS configuration_history CASCADE")
            session.execute("DROP TABLE IF EXISTS configuration_templates CASCADE")
            session.commit()
            print("✅ 现有表已删除")
        
        # 重新创建所有表
        print("🏗️ 创建新表...")
        db.create_all_tables()
        
        print("✅ 数据库表重新创建完成！")
        
        # 验证表结构
        print("🔍 验证表结构...")
        with db.get_session() as session:
            # 检查配置表
            result = session.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            tables = [row[0] for row in result]
            print(f"📋 现有表: {tables}")
            
            # 检查主键约束
            result = session.execute("""
                SELECT 
                    tc.table_name, 
                    kcu.column_name,
                    tc.constraint_name,
                    tc.constraint_type
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu 
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_schema = 'public' 
                    AND tc.table_name = 'configurations'
                    AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
            """)
            
            primary_keys = [(row[0], row[1]) for row in result]
            print(f"🔑 主键约束: {primary_keys}")
            
            if len(primary_keys) == 2 and 'id' in [pk[1] for pk in primary_keys] and 'environment' in [pk[1] for pk in primary_keys]:
                print("✅ 复合主键设置正确！")
            else:
                print("❌ 主键设置不正确！")
        
        return True
        
    except Exception as e:
        print(f"❌ 重新创建表失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("数据库表重新创建工具")
    print("=" * 60)
    
    success = recreate_tables()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 数据库表重新创建成功！")
        print("💡 现在可以运行初始化配置脚本了")
    else:
        print("❌ 数据库表重新创建失败！")
    print("=" * 60)
    
    return success

if __name__ == "__main__":
    exit(0 if main() else 1) 