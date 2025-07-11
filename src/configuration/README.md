# 数据库配置系统

本系统将配置管理从文件迁移到数据库，提供更灵活的配置管理能力。

## 系统架构

### 核心组件

1. **数据库模型** (`database_models.py`)
   - `ConfigurationModel`: 配置主表
   - `ConfigurationHistoryModel`: 配置历史记录表
   - `ConfigurationTemplateModel`: 配置模板表

2. **配置管理器** (`config_manager.py`)
   - `DatabaseConfigManager`: 负责配置的CRUD操作
   - 支持缓存机制，提高性能
   - 支持版本控制和历史记录

3. **配置加载器** (`config_loader.py`)
   - `DatabaseConfigLoader`: 从数据库加载配置
   - 支持环境隔离
   - 提供默认配置回退机制

4. **配置工具** (`config_tools.py`)
   - 命令行工具，用于管理配置
   - 支持配置的导入、导出、迁移

## 使用方法

### 1. 初始化配置

```python
from agents.configuration.config import initialize_database_configs

# 初始化默认配置
success = initialize_database_configs(environment="production")
```

### 2. 加载配置

```python
from agents.configuration.config import load_config_from_database

# 加载完整配置
config = load_config_from_database(environment="production")

# 加载特定配置
from agents.configuration.config import load_specific_config_from_database
memory_config = load_specific_config_from_database("memory", environment="production")
```

### 3. 保存配置

```python
from agents.configuration.config_loader import get_config_loader

config_loader = get_config_loader()
config_data = {
    "enable_memory": True,
    "memory_build_interval": 600,
    # ... 其他配置项
}

success = config_loader.save_config(
    config_name="memory",
    config_data=config_data,
    environment="production",
    description="自定义内存配置",
    is_default=True
)
```

### 4. 命令行工具

```bash
# 列出所有配置
python src/agents/configuration/config_tools.py list

# 显示特定配置
python src/agents/configuration/config_tools.py show memory

# 保存配置
python src/agents/configuration/config_tools.py save memory --file config.json

# 初始化默认配置
python src/agents/configuration/config_tools.py init

# 迁移文件配置到数据库
python src/agents/configuration/config_tools.py migrate config.toml

# 导出配置到文件
python src/agents/configuration/config_tools.py export memory output.json
```

## 配置分类

系统支持以下配置分类：

- `memory`: 记忆配置
- `chat`: 聊天配置
- `bot`: 机器人配置
- `personality`: 人格配置
- `identity`: 身份配置
- `relationship`: 关系配置
- `message_receive`: 消息接收配置
- `normal_chat`: 普通聊天配置
- `focus_chat`: 专注聊天配置
- `emoji`: 表情配置
- `expression`: 表达配置
- `mood`: 情绪配置
- `keyword_reaction`: 关键词反应配置
- `chinese_typo`: 中文错别字配置
- `response_post_process`: 回复后处理配置
- `response_splitter`: 回复分割器配置
- `telemetry`: 遥测配置
- `experimental`: 实验功能配置
- `model`: 模型配置
- `maim_message`: 主要消息配置
- `lpmm_knowledge`: LPMM知识库配置
- `tool`: 工具配置
- `debug`: 调试配置

## 环境支持

系统支持多环境配置：

- `production`: 生产环境
- `development`: 开发环境
- `test`: 测试环境

## 数据库表结构

### configurations 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String | 配置ID（主键） |
| name | String | 配置名称 |
| description | Text | 配置描述 |
| category | String | 配置分类 |
| config_data | JSONB | 配置数据 |
| config_schema | JSONB | 配置模式 |
| version | String | 版本号 |
| is_active | Boolean | 是否激活 |
| is_default | Boolean | 是否为默认配置 |
| environment | String | 环境 |
| created_at | BigInteger | 创建时间 |
| updated_at | BigInteger | 更新时间 |
| last_used_at | BigInteger | 最后使用时间 |

### configuration_history 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String | 历史记录ID（主键） |
| config_id | String | 关联的配置ID |
| config_data | JSONB | 历史配置数据 |
| config_schema | JSONB | 历史配置模式 |
| version | String | 版本号 |
| change_description | Text | 变更描述 |
| operation | String | 操作类型 |
| operator | String | 操作者 |
| created_at | BigInteger | 创建时间 |

## 迁移指南

### 从文件配置迁移

1. 使用命令行工具迁移：

```bash
python src/agents/configuration/config_tools.py migrate config.toml
```

2. 使用Python代码迁移：

```python
from agents.configuration.config import migrate_file_config_to_database

success = migrate_file_config_to_database("config.toml", environment="production")
```

### 兼容性

系统保持向后兼容，原有的文件配置加载函数仍然可用，但会显示废弃警告：

```python
# 已废弃，建议使用数据库配置
from agents.configuration.config import load_config_legacy
config = load_config_legacy("config.toml")
```

## 性能优化

### 缓存机制

- 配置缓存时间：5分钟
- 支持缓存清理和过期检查
- 线程安全的缓存操作

### 数据库优化

- 使用连接池
- 索引优化
- 批量操作支持

## 监控和日志

系统提供详细的日志记录：

- 配置加载日志
- 缓存命中日志
- 错误和异常日志
- 性能监控日志

## 故障排除

### 常见问题

1. **配置加载失败**
   - 检查数据库连接
   - 确认配置表是否存在
   - 查看错误日志

2. **缓存问题**
   - 清理缓存：`config_loader.clear_cache()`
   - 检查缓存信息：`config_loader.get_cache_info()`

3. **迁移失败**
   - 检查文件格式
   - 确认数据库权限
   - 查看详细错误信息

### 调试模式

启用调试日志：

```python
import logging
logging.getLogger('agents.configuration').setLevel(logging.DEBUG)
```

## 扩展开发

### 添加新的配置类型

1. 在 `official_configs.py` 中定义新的配置类
2. 在 `config_loader.py` 中添加配置映射
3. 更新数据库模型（如需要）

### 自定义配置验证

```python
class CustomConfig(ConfigBase):
    def __post_init__(self):
        # 自定义验证逻辑
        if self.some_field < 0:
            raise ValueError("some_field must be positive")
```

## 最佳实践

1. **环境隔离**: 为不同环境使用不同的配置
2. **版本控制**: 使用语义化版本号
3. **默认配置**: 为每个配置类型提供合理的默认值
4. **文档化**: 为配置项添加详细的文档说明
5. **测试**: 为配置系统编写单元测试 