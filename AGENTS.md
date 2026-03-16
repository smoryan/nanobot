# AGENTS.md

本文件定义本项目中 AI coding agent 的工作规则。

## 1. 构建与测试命令

```bash
# 安装依赖（开发模式)
pip install -e .

# 安装开发依赖（包含测试工具）
pip install -e ".[dev]"

# 运行所有测试
pytest tests/

# 运行特定测试文件
pytest tests/test_litellm_kwargs.py

# 运行特定测试用例（精确匹配)
pytest tests/test_commands.py::test_agent_message_flag -v

# 运行特定测试用例（模糊匹配)
pytest tests/test_commands.py -k "test_agent"

# 运行匹配模式的测试
pytest -k "test_loop" tests/

# 代码检查
ruff check nanobot/

# 格式化代码
ruff format nanobot/

# 格式化并检查
ruff format nanobot/ && ruff check nanobot/

# 类型检查（如果配置了 mypy）
mypy nanobot/
```

## 2. Git 分支策略

本项目使用三分支工作流：

| 分支 | 用途 |
|------|------|
| `main` | 同步分支：用于同步 HKUDS/nanobot (upstream) 的更新 |
| `lamz` | **主分支**：本项目的开发主分支，所有功能开发在此进行 |
| `upstream` | 上游仓库：`https://github.com/HKUDS/nanobot.git` (只读) |

### 同步上游更新流程

```bash
# 1. 获取上游最新代码
git fetch upstream

# 2. 切换到 main 分支并同步
git checkout main
git merge upstream/main --ff-only

# 3. 推送到 origin
git push origin main

# 4. 合并到 lamz 主分支
git checkout lamz
git merge main --no-ff
# 推送前确保 lamz 特有功能正常工作
pytest tests/

# 5. 推送 lamz
git push origin lamz
```

## 3. 项目结构

```
nanobot/
├── agent/          # 核心代理逻辑 (loop, context, memory, skills, tools)
│   ├── loop.py      #    Agent loop (LLM ↔ tool execution)
│   ├── context.py  #    Prompt builder
│   ├── memory.py   #    Persistent memory
│   ├── skills.py   #    Skills loader
│   ├── subagent.py #    Background task execution
│   └── tools/      #    Built-in tools (filesystem, shell, web, spawn, cron, message)
├── channels/       # 聊天通道集成 (telegram, discord, feishu, slack, email, qq, dingtalk, matrix, whatsapp, wecom, mochat)
├── providers/      # LLM 提供者 (registry.py 是单一数据源)
│   ├── registry.py      #    ProviderSpec 定义（添加新提供者只需修改此文件）
│   └── litellm_provider.py  #    LiteLLM 封装
├── config/         # 配置管理 (schema, loader, paths)
├── bus/            # 消息路由 (InboundMessage/OutboundMessage)
├── session/        # 会话持久化 (JSONL)
├── cron/           # 定时任务
├── heartbeat/      # 周期性任务检查
├── skills/         # 内置技能 (github, weather, tmux...)
├── templates/      # 工作区模板 (AGENTS.md, SOUL.md, USER.md, HEARTBEAT.md)
├── utils/          # 工具函数
└── cli/            # CLI 命令 (typer)
```

## 4. 编码规范

### 代码风格
- Python 3.11+ (使用 `|` 联合类型语法，`list[str]` 而非 `List[str]`)
- 遵循 PEP 8，4 空格缩进，行宽 100
- 使用 `loguru` 日志，`Pydantic v2` 数据验证
- 异步优先：使用 `asyncio` 和 `async/await`
- 文档字符串：模块、类、公共函数使用三引号文档字符串

### 导入顺序
```python
# 标准库
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

# 第三方库
from loguru import logger
from pydantic import BaseModel, Field

# 本地模块（相对导入）
from nanobot.config.schema import Base
from nanobot.bus.events import InboundMessage
```

### 命名约定
| 类型 | 约定 | 示例 |
|------|------|------|
| 类名 | `PascalCase` | `AgentLoop`, `MessageBus`, `LiteLLMProvider` |
| 函数/方法 | `snake_case` | `get_or_create`, `build_messages`, `_handle_message` |
| 私有方法 | 前缀 `_` | `_resolve_path`, `_register_default_tools` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_TOKENS`, `DEFAULT_MODEL`, `_MAX_CHARS` |
| 模块级变量 | `_lower_snake_case` | `_cache`, `_initialized` |
| 配置字段 | `snake_case` | `api_key`, `api_base`, `max_tokens` |

### 类型注解
```python
# 函数参数
def process_message(
    message: str,
    tools: list[dict[str, Any]] | None = None,
    config: AgentDefaults | None = None,
) -> LLMResponse:
    ...

# 类属性
class AgentLoop:
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
    ) -> None:
        ...

# 返回类型
async def fetch_data() -> dict[str, Any]:
    ...

def get_config() -> AgentsConfig:
    ...
