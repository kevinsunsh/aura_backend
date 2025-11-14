# Aura Backend 架构文档

本文档概述 `aura_backend` 的整体架构设计，以及核心模块的职责与实现要点。旨在帮助新成员快速了解系统运行流程，并为后续维护与扩展提供参考。

## 1. 总体架构概览

系统围绕「语音对话代理」构建，整体由以下几层组成：

- **接入层**：基于 FastAPI/uvicorn 暴露 HTTP 与 WebSocket 服务（`src/app.py`），负责协议握手、连接生命周期管理。
- **协议层**：`src/api_protocol` 定义了自研的二进制消息协议，支持事件枚举、序列化与压缩策略。
- **会话编排层**：`AuraAgent` 与 `ActorMessageProcessor` 负责将前端消息路由到各个能力模块（ASR/VAD/LLM/TTS/动作规划等），协调流程与资源。
- **多 Actor 推理管线**：采用 Pykka 实现的并行 Actor（`VADActor`、`E2EActor`、`LLMChatActor`、`LLMActionActor`、`TTSActor`、`PrePostActor`、`LoopActor`）处理不同模态与任务。
- **LangGraph 任务流**：`agents/graphs` 基于 LangGraph 构建长流程代理（观察、思考、行动、回复等）的有状态执行图。
- **记忆与数据层**：`agents/agent_memory` 管理数据库连接、Prompt 拼装、用户与世界建模、任务/记忆存储。
- **工具与资源层**：`agents/aura_tool`、`agents/doubao_client` 提供 VAD/ASR/TTS 模型封装，`data/` 下维护角色卡、世界书等静态资源。

系统核心数据存放在 PostgreSQL，上层通过 SQLAlchemy、Pydantic 以及自建的 DB 管理器封装。

## 2. 服务入口与协议

### 2.1 FastAPI 应用

- `src/app.py` 启动 FastAPI 实例，配置 CORS，并暴露 `/ws/stream` 等 WebSocket 端点。
- WebSocket 握手成功后交给 `AuraAgent` 进行自定义协议握手、会话初始化、连接关闭等。
- 日志系统使用 Loguru，根据 `tag` 进行着色与过滤，方便定位不同阶段的日志。

### 2.2 自定义二进制协议

- `api_protocol/constant.py` 中定义了消息头位宽、消息类型、序列化/压缩方式，以及客户端/服务端事件枚举。
- `api_protocol/server_protocol.py` 和 `client_protocol.py` 负责构造/解析二进制帧，实现统一的事件分发。
- 协议区分文本消息与音频二进制 payload，可插入 gzip 压缩。

## 3. 会话编排核心

### 3.1 `AuraAgent`

- 单例实现，接管 WebSocket 连接生命周期：等待 `StartConnection`、`StartSession`，进入主循环处理 `TaskRequest`、`SpeakEnded` 等事件。
- 与 `ChatStreamManager` 协作，基于 PostgreSQL 的 `chat_streams` 表加锁防止同一 `chat_id` 并发访问。
- 将解析后的事件转交 `ActorMessageProcessor`，并把各 Actor 的输出统一封装后发回客户端。

### 3.2 `ActorMessageProcessor`

- 初始化并管理所有 Pykka Actor，设置输出回调。
- 在 `start` 阶段从记忆层拉取用户、场景、角色、系统预设、世界信息，驱动 `PromptManager` 建立本轮上下文。
- 收到消息后，根据事件类型向不同 Actor 派发任务（音频分发到 VAD/E2E/Loop，控制消息转给 PrePost/Action 等）。
- 汇总各 Actor 回调，按协议输出到 WebSocket。
- `cleanup` 负责停止各 Actor 并释放资源。

## 4. 多 Actor 推理管线

| Actor | 主要职责 | 关键依赖 |
| --- | --- | --- |
| `VADActor` | 本地 VAD 推理，检测语音起止并发出 `ASRInfo`/`ASREnded` | `agents/aura_tool/vad_engine.py` |
| `E2EActor` | 调用字节豆包的端到端语音对话（同时产出 ASR/TTS/Chat 流） | `doubao_client.DialogSession` |
| `LLMChatActor` | 使用标签流解析器 `StreamingTagParser` 解析 LLM 流式输出，驱动 TTS、动作规划 | PromptManager、`get_chat_model_by_type("pfc_action_planner")` |
| `LLMActionActor` | 基于 LangGraph `action_agent_builder` 运行行动规划/执行图，产出 `ChatAction*` 事件 | LangGraph + PostgresSaver |
| `TTSActor` | 将文本片段转换为语音流，回调到客户端 | `doubao_client.tts_client` |
| `PrePostActor` | 在 VAD/ASR 结束后拼装 Prompt，生成 LLM 输入；在响应结束后做后处理、任务调度 | PromptManager、TaskManager |
| `LoopActor` | 周期性发送环境状态（场景物体、空间实体等） | Scene/Spatial DB 管理器 |

