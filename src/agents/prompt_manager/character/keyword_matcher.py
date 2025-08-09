#!/usr/bin/env python3
"""
关键字匹配功能 - 用于角色书条目的智能匹配
"""

from typing import List, Dict, Any, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from .models import CharacterBookEntryModel

class KeywordMatcher:
    """关键字匹配器"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def find_matching_entries(self, user_input: str, 
                            character_id: str = None,
                            enabled_only: bool = True) -> List[CharacterBookEntryModel]:
        """
        根据用户输入查找匹配的角色书条目
        
        Args:
            user_input: 用户输入的关键词
            character_id: 角色ID（可选）
            enabled_only: 是否只搜索启用的条目
            
        Returns:
            匹配的条目列表，按优先级排序
        """
        # 预处理用户输入
        keywords = self._preprocess_input(user_input)
        
        # 构建查询
        query = self.session.query(CharacterBookEntryModel)
        
        # 只搜索启用的条目
        if enabled_only:
            query = query.filter(CharacterBookEntryModel.enabled == True)
        
        # 如果指定了角色ID，添加过滤条件
        if character_id:
            query = query.join(CharacterBookEntryModel.character_book).filter(
                CharacterBookEntryModel.character_book.has(character_id=character_id)
            )
        
        # 构建搜索条件
        conditions = []
        
        for keyword in keywords:
            # 精确匹配主要关键词
            conditions.append(CharacterBookEntryModel.keys.contains([keyword]))
            # 精确匹配次要关键词
            conditions.append(CharacterBookEntryModel.secondary_keys.contains([keyword]))
            # 内容中包含关键词
            conditions.append(CharacterBookEntryModel.content.ilike(f'%{keyword}%'))
        
        # 应用搜索条件
        query = query.filter(or_(*conditions))
        
        # 按插入顺序排序
        query = query.order_by(CharacterBookEntryModel.insertion_order)
        
        return query.all()
    
    def find_best_matches(self, user_input: str, 
                         character_id: str = None,
                         limit: int = 5) -> List[Dict[str, Any]]:
        """
        查找最佳匹配的条目，并计算匹配分数
        
        Args:
            user_input: 用户输入
            character_id: 角色ID
            limit: 返回结果数量限制
            
        Returns:
            包含匹配分数的条目列表
        """
        entries = self.find_matching_entries(user_input, character_id)
        
        # 计算匹配分数
        scored_entries = []
        keywords = self._preprocess_input(user_input)
        
        for entry in entries:
            score = self._calculate_match_score(entry, keywords)
            if score > 0:
                scored_entries.append({
                    'entry': entry,
                    'score': score,
                    'matched_keywords': self._get_matched_keywords(entry, keywords)
                })
        
        # 按分数排序
        scored_entries.sort(key=lambda x: x['score'], reverse=True)
        
        return scored_entries[:limit]
    
    def _preprocess_input(self, user_input: str) -> List[str]:
        """
        预处理用户输入，提取关键词
        
        Args:
            user_input: 用户输入
            
        Returns:
            关键词列表
        """
        # 简单的关键词提取
        keywords = []
        
        # 去除标点符号和多余空格
        cleaned_input = user_input.strip()
        
        # 按空格分割
        words = cleaned_input.split()
        
        for word in words:
            if len(word) > 1:  # 忽略单字符
                keywords.append(word)
        
        return keywords
    
    def _calculate_match_score(self, entry: CharacterBookEntryModel, keywords: List[str]) -> float:
        """
        计算条目与关键词的匹配分数
        
        Args:
            entry: 角色书条目
            keywords: 关键词列表
            
        Returns:
            匹配分数 (0-1)
        """
        score = 0.0
        
        # 检查主要关键词匹配
        if entry.keys:
            for keyword in keywords:
                if keyword in entry.keys:
                    score += 0.4  # 主要关键词权重最高
        
        # 检查次要关键词匹配
        if entry.secondary_keys:
            for keyword in keywords:
                if keyword in entry.secondary_keys:
                    score += 0.3  # 次要关键词权重中等
        
        # 检查内容匹配
        if entry.content:
            for keyword in keywords:
                if keyword.lower() in entry.content.lower():
                    score += 0.2  # 内容匹配权重较低
        
        # 考虑条目的其他属性
        if entry.constant:
            score += 0.1  # 常驻条目加分
        
        # 归一化分数
        return min(score, 1.0)
    
    def _get_matched_keywords(self, entry: CharacterBookEntryModel, keywords: List[str]) -> List[str]:
        """
        获取匹配的关键词
        
        Args:
            entry: 角色书条目
            keywords: 搜索关键词
            
        Returns:
            匹配的关键词列表
        """
        matched = []
        
        for keyword in keywords:
            # 检查主要关键词
            if entry.keys and keyword in entry.keys:
                matched.append(f"主要关键词: {keyword}")
            
            # 检查次要关键词
            if entry.secondary_keys and keyword in entry.secondary_keys:
                matched.append(f"次要关键词: {keyword}")
            
            # 检查内容
            if entry.content and keyword.lower() in entry.content.lower():
                matched.append(f"内容匹配: {keyword}")
        
        return matched

# 使用示例
def demonstrate_keyword_matching():
    """演示关键字匹配功能"""
    
    print("=== 关键字匹配功能演示 ===")
    
    # 模拟一些测试数据
    test_cases = [
        "你叫什么名字",
        "你的工作是什么",
        "你喜欢什么",
        "你的爱好",
        "你的年龄",
        "你的职业"
    ]
    
    print("\n测试用例:")
    for i, test_case in enumerate(test_cases, 1):
        print(f"{i}. {test_case}")
    
    print("\n预期匹配结果:")
    print("1. '你叫什么名字' -> 匹配 ['名字', '姓名'] 关键词")
    print("2. '你的工作是什么' -> 匹配 ['工作', '职业'] 关键词")
    print("3. '你喜欢什么' -> 匹配 ['爱好', '兴趣'] 关键词")
    print("4. '你的爱好' -> 匹配 ['爱好'] 关键词")
    print("5. '你的年龄' -> 匹配内容中的年龄信息")
    print("6. '你的职业' -> 匹配 ['职业'] 关键词")

# SQL查询优化示例
def sql_optimization_examples():
    """SQL查询优化示例"""
    
    print("\n=== SQL查询优化示例 ===")
    
    # 1. 创建索引
    print("\n1. 创建GIN索引:")
    sql1 = """
    -- 为主要关键词创建索引
    CREATE INDEX idx_keys ON character_book_entries USING GIN (keys);
    
    -- 为次要关键词创建索引
    CREATE INDEX idx_secondary_keys ON character_book_entries USING GIN (secondary_keys);
    
    -- 为内容创建全文搜索索引
    CREATE INDEX idx_content ON character_book_entries USING GIN (to_tsvector('chinese', content));
    """
    print(sql1)
    
    # 2. 高效查询
    print("\n2. 高效查询:")
    sql2 = """
    -- 使用JSONB操作符进行快速查询
    SELECT * FROM character_book_entries 
    WHERE enabled = true
      AND (keys @> '["名字"]' OR secondary_keys @> '["昵称"]')
    ORDER BY insertion_order;
    """
    print(sql2)
    
    # 3. 复杂查询
    print("\n3. 复杂查询:")
    sql3 = """
    -- 组合多个搜索条件
    SELECT *, 
           CASE 
             WHEN keys @> '["名字"]' THEN 0.4
             WHEN secondary_keys @> '["昵称"]' THEN 0.3
             ELSE 0.1
           END as match_score
    FROM character_book_entries 
    WHERE enabled = true
      AND (keys @> '["名字"]' OR secondary_keys @> '["昵称"]' OR content ILIKE '%名字%')
    ORDER BY match_score DESC, insertion_order;
    """
    print(sql3)

if __name__ == "__main__":
    demonstrate_keyword_matching()
    sql_optimization_examples()
