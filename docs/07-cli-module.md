# CLI 模块 (nanobot/cli/)

CLI 模块是 nanobot 的**编排层**，负责解析用户命令、加载配置、初始化代理循环和相关服务、管理交互式 I/O，并协调消息流。

## 目录结构

```
nanobot/cli/
├── __init__.py    # 模块初始化（最小）
└── commands.py    # 核心 CLI 命令实现

nanobot/
└── __main__.py    # 模块执行入口点
```

---

## 1. __main__.py - 入口点

```python
from nanobot.cli.commands import app

if __name__ == "__main__":
    app()
```

**职责**: 当作为模块执行时 (`python -m nanobot`)，导入 Typer app 并调用它。

---

## 2. commands.py - CLI 命令

### 全局选项

```bash
--version, -v    # 显示版本（急切回调）
```

### 2.1 `nanobot onboard`

**目的**: 初始化 nanobot 配置和工作区。

**选项**: 无

**执行操作**:
- 在 `~/.nanobot/config.json` 创建配置
- 创建工作区目录
- 同步工作区模板
- 载入插件（通道）
- 如果配置存在，提示覆盖或刷新

**内部操作**:
```python
save_config(Config())  # 新配置
_onboard_plugins()     # 注入通道默认值
sync_workspace_templates()  # 模板
```

---

### 2.2 `nanobot gateway`

**目的**: 启动 nanobot 网关服务器（用于通道集成）。

**选项**:
```bash
--port, -p       # 网关端口（默认: 从 config.gateway.port）
--workspace, -w  # 工作区目录覆盖
--verbose, -v    # 启用详细日志
--config, -c     # 配置文件路径
```

**初始化组件**:
- `MessageBus()` - 消息路由
- `AgentLoop` - 核心代理逻辑
- `SessionManager` - 会话持久化
- `CronService` - 定时任务执行
- `HeartbeatService` - 周期任务执行
- `ChannelManager` - 所有启用的通道

**入口点流程**:
```
gateway 命令
  → _load_runtime_config()
  → _make_provider()
  → 创建 AgentLoop, CronService, HeartbeatService, ChannelManager
  → 设置 cron 回调 (on_cron_job)
  → 设置 heartbeat 回调 (on_heartbeat_execute, on_heartbeat_notify)
  → asyncio.run() with cron.start(), heartbeat.start(), agent.run(), channels.start_all()
```

---

### 2.3 `nanobot agent`

**目的**: 直接通过 CLI 与代理交互。

**选项**:
```bash
--message, -m     # 要发送的单条消息（非交互）
--session, -s     # 会话 ID（默认: "cli:direct"）
--workspace, -w   # 工作区目录覆盖
--config, -c      # 配置文件路径
--markdown        # 将输出渲染为 Markdown（默认: True）
--no-markdown     # 渲染为纯文本
--logs            # 聊天期间显示运行时日志
--no-logs         # 隐藏运行时日志
```

**两种模式**:

**A. 单消息模式** (`--message`):
```bash
nanobot agent -m "Hello!"
```
- 直接调用 `agent.process_direct()`
- 不需要总线
- 响应后退出

**B. 交互模式** (无 `--message`):
```bash
nanobot agent
```
- 使用 `prompt_toolkit` 进行输入（历史、编辑、粘贴支持）
- 通过 `MessageBus` 路由消息
- 在后台运行代理循环
- 退出条件: `exit`, `quit`, `/exit`, `/quit`, `:q`, `Ctrl+C`, `Ctrl+D`

**入口点流程**:
```
agent 命令
  → _load_runtime_config()
  → _make_provider()
  → 创建 AgentLoop, CronService
  → 如果 --message:
      → agent.process_direct() → 打印响应 → 退出
  → 否则 (交互式):
      → _init_prompt_session()
      → 设置信号处理器 (SIGINT, SIGTERM, SIGHUP, SIGPIPE)
      → 在后台运行 agent_loop.run()
      → 读取输入 → publish_inbound() → consume_outbound() → 显示
```

---

### 2.4 `nanobot channels` (子命令组)

#### 2.4a `nanobot channels status`

**目的**: 显示所有通道的状态。

**执行操作**:
- 列出所有发现的通道（内置 + 插件）
- 显示启用/禁用状态
- 使用 Rich 表格显示

#### 2.4b `nanobot channels login`

**目的**: 通过 QR 码链接 WhatsApp 设备。

**执行操作**:
- 如果未构建，设置 Node.js 桥接
- 将桥接从包复制到 `~/.nanobot/bridge`
- 运行 `npm install` 和 `npm run build`
- 使用 `npm start` 启动桥接
- 显示 QR 码供扫描