Actor 之间通过消息队列与回调解耦，实现语音输入 → VAD/ASR → Prompt 生成 → LLM 回复 → TTS/Action 的流水线，并支持中断与计时。

## 5. LangGraph 任务流

`agents/graphs` 目录基于 LangGraph 构建了多个有状态代理流程：

- `action_agent_graph.py`：核心驱动，协调观察 (`observing_graph`)、思考 (`thinking_graph`)、记忆 (`memorizing_graph`)、回忆 (`recalling_graph`)、回复 (`replying_graph`)、自言自语 (`muttering_graph`) 等子图。
- `speaking_graph.py`：处理主动说话任务，根据对话历史、目标、知识规划是否立即回复。
- 图节点通过 `StateGraph` 定义，`agents/states` 提供对应的 `TypedDict` 状态结构。
- `TaskManager` 与 LangGraph 的 checkpoint（PostgresSaver）结合，实现任务状态持久化、恢复与并行运行。

这些图利用 `langgraph` 的 `Command`、`interrupt` 等机制实现可暂停的多分支流程，结合记忆与外部检索数据生成最终动作或语言输出。

### 5.1 `action_agent_graph` 深入分析

`action_agent_graph.py` 是整个智能体调度枢纽，核心要点如下：

- **状态结构**：`agents/states/action_agent_state.py` 定义了多个 `TypedDict` 与 `Enum`，描述任务阶段（Observation/Thinking/Replying 等）、工作记忆、任务上下文、执行记录等。
- **流程编排**：
  1. **观察阶段**（`observing_graph`）：从 `MessageStore` 获取最新对话，汇总为结构化摘要；与 `LoopActor` 推送的环境态势结合生成观察结果。
  2. **思考阶段**（`thinking_graph`）：结合长期目标、世界知识、角色设定，生成新的对话目标、行动计划或知识补完需求。
  3. **记忆阶段**（`memorizing_graph`）：根据当前交互内容判断是否需要写入总结记忆或检索外部信息。
  4. **行动阶段**（`recalling_graph` + `replying_graph`）：如果需要执行实体动作、调用工具或返回文本回复，会进一步分支到相应子图。
  5. **耳语阶段**（`muttering_graph`）：在需要背景思考或沉浸式反馈时使用预置白噪/耳语音频填充。
- **任务状态管理**：通过 `TaskManager` 获取/更新任务状态（`TaskStateType`），确保同一时刻不会并行执行冲突的任务，并将共享数据写入 Postgres checkpoint，便于断点恢复。
- **指令交互**：节点之间以 `Command(goto=...)` 或 `Command(update=...)` 传递状态；若等待外部输入（如用户回复或动作完成），会触发 `interrupt(...)`。

### 5.2 `speaking_graph` 细节补充

`speaking_graph.py` 专注于“是否主动说话”决策，其流程：

1. `_plan_action`：聚合观察任务产生的聊天历史摘要、上次说话时间、用户沉默时长等，调用 `pfc_action_planner` 模型生成 JSON 格式的行动决策（`send_new_message`/`listening`/`wait`）。
2. `_execute_action`：根据决策切换到生成回复或继续监听。
3. `_generate_new_message`：若需要主动输出，则调用 `pfc_chat` 模型流式生成回复，并通过 `get_stream_writer()` 将文本增量写回前端；同时通知 `TaskManager` 停止冲突任务（如耳语）。
4. 整个流程受 `reply_max_latency` 控制，结合 `TaskManager` 的任务状态判断是否需要暂停或终止。

### 5.3 其他图谱

- `observing_graph.py`：以摄取输入为主，整合消息存档、世界状态、角色数据，输出用于决策的 `Observation`.
- `thinking_graph.py`：执行多轮推理与目标规划，可调用工具或进行知识检索。
- `replying_graph.py`：负责把回复指令转换成结构化消息，交由 `LLMChatActor` 与 `TTSActor` 流式反馈。
- `muttering_graph.py`：结合 `muttering_data` 中存档的音频片段，驱动耳语播放任务。

LangGraph 的子图之间通过共享状态 (`state["shared"]`) 互相传输上下文，并借助 `langgraph.checkpoint.postgres` 的自动 checkpoint 保证长流程鲁棒性。

