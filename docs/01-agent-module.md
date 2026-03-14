# Agent 模块 (nanobot/agent/)

代理模块是 nanobot 的大脑，实现了核心的 LLM ↔ 工具执行循环、内存管理、上下文构建和工具编排。

## 目录结构

```
nanobot/agent/
├── __init__.py        # 模块导出
├── loop.py            # 核心代理循环
├── context.py         # 系统提示和消息上下文构建器
├── memory.py          # 两层内存系统 (MEMORY.md + HISTORY.md)
├── skills.py          # 技能加载器
├── subagent.py        # 后台任务执行管理器
└── tools/             # 内置工具
    ├── __init__.py
    ├── base.py        # 工具基类
    ├── registry.py    # 工具注册表
    ├── filesystem.py  # 文件系统工具
    ├── shell.py       # Shell 执行工具
    ├── web.py         # Web 搜索和获取工具
    ├── message.py     # 消息发送工具
    ├── spawn.py       # 子代理生成工具
    ├── cron.py        # 定时任务工具
    └── mcp.py         # MCP 客户端包装器
```

---

## 1. loop.py - 核心代理循环

### 职责

`AgentLoop` 类是中央处理引擎，负责：
1. 从消息总线消费消息
2. 构建上下文（历史、内存、技能）
3. 调用 LLM 并传递工具定义
4. 执行工具调用（循环）
5. 发送响应回消息总线
6. 处理斜杠命令 (`/new`, `/stop`, `/restart`, `/help`)
7. 管理内存整合

### 类签名

```python
class AgentLoop:
    """代理循环是核心处理引擎。"""
    
    _TOOL_RESULT_MAX_CHARS = 16_000
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    )
```

### 关键方法

| 方法 | 描述 |
|------|------|
| `async def run(self) -> None` | 主事件循环，消费入站消息 |
| `async def _run_agent_loop(...) -> tuple[str \| None, list[str], list[dict]]` | 核心迭代循环 |
| `async def _process_message(...) -> OutboundMessage \| None` | 处理单条消息 |
| `def _register_default_tools(self) -> None` | 注册所有内置工具 |
| `async def _connect_mcp(self) -> None` | 懒加载 MCP 服务器连接 |
| `async def process_direct(...) -> str` | 直接处理消息（用于 CLI 或 cron） |

### 重要设计模式

1. **异步任务分发**: 消息作为异步任务在锁下分发，保持对 `/stop` 的响应性
2. **工具结果截断**: 大型工具结果在会话存储前截断到 16KB
3. **错误响应过滤**: LLM 的错误响应不持久化，防止上下文污染
4. **进度流式传输**: 工具调用提示通过 `on_progress` 回调流式传输
5. **思考块剥离**: 从某些模型输出中移除 `<think)>` 标签

### 依赖关系

- `ContextBuilder` (context.py) - 提示构建
- `MemoryConsolidator` (memory.py) - 基于 Token 的内存整合
- `SubagentManager` (subagent.py) - 后台任务执行
- `ToolRegistry` (tools/registry.py) - 工具管理
- `MessageBus` (bus/queue.py) - 消息传输
- `LLMProvider` (providers/base.py) - LLM 抽象
- `SessionManager` (session/manager.py) - 会话存储

---

## 2. context.py - 上下文构建器

### 职责

`ContextBuilder` 为每次 LLM 调用构建系统提示和消息列表，组合：
- 核心身份和运行时信息
- 引导文件 (AGENTS.md, SOUL.md, USER.md, TOOLS.md)
- 来自 MEMORY.md 的长期内存
- 始终激活的技能
- 技能摘要（用于渐进式加载）
- 运行时元数据（时间、通道、chat_id）

### 类签名

```python
class ContextBuilder:
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[RUNTIME_CONTEXT]"
    
    def __init__(self, workspace: Path)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]
    
    def add_tool_result(...) -> list[dict]
    def add_assistant_message(...) -> list[dict]
```

### 关键设计模式

1. **运行时上下文标记**: 使用特殊标签标记仅元数据部分以便过滤
2. **平台特定策略**: 为 Windows vs POSIX 系统提供不同指导
3. **多模态支持**: 将图像转换为带 MIME 类型检测的 base64
4. **消息合并**: 将运行时上下文与用户内容合并，避免连续同角色消息

