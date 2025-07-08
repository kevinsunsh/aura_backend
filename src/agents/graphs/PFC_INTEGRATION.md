# PFC模块集成文档

## 概述

本文档描述了如何将PFC（Prefrontal Cortex）模块的逻辑集成到main_graph中，使用langgraph框架实现智能对话管理。

## 架构设计

### 1. 状态管理 (main_state.py)

PFC模块扩展了MainState，添加了以下关键字段：

- **对话状态管理**：
  - `conversation_state`: 当前对话状态（INIT, ANALYZING, PLANNING, GENERATING, SENDING, WAITING, ENDED等）
  - `current_action`: 当前执行的行动类型
  - `action_reason`: 行动原因

- **目标管理**：
  - `goals`: 对话目标列表
  - `current_goal`: 当前主要目标

- **历史记录**：
  - `action_history`: 行动历史记录
  - `last_successful_reply_action`: 上一次成功的回复行动

- **观察信息**：
  - `new_messages_count`: 新消息数量
  - `chat_history_str`: 聊天历史字符串
  - `unprocessed_messages`: 未处理的消息列表

- **知识管理**：
  - `knowledge_list`: 知识列表

- **控制标志**：
  - `should_continue`: 是否继续对话
  - `is_ignored`: 是否被忽略

### 2. 提示词管理 (main_prompt.py)

集成了PFC模块所需的所有提示词模板：

- **行动规划提示词**：
  - `PFC_ACTION_PLANNER_INITIAL_PROMPT`: 首次回复决策
  - `PFC_ACTION_PLANNER_FOLLOW_UP_PROMPT`: 连续回复决策

- **目标分析提示词**：
  - `PFC_GOAL_ANALYZER_PROMPT`: 对话目标分析

- **回复生成提示词**：
  - `PFC_REPLY_GENERATOR_DIRECT_PROMPT`: 直接回复生成
  - `PFC_REPLY_GENERATOR_FOLLOW_UP_PROMPT`: 连续消息生成
  - `PFC_REPLY_GENERATOR_FAREWELL_PROMPT`: 告别语生成

- **其他提示词**：
  - `PFC_END_DECISION_PROMPT`: 结束对话决策
  - `PFC_KNOWLEDGE_FETCHER_PROMPT`: 知识获取

### 3. 图结构 (main_graph.py)

使用langgraph框架构建了完整的PFC对话流程：

#### 核心节点

1. **observe_conversation**: 观察对话状态
   - 获取新消息
   - 更新观察信息
   - 触发目标分析

2. **analyze_goals**: 分析对话目标
   - 分析聊天历史
   - 设定或更新对话目标
   - 进入行动规划

3. **plan_action**: 规划下一步行动
   - 基于当前状态和目标
   - 选择最优行动类型
   - 进入行动执行

4. **execute_action**: 执行规划的行动
   - 根据行动类型路由到相应处理
   - 支持多种行动类型

5. **generate_reply**: 生成回复
   - 根据行动类型选择提示词
   - 生成自然回复

6. **send_message**: 发送消息
   - 流式发送回复
   - 保存消息到数据库
   - 更新状态

7. **fetch_knowledge**: 获取知识
   - 从知识库获取相关信息
   - 更新知识列表

8. **wait_for_user_message**: 等待用户消息
   - 检查控制标志
   - 等待后重新观察

9. **end_conversation**: 结束对话
   - 决定是否发送告别语
   - 优雅结束对话

10. **block_and_ignore**: 屏蔽并忽略
    - 设置忽略时间
    - 暂时屏蔽对话

#### 流程控制

```
START → observe_conversation → analyze_goals → plan_action → execute_action
                                                                    ↓
END ← block_and_ignore ← end_conversation ← wait_for_user_message ← send_message ← generate_reply
```

## 行动类型

PFC模块支持以下行动类型：

1. **direct_reply**: 直接回复用户
2. **send_new_message**: 发送连续消息
3. **fetch_knowledge**: 获取知识
4. **wait**: 等待用户回复
5. **listening**: 倾听用户发言
6. **rethink_goal**: 重新思考目标
7. **end_conversation**: 结束对话
8. **block_and_ignore**: 屏蔽并忽略

## 状态转换

### 对话状态枚举

- `INIT`: 初始化
- `ANALYZING`: 分析历史
- `PLANNING`: 规划目标
- `GENERATING`: 生成回复
- `SENDING`: 发送消息
- `WAITING`: 等待
- `ENDED`: 结束
- `ERROR`: 错误
- `IGNORED`: 屏蔽

### 状态转换规则

1. **INIT → ANALYZING**: 初始化完成后开始分析
2. **ANALYZING → PLANNING**: 分析完成后开始规划
3. **PLANNING → GENERATING**: 规划完成后生成回复
4. **GENERATING → SENDING**: 生成完成后发送消息
5. **SENDING → WAITING**: 发送完成后等待响应
6. **WAITING → ANALYZING**: 等待结束后重新分析

## 工具函数

### 状态构建函数

- `_build_goals_str()`: 构建目标字符串
- `_build_knowledge_info_str()`: 构建知识信息字符串
- `_build_action_history_summary()`: 构建行动历史概要
- `_get_persona_text()`: 获取人设文本

### 错误处理

所有节点都包含完整的错误处理机制：

1. **异常捕获**: 使用try-catch包装所有操作
2. **状态更新**: 错误时更新conversation_state为ERROR
3. **错误信息**: 记录详细的错误信息
4. **优雅退出**: 错误时正确退出到END节点

## 使用示例

### 基本使用

```python
from src.agents.graphs.main_graph import graph
from src.agents.states.main_state import MainState, ConversationState

# 初始化状态
initial_state = MainState(
    chat_id="test_chat",
    user_id="test_user",
    conversation_state=ConversationState.INIT,
    # ... 其他字段
)

# 运行图
async for event in graph.astream(initial_state, config=config):
    print(f"状态更新: {event}")
```

### 自定义配置

```python
# 修改等待时间
state["waiting_for_user_message_at"] = time.time()

# 设置忽略时间
state["ignore_until_timestamp"] = time.time() + 3600

# 手动结束对话
state["should_continue"] = False
```

## 测试

运行测试脚本验证PFC模块功能：

```bash
python tests/test_pfc_main_graph.py
```

## 扩展性

### 添加新的行动类型

1. 在`ActionType`枚举中添加新类型
2. 在`_execute_action`中添加处理逻辑
3. 在提示词中添加新行动类型的说明

### 添加新的状态

1. 在`ConversationState`枚举中添加新状态
2. 在相应的节点中更新状态转换逻辑

### 自定义提示词

1. 在`main_prompt.py`中添加新的提示词模板
2. 在相应的节点中使用新的提示词

## 性能优化

### 缓存策略

- 消息历史缓存
- 知识查询结果缓存
- 目标分析结果缓存

### 异步处理

- 消息获取异步化
- 知识查询异步化
- 回复生成异步化

## 总结

PFC模块的集成实现了：

1. **完整的对话管理流程**: 从观察到执行的全流程
2. **智能的目标管理**: 动态设定和更新对话目标
3. **灵活的行动规划**: 基于当前状态选择最优行动
4. **自然的回复生成**: 符合人设的自然回复
5. **健壮的错误处理**: 完整的异常处理机制
6. **良好的扩展性**: 易于添加新功能和自定义

这个集成将PFC模块的先进对话管理能力与langgraph框架的强大图计算能力相结合，为智能对话系统提供了坚实的基础。 