```

## 5. 关键设计模式

### 注册表模式 (Provider Registry)
```python
# providers/registry.py 是单一数据源
# 添加新提供者只需 2 步：
# 1. 在 registry.py 添加 ProviderSpec
# 2. 在 config/schema.py 的 ProvidersConfig 添加字段

@dataclass(frozen=True)
class ProviderSpec:
    name: str                    # config field name
    keywords: tuple[str, ...]    # model-name keywords
    env_key: str                 # LiteLLM env var
    display_name: str = ""
    litellm_prefix: str = ""     # auto-prefix: model → provider/model
    ...
```

### 生产者-消费者模式 (MessageBus)
```python
# bus/queue.py
# 通道 publish → agent consume
# agent publish → 通道 consume
class MessageBus:
    async def publish(self, message: InboundMessage) -> None:
        await self._inbound_queue.put(message)
    
    async def consume(self) -> InboundMessage | None:
        return await self._inbound_queue.get()
```

### 工具基类模式
```python
# agent/tools/base.py
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
```

## 6. 配置管理

- 默认配置: `~/.nanobot/config.json`
- 多实例: `~/.nanobot-{name}/config.json`
- 所有配置类继承 `nanobot.config.schema.Base`
- 环境变量前缀: `NANOBOT_`
- 配置字段支持 camelCase 和 snake_case（通过 Pydantic alias_generator）

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "workspace": "~/.nanobot/workspace"
    }
  }
}
```

## 7. 测试约定

- 测试文件在 `tests/`，命名: `test_{module}_{feature}.py`
- 使用 `pytest` + `pytest-asyncio`
- Mock 外部依赖（网络请求、LLM 调用等）
- 每个测试文件顶部有文档字符串说明测试目的
- 使用类型注解，测试函数有明确返回类型

```python
"""Regression tests for PR #2026 — litellm_kwargs injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


def test_openrouter_spec_uses_prefix_not_custom_llm_provider() -> None:
    """OpenRouter must rely on litellm_prefix, not custom_llm_provider kwarg."""
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.litellm_prefix == "openrouter"


@pytest.mark.asyncio
async def test_openrouter_prefixes_model_correctly() -> None:
    """OpenRouter should prefix model as openrouter/vendor/model."""
    mock_acompletion = AsyncMock(return_value=_fake_response())
    
    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            provider_name="openrouter",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )
```

## 8. Git 提交规范

Conventional Commits: `<type>(<scope>): <subject>`

类型: `feat` | `fix` | `docs` | `style` | `refactor` | `test` | `chore`

示例:
- `feat(channels): add Matrix channel support`
- `fix(providers): correct OpenRouter model prefixing`
- `refactor(agent): extract tool registry to separate module`
- `test(cron): add edge case tests for timezone handling`

## 9. 常见任务
### 添加新 LLM 提供者
1. 在 `nanobot/providers/registry.py` 添加 `ProviderSpec`:
```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    env_key="MYPROVIDER_API_KEY",
    display_name="My Provider",
    litellm_prefix="myprovider",
)
```
2. 在 `nanobot/config/schema.py` 的 `ProvidersConfig` 添加字段:
```python
class ProvidersConfig(Base):
    ...
    myprovider: ProviderConfig = Field(default_factory=ProviderConfig)
```

### 添加新聊天通道
1. 在 `nanobot/channels/` 创建新文件，继承 `BaseChannel`
2. 实现必需方法: `start()`, `stop()`, `send()`
3. 在 `nanobot/config/schema.py` 添加配置类

### 添加新工具
1. 在 `nanobot/agent/tools/` 创建新文件，继承 `Tool`
2. 实现 `name`, `description`, `parameters`, `execute()`
3. 在 `nanobot/agent/loop.py` 的 `_register_default_tools()` 注册

## 10. 注意事项
### 安全
- 永远不要硬编码 API keys
- 生产环境启用 `restrictToWorkspace`
- 使用 `allow_from` 进行权限控制（空数组拒绝所有，`["*"]` 允许所有）

### 性能
- 使用内存缓存（`SessionManager._cache`）
- 大型输出截断到 16KB（`_TOOL_RESULT_MAX_CHARS = 16_000`）
- Token 估算使用 `tiktoken`

### 错误处理
- 使用 `loguru` 记录错误（`logger.error()`, `logger.exception()`）
- 重试逻辑: 429, 500-504, 超时
- 优雅降级而非崩溃
- 不要使用空的 catch 块

## 11. 核心依赖

见 `pyproject.toml`:
- `litellm` - LLM 统一接口
- `pydantic` / `pydantic-settings` - 数据验证
- `typer` / `rich` - CLI
- `loguru` - 日志
- `httpx` / `websockets` - HTTP/WebSocket 客户端
- `tiktoken` - Token 估算

## 12. 文档参考

详细模块文档位于 `docs/`:
- `00-overview.md` - 项目概述与架构
- `01-agent-loop.md` - Agent Loop 详解
- `02-context-builder.md` - 上下文构建
- `03-memory-system.md` - 内存系统
- `04-provider-registry.md` - Provider 注册表
- `05-channel-development.md` - Channel 开发指南
