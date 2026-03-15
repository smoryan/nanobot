# AGENTS.md

本文件定义本项目中 AI coding agent 的工作规则。

## 1. 构建与测试命令

```bash
# 安装依赖
pip install -e .

# 运行所有测试
pytest tests/

# 运行特定测试文件
pytest tests/test_loop_consolidation_tokens.py

# 运行特定测试用例
pytest tests/test_commands.py::test_agent_message_flag -v

# Lint
ruff check nanobot/

# 格式化
ruff format nanobot/
```

## 2. 项目结构

```
nanobot/
├── agent/          # 核心代理逻辑 (loop, context, memory, skills, tools)
├── channels/       # 聊天通道集成 (telegram, discord, feishu, slack...)
├── providers/      # LLM 提供者 (registry.py 是单一数据源)
├── config/         # 配置管理 (schema, loader, paths)
├── bus/            # 消息路由 (InboundMessage/OutboundMessage)
├── session/        # 会话持久化 (JSONL)
├── cron/           # 定时任务
├── heartbeat/      # 周期性任务检查
├── skills/         # 内置技能 (github, weather, tmux...)
├── templates/      # 工作区模板 (AGENTS.md, SOUL.md...)
├── utils/          # 工具函数
└── cli/            # CLI 命令 (typer)
```

## 3. 编码规范

### 代码风格
- Python 3.11+ (使用 `|` 联合类型语法)
- 遵循 PEP 8，4 空格缩进，行宽 100
- 使用 `loguru` 日志，`Pydantic v2` 数据验证
- 异步优先：使用 `asyncio` 和 `async/await`

### 命名约定
- 类名: `PascalCase` (如 `AgentLoop`, `MessageBus`)
- 函数/方法: `snake_case` (如 `get_or_create`, `build_messages`)
- 私有方法: 前缀 `_` (如 `_handle_message`)
- 常量: `UPPER_SNAKE_CASE` (如 `MAX_TOKENS`)

### 类型注解
```python
def process_message(
    message: str,
    tools: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    ...
```

## 4. 关键设计模式

### 注册表模式 (Provider Registry)
```python
# providers/registry.py 是单一数据源
# 添加新提供者只需：
# 1. 在 registry.py 添加 ProviderSpec
# 2. 在 config/schema.py 添加配置字段
```

### 生产者-消费者模式 (MessageBus)
```python
# bus/queue.py
# 通道 publish → agent consume
# agent publish → 通道 consume
```

## 5. 配置管理

- 默认配置: `~/.nanobot/config.json`
- 多实例: `~/.nanobot-{name}/config.json`
- 所有配置类继承 `nanobot.config.schema.Base`
- 环境变量前缀: `NANOBOT_`

## 6. 测试约定

- 测试文件在 `tests/`，命名: `test_{module}_{feature}.py`
- 使用 `pytest` + `pytest-asyncio`
- Mock 外部依赖

```python
@pytest.mark.asyncio
async def test_example():
    result = await some_async_function()
    assert result is not None
```

## 7. Git 提交规范

Conventional Commits: `<type>(<scope>): <subject>`

类型: `feat` | `fix` | `docs` | `style` | `refactor` | `test` | `chore`

示例: `feat(channels): add Matrix channel support`

## 8. 常见任务

### 添加新 LLM 提供者
1. 在 `nanobot/providers/registry.py` 添加 `ProviderSpec`
2. 在 `nanobot/config/schema.py` 的 `ProvidersConfig` 添加字段

### 添加新聊天通道
1. 在 `nanobot/channels/` 创建新文件，继承 `BaseChannel`
2. 实现 `start()`, `stop()`, `send()`
3. 在 `nanobot/config/schema.py` 添加配置类

### 添加新工具
1. 在 `nanobot/agent/tools/` 创建新文件，继承 `Tool`
2. 实现 `name`, `description`, `parameters`, `execute()`
3. 在 `nanobot/agent/loop.py` 的 `_register_default_tools()` 注册

## 9. 注意事项

### 安全
- 永远不要硬编码 API keys
- 生产环境启用 `restrictToWorkspace`
- 使用 `allow_from` 进行权限控制

### 性能
- 使用内存缓存 (`SessionManager._cache`)
- 大型输出截断到 16KB
- Token 估算使用 `tiktoken`

### 错误处理
- 使用 `loguru` 记录错误
- 重试逻辑: 429, 500-504, 超时
- 优雅降级而非崩溃

## 10. 核心依赖

见 `pyproject.toml`: `litellm`, `pydantic`, `typer`, `rich`, `loguru`, `httpx`, `websockets`

## 11. 文档参考

详细模块文档位于 `docs/`: `00-overview.md` ~ `10-bridge-module.md`
