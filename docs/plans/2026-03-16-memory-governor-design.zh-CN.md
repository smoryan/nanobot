# Memory Governor 设计文档

## 概览

本设计的目标是把 memory 治理能力从主代理循环中剥离，迁移到一个专用、默认异步运行的
`memory-agent`，同时保留当前轻量、grep-first、基于文件的 memory 模型。

最终控制流如下：

`conversation -> memory event -> memory-agent -> _MEMBEAT_TOOL actions -> file materialization`

主代理继续保留对 `memory/MEMORY.md` 的读取路径，从而保证 prompt 构建逻辑简单、稳定、可预期。
记忆写入路径和治理路径则转交给 `memory-agent`，由它统一负责打标签、整合、历史压缩以及 TODO 发射。

## 目标

- 引入结构化标签头，使用非 Markdown 原生起始标记：`[%key:value]`
- 引入 governor-style 的 `memory-agent`，默认异步运行
- 使用 `_MEMBEAT_TOOL` 作为 memory 决策的受控动作协议
- 引入 `TODO.md` 和 `todo_tools`，作为独立的任务投影视图
- 保持 memory 系统可审计、便于 grep 搜索，并继续以文件为核心

## 非目标

- 不引入向量数据库或重型 RAG 管线
- 不修改主代理直接读取 `memory/MEMORY.md` 的路径
- 第一阶段不重做 session 模型
- 不允许模型自由重写文件

## 架构

### Main Agent

- 和现在一样，把 `memory/MEMORY.md` 读入上下文
- 不再直接承担 memory 更新治理和最终落盘职责
- 在一次对话轮次完成后，发出一个 `memory event`

### Memory Agent

- 作为 memory 管理的唯一 governor
- 异步消费 memory events
- 解读最近的会话状态，并决定是否需要持久化内容
- 调用 `_MEMBEAT_TOOL` 获取受约束的动作列表
- 将批准后的动作交给确定性的 materializers 执行

### _MEMBEAT_TOOL

- 只返回结构化的 memory actions
- 不直接编辑文件
- 负责划清“memory 解释决策”和“文件写入执行”的边界

### Materializers

- 将 `append_history` 动作持久化到 `memory/HISTORY.md`
- 将 `upsert_memory` 动作持久化到 `memory/MEMORY.md`
- 将 `emit_todo` 动作通过 `todo_tools` 投影到 `TODO.md`

## 文件格式

### memory/HISTORY.md

采用带标签块的追加式事件日志。

示例：

```md
[2026-03-15 12:30]
[%type: decision]
[%tags: project,todo,constraint]
[%source: cli:alice]
[%importance: high]

User decided to introduce tagged memory and an async memory-agent.
```

格式规则：

- 第一行继续保留现有时间锚点：`[YYYY-MM-DD HH:MM]`
- 元数据头使用 `[%key:value]`
- 元数据与正文之间保留一个空行
- 正文保持自然语言，可直接供人阅读
- `HISTORY.md` 在正常模式下保持 append-only

### memory/MEMORY.md

保存整合后的长期事实，同样使用人可读的 `[%...]` 头部块表示。它应偏向稳定事实，避免退化为事件流水账。

示例：

```md
## Project Context

[%type: project]
[%tags: project,constraint]
[%source: history:2026-03-15T12:30]
[%importance: high]

The system should use a governor-style memory-agent and keep the main agent on the read path only.
```

### TODO.md

工作区任务文件，采用固定分区和固定条目语义。

分区：

- `## Active`
- `## Waiting on User`
- `## Completed`

每一条任务都必须带有：

- checkbox 状态
- 执行者类型：`Agent` 或 `User`
- user object
- 标准化后的任务文本
- 可选的 source memory 引用

示例格式：

```md
## Active

- [ ] [Agent] [user:alice] Draft memory-agent implementation plan [source:history:2026-03-15T12:30]

## Waiting on User

- [ ] [User] [user:alice] Review memory governor design draft

## Completed

- [x] [Agent] [user:alice] Approve memory governor architecture
```

## 标签模型

第一阶段的标签枚举：

- `profile`
- `preference`
- `project`
- `decision`
- `constraint`
- `todo`

设计说明：

- 标签表达的是语义类别，而不是存储目标
- `todo` 表示这段 memory 内容应该被投影进 TODO 系统
- 单个块可以通过 `[%tags:...]` 同时拥有多个标签

