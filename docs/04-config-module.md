# Config 模块 (nanobot/config/)

配置模块负责 nanobot 中的所有配置管理。它处理配置 Schema 定义、加载/保存配置文件、运行时路径解析和多实例支持。

## 目录结构

```
nanobot/config/
├── __init__.py    # 公共 API 导出
├── schema.py      # Pydantic 配置 Schema
├── loader.py      # 配置加载/保存/迁移
└── paths.py       # 路径解析函数
```

---

## 1. schema.py - 配置 Schema

### 职责

使用 Pydantic 定义所有配置 Schema 和提供者匹配逻辑。这是配置结构的单一数据源。

### 配置 Schema

#### Base (BaseModel)

```python
class Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
```

**目的**: 接受 camelCase 和 snake_case 键的基类。

#### ChannelsConfig

```python
class ChannelsConfig(Base):
    send_progress: bool = True      # 流式代理文本进度到通道
    send_tool_hints: bool = False   # 流式工具调用提示
    
    # extra="allow" - 允许额外的通道特定字段作为字典
```

**通道特定配置** (作为额外字段添加):
- `telegram`, `discord`, `whatsapp`, `feishu`, `mochat`, `dingtalk`, `slack`, `email`, `qq`, `matrix`, `wecom`

#### AgentDefaults

```python
class AgentDefaults(Base):
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str = "auto"
    max_tokens: int = 8192
    context_window_tokens: int = 65536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int | None = None  # 已弃用
    reasoning_effort: str | None = None  # "low"/"medium"/"high"
```

#### ProviderConfig

```python
class ProviderConfig(Base):
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None
```

#### ProvidersConfig

```python
class ProvidersConfig(Base):
    custom: ProviderConfig = ProviderConfig()
    azure_openai: ProviderConfig = ProviderConfig()
    anthropic: ProviderConfig = ProviderConfig()
    openai: ProviderConfig = ProviderConfig()
    openrouter: ProviderConfig = ProviderConfig()
    # ... 20+ 提供者
```

#### HeartbeatConfig

```python
class HeartbeatConfig(Base):
    enabled: bool = True
    interval_s: int = 1800  # 30 分钟
```

#### GatewayConfig

```python
class GatewayConfig(Base):
    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = HeartbeatConfig()
```

#### WebSearchConfig

```python
class WebSearchConfig(Base):
    provider: str = "brave"  # brave, tavily, duckduckgo, searxng, jina
    api_key: str = ""
    base_url: str = ""       # 用于 SearXNG
    max_results: int = 5     # 1-10
```

#### MCPServerConfig

```python
class MCPServerConfig(Base):
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""        # stdio: 要运行的命令
    args: list[str] = []     # stdio: 命令参数
    env: dict[str, str] = {} # stdio: 额外环境变量
    url: str = ""            # HTTP/SSE: 端点 URL
    headers: dict[str, str] = {}  # HTTP/SSE: 自定义头
    tool_timeout: int = 30   # 工具调用取消前的秒数
    enabled_tools: list[str] = ["*"]  # 要注册的工具
```

#### ToolsConfig

```python
class ToolsConfig(Base):
    web: WebToolsConfig = WebToolsConfig()
    exec: ExecToolConfig = ExecToolConfig()
    restrict_to_workspace: bool = False  # 限制工具访问到工作区
    mcp_servers: dict[str, MCPServerConfig] = {}
```

#### Config (根配置)

```python
class Config(BaseSettings):
    agents: AgentsConfig = AgentsConfig()
    channels: ChannelsConfig = ChannelsConfig()
    providers: ProvidersConfig = ProvidersConfig()
    gateway: GatewayConfig = GatewayConfig()
    tools: ToolsConfig = ToolsConfig()
    
    @property
    def workspace_path(self) -> Path: ...
    
    def _match_provider(self, model: str | None = None) -> tuple[ProviderConfig | None, str | None]: ...
    def get_provider(self, model: str | None = None) -> ProviderConfig | None: ...
    def get_provider_name(self, model: str | None = None) -> str | None: ...
    def get_api_key(self, model: str | None = None) -> str | None: ...
    def get_api_base(self, model: str | None = None) -> str | None: ...
```

**环境变量支持**:
- 前缀: `NANOBOT_`
- 嵌套分隔符: `__`
- 示例: `NANOBOT__AGENTS__DEFAULTS__MODEL="anthropic/claude-opus-4-5"`

### 提供者匹配逻辑

1. **强制提供者**: 如果 `provider != "auto"`，直接使用该提供者
2. **显式前缀匹配**: 模型以提供者名开头（如 `deepseek/*` → deepseek）
3. **关键词匹配**: 模型名包含提供者关键词（从注册表）
4. **本地回退**: 通过 `api_base` 匹配本地提供者（如 Ollama 的 `11434`）
5. **网关回退**: 第一个有 API key 的可用网关

---

## 2. loader.py - 配置加载器

