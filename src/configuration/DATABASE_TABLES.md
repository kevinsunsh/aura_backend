# 数据库表结构梳理

## 概述

Aura Backend 系统使用 PostgreSQL 数据库，包含多个功能模块的数据表。以下是所有数据表的详细结构。

## 配置系统相关表

### 1. configurations (配置主表)
**文件**: `src/agents/configuration/database_models.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | String | 配置ID（主键） | PRIMARY KEY |
| name | String | 配置名称 | NOT NULL |
| description | Text | 配置描述 | NULL |
| category | String | 配置分类 | NOT NULL |
| config_data | JSONB | 配置数据（JSON格式） | NOT NULL |
| config_schema | JSONB | 配置模式（用于验证） | NULL |
| version | String | 配置版本 | NOT NULL, DEFAULT '1.0.0' |
| is_active | Boolean | 是否激活 | NOT NULL, DEFAULT TRUE |
| is_default | Boolean | 是否为默认配置 | NOT NULL, DEFAULT FALSE |
| environment | String | 环境 | NOT NULL, DEFAULT 'production' |
| created_at | BigInteger | 创建时间 | NOT NULL |
| updated_at | BigInteger | 更新时间 | NOT NULL |
| last_used_at | BigInteger | 最后使用时间 | NULL |

**索引**:
- `idx_configurations_category` (category)
- `idx_configurations_environment` (environment)
- `idx_configurations_is_active` (is_active)
- `idx_configurations_created_at` (created_at)
- `idx_configurations_updated_at` (updated_at)

### 2. configuration_history (配置历史记录表)
**文件**: `src/agents/configuration/database_models.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | String | 历史记录ID（主键） | PRIMARY KEY |
| config_id | String | 关联的配置ID | NOT NULL |
| config_data | JSONB | 历史配置数据 | NOT NULL |
| config_schema | JSONB | 历史配置模式 | NULL |
| version | String | 版本号 | NOT NULL |
| change_description | Text | 变更描述 | NULL |
| operation | String | 操作类型 | NOT NULL |
| operator | String | 操作者 | NULL |
| created_at | BigInteger | 创建时间 | NOT NULL |

**索引**:
- `idx_configuration_history_config_id` (config_id)
- `idx_configuration_history_version` (version)
- `idx_configuration_history_created_at` (created_at)

### 3. configuration_templates (配置模板表)
**文件**: `src/agents/configuration/database_models.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | String | 模板ID（主键） | PRIMARY KEY |
| name | String | 模板名称 | NOT NULL |
| description | Text | 模板描述 | NULL |
| category | String | 模板分类 | NOT NULL |
| template_data | JSONB | 模板数据 | NOT NULL |
| template_schema | JSONB | 模板模式 | NULL |
| is_public | Boolean | 是否公开 | NOT NULL, DEFAULT TRUE |
| tags | JSONB | 标签 | NULL |
| created_at | BigInteger | 创建时间 | NOT NULL |
| updated_at | BigInteger | 更新时间 | NOT NULL |

**索引**:
- `idx_configuration_templates_category` (category)
- `idx_configuration_templates_is_public` (is_public)
- `idx_configuration_templates_created_at` (created_at)

## 消息系统相关表

### 4. messages (消息表)
**文件**: `src/agents/agent_memory/message_store.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| msg_id | String | 消息ID（主键） | PRIMARY KEY |
| chat_id | String | 聊天ID | NOT NULL |
| user_id | String | 用户ID | NOT NULL |
| platform | String | 平台 | NOT NULL |
| m_type | String | 消息类型 | NOT NULL |
| content | String | 消息内容 | NOT NULL |
| data | JSONB | 消息数据 | NOT NULL |
| created_at | BigInteger | 创建时间 | NOT NULL |

**索引**:
- `idx_messages_created_at` (created_at)
- `idx_messages_chat_id` (chat_id)
- `idx_messages_user_id` (user_id)
- `idx_messages_platform` (platform)

### 5. chat_streams (聊天流表)
**文件**: `src/agents/agent_memory/chat_stream.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| chat_id | String | 聊天ID（主键） | PRIMARY KEY |
| chatstream_checked_at | BigInteger | 预处理器检查时间 | NOT NULL |
| created_at | BigInteger | 创建时间 | NOT NULL |
| chatstream_locked | Boolean | 处理器锁 | NOT NULL, DEFAULT FALSE |
| chatstream_heartbeat | BigInteger | 处理器心跳 | NOT NULL, DEFAULT 0 |

**索引**:
- `idx_chat_streams_chatstream_checked_at` (chatstream_checked_at)
- `idx_chat_streams_created_at` (created_at)

## 记忆系统相关表

### 6. graph_nodes (记忆图节点表)
**文件**: `src/agents/agent_memory/Hippocampus.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| concept | String | 节点概念（主键） | PRIMARY KEY |
| memory_items | String | JSON格式存储的记忆列表 | NOT NULL |
| hash | String | 节点哈希值 | NOT NULL |
| created_time | BigInteger | 创建时间戳 | NOT NULL |
| last_modified | BigInteger | 最后修改时间戳 | NOT NULL |