## 6. 记忆与上下文管理

### 6.1 数据库封装

- `agents/agent_memory/database` 提供 `Database`、`DBManagerBase` 等基础设施，通过 `DatabaseConfigManager` 加载环境配置。
- 每类实体（用户、角色、场景、世界、任务、摘要记忆等）都实现了 `DBManager` 与 ORM `Model`，统一 CRUD。

### 6.2 Prompt 管理

- `prompt_manager/prompt_manager.py` 是 Prompt 生成的核心，整合用户画像、场景物品、世界知识、历史对话、系统预设等信息，通过宏替换和 token 预算管理构建 LLM 输入。
- `world_info/scanner.py` 根据激活关键词动态挑选世界知识；`scene_items`、`spatial_entity` 提供三维场景与导航数据。
- `system_preset`、`character`、`char_instance_info`、`scene_info` 等模块负责加载/落库对应配置。

### 6.3 记忆与任务

- `summary_mem`、`view_memory` 等模块维护长时记忆与可视化信息。
- `task` 模块定义任务模型与调度器（`TaskManager`），结合 LangGraph 流程实现任务排程、状态更新、回调执行。
- `message_store` 按轮存储用户与助手消息，用于后续 Prompt 与记忆聚合。

## 7. 外部能力封装

- `agents/doubao_client`：对接火山引擎豆包实时对话、ASR、TTS，提供统一回调接口。
- `agents/aura_tool`：本地推理工具（VAD/VAD Split），加载 ONNX 模型执行端侧推理。
- `utils.utils`：包含 `safe_call`、性能埋点、原子操作等工具函数。
- `muttering_data`：预置的耳语音频数据，供自言自语任务使用。

## 8. 配置与部署

- `src/config.py` 使用 Pydantic Settings 读取 `.env` 环境变量（API Key、PostgreSQL、日志目录等）。
- `deploy_scripts/`、`push_docker_image.sh`、`Dockerfile` 等提供多环境部署脚本（火山、腾讯等）。
- `tests/` 下包含基础网络、任务、音频端到端测试脚本。

## 9. 运行流程概述

1. 客户端建立 WebSocket → 发送 `StartConnection` → `AuraAgent` 回复 `ConnectionStarted`。
2. 客户端发送 `StartSession`（携带 `chat_id`/`user_id`）→ `ChatStreamManager` 上锁 → `ActorMessageProcessor.start` 初始化上下文与 Actor。
3. 音频帧通过 `TaskRequest` 事件进入 → `VADActor`/`E2EActor` 检测语音 → `PrePostActor` 触发 Prompt 生成 → `LLMChatActor` 流式生成文本。
4. `LLMChatActor` 的标签输出驱动 `LLMActionActor` 规划行动，或触发 `TTSActor` 返回语音。
5. LangGraph 子图根据消息和任务状态决定是否自言自语、记录记忆、调度动作。
6. 会话结束时客户端发送 `FinishSession` → 系统发送 `SessionFinished` 并清理 Actor、释放锁。

## 10. 模块间依赖关系

- `AuraAgent` ⇆ `ChatStreamManager`：确保会话唯一性与心跳。
- `ActorMessageProcessor` ⇄ 各 Actor：通过回调互相通知，串联语音、文本、动作链路。
- `PromptManager` ⇆ 各 DBManager：动态加载场景/角色/世界知识。
- `LangGraph` ⇆ `TaskManager`：任务调度、状态持久化与断点恢复。
- `doubao_client`/`aura_tool`：提供底层推理能力，上层 Actor 只关心高层接口。

## 11. 开发建议

- **资源管理**：Actor 与数据库连接需成对启停，避免线程/锁泄漏。
- **协议兼容**：新增事件时务必更新协议常量与解析器，保持前后端一致。
- **Prompt 扩展**：新增 Persona/世界信息时，记得更新对应 DB、Prompt 生成逻辑与宏替换。
- **LangGraph 任务**：引入新任务建议先在 `agents/states` 定义状态，再在对应 `graph` 中编排节点，并配置 Postgres checkpoint。
- **测试与监控**：使用 `utils.utils.start_performance_point` 进行性能埋点；`logs/main.log` 与 Loguru tag 有助于链路排查。

---  

如需更细粒度的数据库表设计、配置导入流程，可参考：

- `agents/agent_memory/README.md`
- `agents/agent_memory/configuration/DATABASE_TABLES.md`
- 各模块下的 `create_tables.py` 与 `manager.py`

欢迎在后续开发中补充时序图、数据流图等辅助说明。