### 职责

处理从 JSON 加载、保存和迁移配置文件。支持多实例配置。

### 函数

```python
def set_config_path(path: Path) -> None
    # 全局设置当前配置路径（用于多实例支持）

def get_config_path() -> Path
    # 获取配置文件路径
    # 返回 _current_config_path 或默认 ~/.nanobot/config.json

def load_config(config_path: Path | None = None) -> Config
    # 从文件加载配置或创建默认配置
    # 1. 解析路径
    # 2. 如果文件存在: 加载 JSON → 应用迁移 → 验证
    # 3. 错误时返回默认 Config()

def save_config(config: Config, config_path: Path | None = None) -> None
    # 保存配置到文件
    # 使用 model_dump(by_alias=True) 获取 camelCase 键

def _migrate_config(data: dict) -> dict
    # 迁移旧配置格式到当前 Schema
    # 当前迁移: tools.exec.restrictToWorkspace → tools.restrictToWorkspace
```

---

## 3. paths.py - 路径解析

### 职责

解析 nanobot 的所有运行时路径，支持多实例隔离。路径从活动配置上下文派生。

### 函数

```python
def get_data_dir() -> Path
    # 返回实例级运行时数据目录
    # 返回 config_file.parent（包含 config.json 的目录）

def get_runtime_subdir(name: str) -> Path
    # 返回实例数据目录下的命名运行时子目录
    # 示例: get_runtime_subdir("cron") → ~/.nanobot/cron

def get_media_dir(channel: str | None = None) -> Path
    # 返回媒体目录，可选按通道命名空间
    # 示例: get_media_dir("telegram") → ~/.nanobot/media/telegram

def get_cron_dir() -> Path
    # 返回 cron 存储目录

def get_logs_dir() -> Path
    # 返回日志目录

def get_workspace_path(workspace: str | None = None) -> Path
    # 解析并确保代理工作区路径

def get_cli_history_path() -> Path
    # 返回共享 CLI 历史文件路径（全局）

def get_bridge_install_dir() -> Path
    # 返回共享 WhatsApp 桥接安装目录（全局）

def get_legacy_sessions_dir() -> Path
    # 返回用于迁移回退的旧全局会话目录
```

### 路径解析逻辑

#### 实例特定路径

| 函数 | 解析为 | 示例 |
|------|--------|------|
| `get_data_dir()` | `config_file.parent` | `~/.nanobot-telegram/` |
| `get_cron_dir()` | `config_file.parent/cron` | `~/.nanobot-telegram/cron` |
| `get_logs_dir()` | `config_file.parent/logs` | `~/.nanobot-telegram/logs` |
| `get_media_dir()` | `config_file.parent/media` | `~/.nanobot-telegram/media` |

#### 全局路径（跨实例共享）

| 函数 | 解析为 |
|------|--------|
| `get_cli_history_path()` | `~/.nanobot/history/cli_history` |
| `get_bridge_install_dir()` | `~/.nanobot/bridge` |
| `get_legacy_sessions_dir()` | `~/.nanobot/sessions` |

#### 工作区路径

工作区路径来自配置值，不是配置位置。使用 `--workspace` CLI 标志覆盖。

---

## 4. 配置文件格式

### 示例配置

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1,
      "maxToolIterations": 40
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": false,
      "token": "",
      "allowFrom": []
    }
  },
  "providers": {
    "openrouter": { "apiKey": "" },
    "anthropic": { "apiKey": "" },
    "openai": { "apiKey": "" }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  },
  "tools": {
    "web": {
      "proxy": null,
      "search": {
        "provider": "brave",
        "apiKey": "",
        "baseUrl": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60,
      "pathAppend": ""
    },
    "restrictToWorkspace": false,
    "mcpServers": {}
  }
}
```

### 关键特性

- **camelCase 和 snake_case** 键都被接受
- **默认值** 自动填充缺失字段
- **环境变量** 覆盖配置值
- **多实例支持** 通过 `--config` 标志

---

## 5. 多实例支持

### 快速开始

```bash
# 实例 A - Telegram 机器人
nanobot gateway --config ~/.nanobot-telegram/config.json

# 实例 B - Discord 机器人
nanobot gateway --config ~/.nanobot-discord/config.json

# 实例 C - 飞书机器人带自定义端口
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

### 路径解析

| 组件 | 解析自 | 示例 |
|------|--------|------|
| **配置** | `--config` 路径 | `~/.nanobot-A/config.json` |
| **工作区** | `--workspace` 或配置 | `~/.nanobot-A/workspace/` |
| **Cron 任务** | 配置目录 | `~/.nanobot-A/cron/` |
| **媒体/运行时状态** | 配置目录 | `~/.nanobot-A/media/` |

### 最小设置

1. 将基础配置复制到新实例目录
2. 为该实例设置不同的 `agents.defaults.workspace`
3. 使用 `--config` 启动实例