---

## 3. memory.py - 持久化内存系统

### 职责

两层内存系统，带自动整合：
1. **MEMORY.md**: 长期事实，由 LLM 摘要更新
2. **HISTORY.md**: 可 grep 搜索的带时间戳日志
3. **基于 Token 的整合**: 当上下文增长时自动归档旧消息

### 类签名

```python
class MemoryStore:
    """管理 MEMORY.md 和 HISTORY.md 文件"""
    
    def __init__(self, workspace: Path)
    def read_long_term(self) -> str
    def write_long_term(self, content: str) -> None
    def append_history(self, entry: str) -> None
    def get_memory_context(self) -> str
    async def consolidate(messages, provider, model) -> bool


class MemoryConsolidator:
    """拥有整合策略和锁"""
    
    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable,
        get_tool_definitions: Callable,
    )
    
    async def maybe_consolidate_by_tokens(self, session: Session) -> None
    async def archive_unconsolidated(self, session: Session) -> bool
    def pick_consolidation_boundary(...) -> tuple[int, int] | None
    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]
```

### 关键设计模式

1. **WeakRef 锁**: 防止会话键锁的内存泄漏
2. **用户轮次边界**: 在用户消息处整合以保持对话流程
3. **强制工具选择**: 尝试强制 tool_choice，出错时回退到 auto
4. **原始归档回退**: 重复 LLM 失败后的降级模式
5. **Token 估算**: 使用提供者特定的 Token 估算进行上下文大小计算

---

## 4. skills.py - 技能加载器

### 职责

从 markdown 文件 (SKILL.md) 加载代理能力：
1. 工作区技能目录 (`workspace/skills/`) - 最高优先级
2. 内置技能目录 (`nanobot/skills/`) - 回退

### 类签名

```python
class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None)
    
    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]
    def load_skill(self, name: str) -> str | None
    def load_skills_for_context(self, skill_names: list[str]) -> str
    def build_skills_summary(self) -> str
    def get_always_skills(self) -> list[str]
    def get_skill_metadata(self, name: str) -> dict | None
```

### Frontmatter 格式

```yaml
---
description: "技能描述"
always: true  # 始终加载到上下文
metadata: {"nanobot":{"requires":{"bins":["git"],"env":["API_KEY"]}}}
---
# 技能内容
```

### 关键设计模式

1. **渐进式加载**: 技能摘要在系统提示中，完整内容按需通过 read_file
2. **可用性过滤**: 隐藏依赖未满足的技能（缺少二进制、环境变量）
3. **始终技能**: 标记为 `always: true` 的技能加载到每个提示
4. **优先级系统**: 工作区技能覆盖内置技能

---

## 5. subagent.py - 后台任务执行

### 职责

`SubagentManager` 为后台任务生成隔离的代理实例：
- 独立运行任务而不阻塞主代理
- 通过系统消息将结果报告回主代理
- 限制 15 次迭代以专注执行
- 有自己的工具集（文件系统、exec、web - 无 message/spawn/cron）

### 类签名

```python
class SubagentManager:
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        restrict_to_workspace: bool = False,
    )
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str
    
    async def cancel_by_session(self, session_key: str) -> int
    def get_running_count(self) -> int
```

### 关键设计模式

1. **任务生命周期管理**: 按 session_key 跟踪任务以便批量取消
2. **结果广播**: 将结果作为系统消息发送以触发主代理
3. **隔离工具集**: 子代理不能发送消息或生成更多子代理（防止递归）
4. **UUID ID**: 缩短的 UUID 用于任务标识

---

## 6. tools/ - 内置工具

### base.py - 工具基类

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def description(self) -> str: ...
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str: ...
    
    def cast_params(self, params: dict) -> dict
    def validate_params(self, params: dict) -> list[str]
    def to_schema(self) -> dict[str, Any]
```

**特性**:
- JSON Schema 验证
- 类型转换（string → int/bool/number）
- 自动 OpenAI 函数 Schema 转换

### registry.py - 工具注册表

```python
class ToolRegistry:
    def __init__(self)
    def register(self, tool: Tool) -> None
    def unregister(self, name: str) -> None
    def get(self, name: str) -> Tool | None
    def get_definitions(self) -> list[dict[str, Any]]
    async def execute(self, name: str, params: dict[str, Any]) -> str