**索引**:
- `idx_graph_nodes_created_time` (created_time)
- `idx_graph_nodes_hash` (hash)
- `idx_graph_nodes_last_modified` (last_modified)

### 7. graph_edges (记忆图边表)
**文件**: `src/agents/agent_memory/Hippocampus.py`

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| source | String | 源节点 | NOT NULL |
| target | String | 目标节点 | NOT NULL |
| strength | Integer | 连接强度 | NOT NULL |
| hash | String | 边哈希值 | NOT NULL |
| created_time | BigInteger | 创建时间戳 | NOT NULL |
| last_modified | BigInteger | 最后修改时间戳 | NOT NULL |

**约束**:
- PRIMARY KEY (source, target)

**索引**:
- `idx_graph_edges_source` (source)
- `idx_graph_edges_target` (target)
- `idx_graph_edges_hash` (hash)
- `idx_graph_edges_created_time` (created_time)
- `idx_graph_edges_last_modified` (last_modified)

## 配置分类说明

系统支持以下配置分类，每个分类对应一个配置记录：

### 核心配置
- `memory`: 记忆配置
- `chat`: 聊天配置
- `bot`: 机器人配置
- `personality`: 人格配置
- `identity`: 身份配置
- `relationship`: 关系配置

### 消息处理配置
- `message_receive`: 消息接收配置
- `normal_chat`: 普通聊天配置
- `focus_chat`: 专注聊天配置

### 表达配置
- `emoji`: 表情配置
- `expression`: 表达配置
- `mood`: 情绪配置

### 响应处理配置
- `keyword_reaction`: 关键词反应配置
- `chinese_typo`: 中文错别字配置
- `response_post_process`: 回复后处理配置
- `response_splitter`: 回复分割器配置

### 系统配置
- `telemetry`: 遥测配置
- `experimental`: 实验功能配置
- `model`: 模型配置
- `maim_message`: 主要消息配置
- `lpmm_knowledge`: LPMM知识库配置
- `tool`: 工具配置
- `debug`: 调试配置

## 环境支持

系统支持多环境配置隔离：

- `production`: 生产环境
- `development`: 开发环境
- `test`: 测试环境

## 数据库连接配置

**文件**: `src/config.py`

```python
# PostgreSQL 配置
POSTGRES_HOST: str = "sh-postgres-c93lya14.sql.tencentcdb.com"
POSTGRES_PORT: int = 25561
POSTGRES_DB: str = "aura-PostgreSQL"
POSTGRES_USER: str = "root"
POSTGRES_PASSWORD: str = "X1KxZeMkM#nobqKiq"
POSTGRES_SCHEMA: str = "public"
```

## 表关系图

```
configurations (配置主表)
├── configuration_history (配置历史记录表)
│   └── config_id -> configurations.id
└── configuration_templates (配置模板表)

messages (消息表)
└── chat_id -> chat_streams.chat_id

chat_streams (聊天流表)
└── chat_id (独立)

graph_nodes (记忆图节点表)
└── concept (独立)

graph_edges (记忆图边表)
├── source -> graph_nodes.concept
└── target -> graph_nodes.concept
```

## 性能优化

### 索引策略
- 所有表都包含时间戳索引，支持时间范围查询
- 配置表按分类和环境建立索引，支持快速筛选
- 消息表按聊天ID和用户ID建立索引，支持会话查询
- 记忆图表按哈希值建立索引，支持快速查找

### 连接池配置
- 连接池大小: 10-30（根据环境调整）
- 最大溢出连接: 20-50
- 连接回收时间: 30分钟
- 连接超时: 10秒

### 缓存策略
- 配置缓存: 5分钟TTL
- 线程安全缓存操作
- 支持缓存清理和过期检查

## 数据迁移

### 从文件配置迁移到数据库
```bash
python src/agents/configuration/config_tools.py migrate config.toml
```

### 初始化默认配置
```bash
python src/agents/configuration/config_tools.py init
```

## 监控和维护

### 表大小监控
```sql
SELECT 
    schemaname,
    tablename,
    attname,
    n_distinct,
    correlation
FROM pg_stats
WHERE tablename IN ('configurations', 'messages', 'chat_streams', 'graph_nodes', 'graph_edges');
```

### 索引使用情况
```sql
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE tablename IN ('configurations', 'messages', 'chat_streams', 'graph_nodes', 'graph_edges');
```

### 连接池状态
```python
from agents.agent_memory.database.database import Database
db = Database()
pool_info = db.get_connection_info()
print(pool_info)
``` 