## Memory Event Schema

主代理在一次对话轮次结束后发出一个轻量级 event。

必填字段：

- `session_key`
- `message_range`
- `trigger`
- `origin`
- `timestamp`

可选字段：

- `context_excerpt`
- `message_ids`
- `channel`
- `chat_id`

这个 event 不是最终的 memory 写入请求，它只是 `memory-agent` 做治理判断的输入信号。

## _MEMBEAT_TOOL Action Schema

v1 允许的动作：

- `append_history`
- `upsert_memory`
- `emit_todo`
- `noop`

### append_history

用途：

- 向 `memory/HISTORY.md` 追加一个带标签的事件块

必填载荷：

- stable action id
- timestamp
- type
- tags
- source
- importance
- body

### upsert_memory

用途：

- 将稳定事实合并写入 `memory/MEMORY.md`

必填载荷：

- stable action id
- merge key
- type
- tags
- source reference
- importance
- body

### emit_todo

用途：

- 通过 `todo_tools` 创建或更新标准化的 TODO 项

必填载荷：

- stable action id
- dedupe key
- executor type
- user object
- task text
- source reference

### noop

用途：

- 明确表示当前 event 不需要沉淀任何 memory 持久化内容

## TODO 系统

`TODO.md` 是一层 projection，不是 memory 的源数据。memory 的源头仍然是 conversation 本身以及落盘后的 memory 文件。

规则：

- `main agent` 不直接维护 `TODO.md`
- `memory-agent` 通过 `emit_todo` 发射任务意图
- `todo_tools` 负责对 `TODO.md` 进行确定性更新
- 用户任务和 agent 任务共用一个文件，但必须保留明确的执行者标识

## todo_tools 最小 API

v1 最小 API：

- `add_todo`
- `update_todo`
- `complete_todo`
- `move_todo`
- `list_todos`

v1 明确不做：

- freeform rewrite
- bulk arbitrary replacement
- 模型直接自由编辑 markdown

## 执行流程

1. 主对话轮次完成。
2. 主代理先保存正常的 session history。
3. 主代理异步发出一个 `memory event`。
4. `memory-agent` 接收事件，并加载所需的上下文切片。
5. `memory-agent` 调用 `_MEMBEAT_TOOL`。
6. `_MEMBEAT_TOOL` 返回受约束的 actions。
7. 确定性的 materializers 将内容写入 `HISTORY.md`、`MEMORY.md` 和 `TODO.md`。
8. 即使失败，也通过重试处理，不阻塞主对话链路。

## 安全性与不变量

- 新设计下，main agent 不再直接承担 memory 写入治理
- `_MEMBEAT_TOOL` 永远不直接写文件
- 文件写入必须是确定性的、可审计的
- 重放同一个 memory event 时必须保证幂等
- `emit_todo` 动作必须可去重
- `HISTORY.md` 必须继续保持 grep-friendly 与 append-oriented
- `MEMORY.md` 必须在没有辅助工具的情况下也能被人直接阅读

## 分阶段落地计划

### Phase 1

- 定义 `[%key:value]` 标签块格式
- 增加 memory event 发射机制
- 引入 `_MEMBEAT_TOOL`
- 实现 `append_history` 与 `upsert_memory`

### Phase 2

- 增加 `emit_todo`
- 引入 `TODO.md`
- 引入 `todo_tools`

### Phase 3

- 增加 memory-agent 专属 skill/tools/scripts
- 增加用户可显式调用的 memory 命令
- 继续完善压缩、去重、优先级治理

## 待确认问题

- `MEMORY.md` 的 merge key 粒度应该如何定义？
- `emit_todo` 应使用什么样的 dedupe key？
- memory events 应该按时间窗口批处理、按数量批处理，还是两者结合？
- subagent 的输出应在什么时机被纳入 memory governance？
- `MEMORY.md` 是否继续保留分类 headings，还是最终完全过渡到 tagged blocks？

## 建议

建议将该系统实现为 governor-style 的 memory 架构：

- main agent 保持简单、专注读取
- memory-agent 成为唯一的治理边界
- `_MEMBEAT_TOOL` 将模型输出标准化为安全动作
- file materializers 保持整个系统透明、可审阅、可追踪

这样既保留了 nanobot 轻量、file-first 的哲学，也为 memory tagging、异步 consolidation 和 TODO projection 提供了清晰的演进路径。