```

### filesystem.py - 文件系统工具

| 工具 | 参数 | 描述 |
|------|------|------|
| `read_file` | path, offset, limit | 读取文件内容（分页） |
| `write_file` | path, content | 写入文件（自动创建父目录） |
| `edit_file` | path, old_text, new_text, replace_all | 替换文件中的文本 |
| `list_dir` | path, recursive, max_entries | 列出目录内容 |

**特性**:
- 相对于工作区的路径解析
- 可选的目录限制（安全）
- 跨平台路径处理

### shell.py - Shell 执行

```python
class ExecTool(Tool):
    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str
```

**安全防护**:
- 阻止危险命令：`rm -rf`, `del /f`, `format`, `mkfs`, `dd`, `shutdown`, fork 炸弹
- 可选工作区限制
- 最大超时：600 秒
- 最大输出：10KB

### web.py - Web 工具

| 工具 | 描述 |
|------|------|
| `web_search` | 搜索提供商：brave, tavily, jina, searxng, duckduckgo |
| `web_fetch` | 获取 URL 内容（Jina Reader API 或 readability-lxml） |

**特性**:
- 缺少凭据时自动回退到 DuckDuckGo
- HTML 标签剥离和规范化
- 可选代理支持

### message.py - 消息工具

```python
class MessageTool(Tool):
    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
    ) -> str
```

**特性**:
- 上下文感知（默认为当前通道/聊天）
- 媒体附件支持
- 跟踪每轮发送的消息（抑制最终响应）

### spawn.py - 子代理工具

```python
class SpawnTool(Tool):
    async def execute(self, task: str, label: str | None = None) -> str
```

### cron.py - 定时任务工具

```python
class CronTool(Tool):
    async def execute(
        self,
        action: str,  # "add", "list", "remove"
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
    ) -> str
```

### mcp.py - MCP 客户端

```python
async def connect_mcp_servers(
    mcp_servers: dict,
    registry: ToolRegistry,
    stack: AsyncExitStack,
) -> None
```

**传输模式**:
- **stdio**: 通过 command/args 的本地进程
- **sse**: Server-Sent Events (URL 以 /sse 结尾)
- **streamableHttp**: HTTP 流（非 /sse URL 的默认值）

**特性**:
- 懒加载连接（首次消息）
- 自动工具发现和注册
- 名称前缀：`mcp_{server_name}_`
- 可配置超时
- `enabledTools` 过滤器支持

---

## 模块间关系图

```
                    ┌─────────────┐
                    │ MessageBus  │
                    └──────┬──────┘
                           │
           ┌───────────────▼───────────────┐
           │       AgentLoop               │
           │  - 消费入站消息               │
           │  - 分发任务                   │
           │  - 调用 LLM + 工具            │
           └───────┬───────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
     ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Context  │ │  Memory  │ │  Subagent    │
│ Builder  │ │Consolid. │ │  Manager     │
└────┬─────┘ └────┬─────┘ └──────┬───────┘
     │            │               │
     ▼            ▼               ▼
┌─────────────┐ ┌──────────────┐  ┌─────────────┐
│ SkillsLoader│ │SessionManager│  │ToolRegistry │
└─────────────┘ └──────────────┘  └──────┬──────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
            │ filesystem  │   │   shell     │   │     web     │
            │ tools       │   │   tool      │   │   tools     │
            └─────────────┘   └─────────────┘   └─────────────┘
                    │                 │                 │
                    └─────────────────┴─────────────────┘
                                      │
                                      ▼
                            ┌─────────────────┐
                            │   Tool (base)   │
                            └─────────────────┘
```

---

## 关键数据流

1. 入站消息 → `AgentLoop._dispatch()`
2. 构建上下文: `ContextBuilder.build_messages()` + 会话历史
3. 调用 LLM: `provider.chat_with_retry()` 带工具定义
4. 执行工具: `ToolRegistry.execute()` → 各个 `Tool.execute()`
5. 整合内存: `MemoryConsolidator.maybe_consolidate_by_tokens()`
6. 保存会话: `SessionManager.save()`
7. 发送响应: `MessageBus.publish_outbound()`