---

### 2.5 `nanobot plugins` (子命令组)

#### 2.5a `nanobot plugins list`

**目的**: 列出所有发现的通道（内置和插件）。

**执行操作**:
- 区分内置和插件通道
- 显示启用状态
- 使用 Rich 表格显示

---

### 2.6 `nanobot status`

**目的**: 显示 nanobot 状态。

**执行操作**:
- 显示配置文件路径和存在性
- 显示工作区路径和存在性
- 显示模型设置
- 显示提供者状态和 API keys（掩码或 ✓）

---

### 2.7 `nanobot provider` (子命令组)

#### 2.7a `nanobot provider login <provider>`

**目的**: 使用 OAuth 提供者进行认证。

**选项**:
```bash
provider    # OAuth 提供者名（如 "openai-codex", "github-copilot"）
```

**支持的提供者**:
- `openai-codex` — 使用 `oauth-cli-kit` 进行交互式 OAuth 流
- `github-copilot` — 使用 LiteLLM 设备流

---

## 3. 辅助函数

### 终端管理
- `_flush_pending_tty_input()` - 在生成期间丢弃未读按键
- `_restore_terminal()` - 退出时恢复终端状态
- `_init_prompt_session()` - 创建带文件历史的 prompt_toolkit 会话

### 交互式 I/O
- `_read_interactive_input_async()` - 使用 prompt_toolkit 读取用户输入
- `_print_agent_response()` - 打印非交互式响应
- `_print_interactive_line()` - 打印异步进度更新
- `_print_interactive_response()` - 打印异步交互式回复
- `_render_interactive_ansi()` - 将 Rich 输出渲染为 ANSI

### 配置 & 提供者
- `_load_runtime_config(config, workspace)` - 加载带可选覆盖的配置
- `_make_provider(config)` - 从配置创建 LLM 提供者
- `_print_deprecated_memory_window_notice()` - 警告已弃用的配置

### 载入
- `_onboard_plugins(config_path)` - 为所有发现的通道注入默认配置
- `_merge_missing_defaults(existing, defaults)` - 递归合并默认值而不覆盖

### 通道管理
- `_get_bridge_dir()` - 获取/设置 WhatsApp 桥接目录
- `_pick_heartbeat_target()` - 为 heartbeat 消息选择通道/聊天目标

---

## 4. 模块交互

### commands.py 导入自:

**nanobot.config**:
- `paths` → `get_workspace_path`, `get_config_path`, `get_cli_history_path`, `get_cron_dir`, `get_bridge_install_dir`, `get_runtime_subdir`
- `schema` → `Config`
- `loader` → `load_config`, `save_config`, `set_config_path`

**nanobot.agent**:
- `loop` → `AgentLoop`

**nanobot.channels**:
- `manager` → `ChannelManager`
- `registry` → `discover_all`, `discover_channel_names`

**nanobot.bus**:
- `queue` → `MessageBus`
- `events` → `InboundMessage`, `OutboundMessage`

**nanobot.cron**:
- `service` → `CronService`
- `types` → `CronJob`

**nanobot.heartbeat**:
- `service` → `HeartbeatService`

**nanobot.session**:
- `manager` → `SessionManager`

**nanobot.providers**:
- `base` → `GenerationSettings`
- `openai_codex_provider` → `OpenAICodexProvider`
- `azure_openai_provider` → `AzureOpenAIProvider`
- `custom_provider` → `CustomProvider`
- `litellm_provider` → `LiteLLMProvider`
- `registry` → `PROVIDERS`, `find_by_name`

**nanobot.utils**:
- `helpers` → `sync_workspace_templates`
- `evaluator` → `evaluate_response`

**外部库**:
- `typer` - CLI 框架
- `rich` - 终端格式化（Console, Markdown, Table, Text）
- `prompt_toolkit` - 交互式输入（PromptSession, FileHistory, ANSI, HTML）

---

## 5. 架构摘要

CLI 模块作为**编排层**，负责:
1. 解析用户命令和选项 (Typer)
2. 加载配置并创建提供者
3. 初始化代理循环和相关服务
4. 使用 prompt_toolkit 管理交互式 I/O
5. 通过 MessageBus 协调消息流
6. 使用 Rich 格式化渲染输出
7. 处理终端状态和信号以实现优雅关闭

CLI **不是核心逻辑** — 它是:
- 使用正确配置初始化 `AgentLoop` 的接口
- 启动后台服务（cron, heartbeat, channels）
- 提供用户友好的输入/输出处理
- 将实际代理工作委托给 `nanobot/agent/` 模块
