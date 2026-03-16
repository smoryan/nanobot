# Memory Governor 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**目标：** 为 nanobot 构建一套 governor-style 的 memory 架构：主代理负责发出 memory events，专用且异步的 `memory-agent` 通过 `_MEMBEAT_TOOL` 决定持久化动作，最终把带标签的 memory 块和 `TODO.md` 落到文件系统中。

**架构：** 主代理继续保留 `memory/MEMORY.md` 的读取路径，但把 memory 治理和写入决策迁移到独立的 service / agent 边界之后。实现上复用现有 `HeartbeatService` 的“虚拟工具决策阶段”模式，再把受约束的动作确定性地物化到 `HISTORY.md`、`MEMORY.md`，以及后续的 `TODO.md`。

**技术栈：** Python 3.11+、asyncio、Pydantic 配置 schema、现有 `LLMProvider`、`Tool` / `ToolRegistry`、Markdown 文件存储、pytest、pytest-asyncio。

---

## 实施策略

按阶段落地，先打通最小闭环，再扩展 TODO 系统，最后补 `memory-agent` 的 skill / scripts。每个任务尽量严格走 TDD：先写失败测试，再补最小实现，再跑局部测试，最后再扩大验证范围。

本计划默认优先完成 Phase 1 和 Phase 2 的主链路；Phase 3 作为后续增强，不建议在第一轮实现中一起硬塞进去。

## Phase 1 - Tagged Memory + Memory Event + `_MEMBEAT_TOOL`

### Task 1: 在 `memory.py` 中增加 tagged-memory 基础能力

**Files:**
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_memory_tagged_blocks.py`

**Step 1: 先写失败测试**

创建 `tests/test_memory_tagged_blocks.py`，覆盖以下行为：

```python
from pathlib import Path

from nanobot.agent.memory import MemoryStore


def test_append_history_block_uses_tagged_header_format(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.append_history_block(
        timestamp="2026-03-16 10:00",
        block_type="decision",
        tags=["project", "constraint"],
        source="cli:alice",
        importance="high",
        body="Adopt memory governor design.",
    )

    text = store.history_file.read_text(encoding="utf-8")
    assert "[2026-03-16 10:00]" in text
    assert "[%type: decision]" in text
    assert "[%tags: project,constraint]" in text
    assert "[%source: cli:alice]" in text
    assert "[%importance: high]" in text


def test_history_block_has_blank_line_before_body(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.append_history_block(
        timestamp="2026-03-16 10:00",
        block_type="decision",
        tags=["project"],
        source="cli:alice",
        importance="medium",
        body="Body line.",
    )

    text = store.history_file.read_text(encoding="utf-8")
    assert "[%importance: medium]\n\nBody line." in text
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_memory_tagged_blocks.py -v`

Expected: FAIL，因为 `append_history_block` 还不存在。

**Step 3: 写最小实现**

在 `nanobot/agent/memory.py` 中：

- 增加一个小型 tagged block formatter helper
- 增加 `append_history_block(...)`
- 保留现有 `append_history(...)`，以便迁移期兼容
- 这一轮先不要改 consolidation 的旧行为

建议形态：

```python
def _render_tagged_block(
    timestamp: str,
    block_type: str,
    tags: list[str],
    source: str,
    importance: str,
    body: str,
) -> str:
    lines = [
        f"[{timestamp}]",
        f"[%type: {block_type}]",
        f"[%tags: {','.join(tags)}]",
        f"[%source: {source}]",
        f"[%importance: {importance}]",
        "",
        body.strip(),
    ]
    return "\n".join(lines).rstrip()
```

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_memory_tagged_blocks.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py tests/test_memory_tagged_blocks.py
git commit -m "feat(memory): add tagged history block formatter"
```

### Task 2: 引入 `_MEMBEAT_TOOL` schema 和决策归一化

**Files:**
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_membeat_tool_schema.py`

**Step 1: 先写失败测试**

创建 `tests/test_membeat_tool_schema.py`：

```python
from nanobot.agent.memory import _MEMBEAT_TOOL, normalize_membeat_actions


def test_membeat_tool_exposes_allowed_actions() -> None:
    function = _MEMBEAT_TOOL[0]["function"]
    assert function["name"] == "membeat"
    actions = function["parameters"]["properties"]["actions"]["items"]["properties"]["kind"]["enum"]
    assert actions == ["append_history", "upsert_memory", "emit_todo", "noop"]


def test_normalize_membeat_actions_accepts_valid_payload() -> None:
    payload = {
        "actions": [
            {"kind": "append_history", "id": "a1", "timestamp": "2026-03-16 10:00", "type": "decision", "tags": ["project"], "source": "cli:alice", "importance": "high", "body": "Hello"}
        ]
    }
    actions = normalize_membeat_actions(payload)
    assert actions[0]["kind"] == "append_history"
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_membeat_tool_schema.py -v`

Expected: FAIL，因为 `_MEMBEAT_TOOL` 和 `normalize_membeat_actions` 还未定义。

**Step 3: 写最小实现**

在 `nanobot/agent/memory.py` 中：

- 增加 `_MEMBEAT_TOOL`
- 严格按已确认设计定义 action kinds
- 增加 normalization helper，返回 `list[dict[str, Any]]`
- 对格式错误的 payload 尽早、确定性地拒绝

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_membeat_tool_schema.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py tests/test_membeat_tool_schema.py
git commit -m "feat(memory): add membeat tool schema"
```

### Task 3: 增加 `MemoryEvent` 和 event emission 契约

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `nanobot/agent/loop.py`
- Test: `tests/test_memory_event_emission.py`

**Step 1: 先写失败测试**

创建 `tests/test_memory_event_emission.py`：

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


@pytest.mark.asyncio
async def test_process_direct_emits_memory_event_after_turn(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    loop.emit_memory_event = AsyncMock()  # type: ignore[method-assign]

    await loop.process_direct("hello", session_key="cli:test")

    loop.emit_memory_event.assert_awaited_once()
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_memory_event_emission.py -v`

Expected: FAIL，因为 `emit_memory_event` 还不存在，或者没有被调用。

**Step 3: 写最小实现**

在 `nanobot/agent/memory.py` 中：

- 增加一个简单的 `MemoryEvent` dataclass 或 typed dict

在 `nanobot/agent/loop.py` 中：

- 增加 `emit_memory_event(...)`
- 在 `_save_turn(...)` 和 `self.sessions.save(session)` 之后调用它
- 这一轮先保留当前同步 consolidation，避免已有行为回归
- 第一版可以先是 no-op stub，只要把未来 service 边界立起来即可

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_memory_event_emission.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py nanobot/agent/loop.py tests/test_memory_event_emission.py
git commit -m "refactor(memory): add memory event emission hook"
```

### Task 4: 参考 heartbeat 风格创建 `MemoryGovernorService`

**Files:**
- Create: `nanobot/memory_governor/service.py`
- Test: `tests/test_memory_governor_service.py`
- Reference: `nanobot/heartbeat/service.py`

**Step 1: 先写失败测试**

创建 `tests/test_memory_governor_service.py`，至少覆盖：

```python
import pytest

from nanobot.memory_governor.service import MemoryGovernorService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs):
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_decide_returns_membeat_actions(tmp_path) -> None:
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="mb_1",
                    name="membeat",
                    arguments={"actions": [{"kind": "noop", "id": "noop-1"}]},
                )
            ],
        )
    ])
    service = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")
    actions = await service.decide_actions("prompt")
    assert actions == [{"kind": "noop", "id": "noop-1"}]
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_memory_governor_service.py -v`

Expected: FAIL，因为 service 模块还不存在。

**Step 3: 写最小实现**

创建 `nanobot/memory_governor/service.py`：

- 整体模式参考 `HeartbeatService`
- 暴露 `decide_actions(prompt: str) -> list[dict[str, Any]]`
- 调用 `provider.chat_with_retry(..., tools=_MEMBEAT_TOOL, model=self.model)`
- 用 `normalize_membeat_actions` 归一化工具返回结果

这一轮先不要接进主运行时。

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_memory_governor_service.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/memory_governor/service.py tests/test_memory_governor_service.py
git commit -m "feat(memory): add governor service decision layer"
```

### Task 5: 以确定性方式物化 `append_history` 和 `upsert_memory`

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `nanobot/memory_governor/service.py`
- Test: `tests/test_memory_materialization.py`

**Step 1: 先写失败测试**

创建 `tests/test_memory_materialization.py`：

```python
from pathlib import Path

from nanobot.agent.memory import MemoryStore


def test_apply_append_history_action_writes_tagged_block(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.apply_membeat_action({
        "kind": "append_history",
        "id": "a1",
        "timestamp": "2026-03-16 10:00",
        "type": "decision",
        "tags": ["project"],
        "source": "cli:alice",
        "importance": "high",
        "body": "Adopt governor design.",
    })
    assert "[%type: decision]" in store.history_file.read_text(encoding="utf-8")


def test_apply_upsert_memory_action_writes_memory_file(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.apply_membeat_action({
        "kind": "upsert_memory",
        "id": "m1",
        "merge_key": "project:governor-style",
        "type": "project",
        "tags": ["project", "constraint"],
        "source": "history:2026-03-16T10:00",
        "importance": "high",
        "body": "Use governor-style memory-agent.",
    })
    assert "Use governor-style memory-agent." in store.memory_file.read_text(encoding="utf-8")
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_memory_materialization.py -v`

Expected: FAIL，因为 `apply_membeat_action` 还不存在。

**Step 3: 写最小实现**

在 `nanobot/agent/memory.py` 中：

- 增加 `apply_membeat_action(...)`
- 先实现 `append_history` 和 `upsert_memory` 两个分支
- 当前阶段 `upsert_memory` 可采用简单、显式的 `merge_key` 合并策略，不要提前做复杂抽象

在 `nanobot/memory_governor/service.py` 中：

- 增加 `apply_actions(...)`
- 遍历归一化后的 actions，并委托给 `MemoryStore`

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_memory_materialization.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py nanobot/memory_governor/service.py tests/test_memory_materialization.py
git commit -m "feat(memory): materialize membeat actions"
```

### Task 6: 把 `MemoryGovernorService` 接进运行时，但暂不移除旧 consolidation

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/cli/commands.py`
- Test: `tests/test_memory_governor_wiring.py`

**Step 1: 先写失败测试**

创建 `tests/test_memory_governor_wiring.py`：

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


@pytest.mark.asyncio
async def test_process_direct_dispatches_memory_event_to_governor(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    loop.memory_governor = AsyncMock()

    await loop.process_direct("hello", session_key="cli:test")

    loop.memory_governor.handle_event.assert_awaited()
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_memory_governor_wiring.py -v`

Expected: FAIL，因为 `memory_governor` 还没有接入。

**Step 3: 写最小实现**

在 `nanobot/agent/loop.py` 中：

- 在 `AgentLoop.__init__` 中接受可选的 `memory_governor` 依赖
- 如果该依赖存在，就把 `emit_memory_event(...)` 转发到 `memory_governor.handle_event(...)`
- 当前阶段继续保留旧 `MemoryConsolidator`，确保迁移安全

在 `nanobot/cli/commands.py` 中：

- 实例化 `MemoryGovernorService`
- 把它传给 `AgentLoop(...)`

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_memory_governor_wiring.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py nanobot/cli/commands.py tests/test_memory_governor_wiring.py
git commit -m "feat(memory): wire governor service into agent loop"
```

## Phase 2 - `TODO.md` + `todo_tools`

### Task 7: 增加 `TODO.md` 模板和工作区同步支持

**Files:**
- Create: `nanobot/templates/TODO.md`
- Modify: `nanobot/utils/helpers.py`
- Test: `tests/test_commands.py`

**Step 1: 先写失败测试**

扩展 `tests/test_commands.py`，断言 `sync_workspace_templates(...)` 会创建 `TODO.md`。

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_commands.py -k "TODO or onboard or workspace" -v`

Expected: FAIL，因为 `TODO.md` 还不会被创建。

**Step 3: 写最小实现**

- 创建 `nanobot/templates/TODO.md`，包含已确认的分区：
  - `## Active`
  - `## Waiting on User`
  - `## Completed`
- 修改 `nanobot/utils/helpers.py`，让工作区模板同步逻辑复制这个文件

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_commands.py -k "TODO or onboard or workspace" -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/templates/TODO.md nanobot/utils/helpers.py tests/test_commands.py
git commit -m "feat(todo): add workspace TODO template"
```

### Task 8: 实现 `TodoTool` 的基础操作

**Files:**
- Create: `nanobot/agent/tools/todo.py`
- Modify: `nanobot/agent/tools/__init__` if needed
- Test: `tests/test_todo_tool.py`
- Reference: `nanobot/agent/tools/base.py`, `nanobot/agent/tools/cron.py`

**Step 1: 先写失败测试**

创建 `tests/test_todo_tool.py`，覆盖：

- `add_todo`
- `update_todo`
- `complete_todo`
- `move_todo`
- `list_todos`

示例骨架：

```python
import pytest

from nanobot.agent.tools.todo import TodoTool


@pytest.mark.asyncio
async def test_add_todo_appends_agent_task(tmp_path) -> None:
    tool = TodoTool(workspace=tmp_path)
    result = await tool.execute(
        action="add_todo",
        task_id="todo-1",
        executor="Agent",
        user="alice",
        text="Draft implementation plan",
        section="Active",
        source="history:2026-03-16T10:00",
    )
    assert "todo-1" in result
    assert "Draft implementation plan" in (tmp_path / "TODO.md").read_text(encoding="utf-8")
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_todo_tool.py -v`

Expected: FAIL，因为 tool 还不存在。

**Step 3: 写最小实现**

创建 `nanobot/agent/tools/todo.py`：

- 先做成一个单工具，通过 `action` enum 控制子动作，便于 v1 集成
- actions: `add_todo`, `update_todo`, `complete_todo`, `move_todo`, `list_todos`
- 只允许确定性的 markdown 编辑
- 不允许 freeform rewrite

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_todo_tool.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/tools/todo.py tests/test_todo_tool.py
git commit -m "feat(todo): add deterministic todo tool"
```

### Task 9: 在主循环中注册 `TodoTool`

**Files:**
- Modify: `nanobot/agent/loop.py`
- Test: `tests/test_tool_validation.py`

**Step 1: 先写失败测试**

增加测试：创建 `AgentLoop(...)` 后断言 `loop.tools.has("todo")` 为真。

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_tool_validation.py -k todo -v`

Expected: FAIL，因为该工具尚未注册。

**Step 3: 写最小实现**

更新 `AgentLoop._register_default_tools()`，注册 `TodoTool(workspace=self.workspace)`。

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_tool_validation.py -k todo -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py tests/test_tool_validation.py
git commit -m "feat(todo): register todo tool"
```

### Task 10: 通过 `todo_tools` 物化 `emit_todo` actions

**Files:**
- Modify: `nanobot/memory_governor/service.py`
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_membeat_emit_todo.py`

**Step 1: 先写失败测试**

创建 `tests/test_membeat_emit_todo.py`：

```python
import pytest

from nanobot.memory_governor.service import MemoryGovernorService


@pytest.mark.asyncio
async def test_emit_todo_action_writes_to_todo_file(tmp_path) -> None:
    service = MemoryGovernorService(workspace=tmp_path, provider=None, model="test-model")
    await service.apply_actions([
        {
            "kind": "emit_todo",
            "id": "todo-1",
            "dedupe_key": "alice:draft-plan",
            "executor_type": "Agent",
            "user_object": "alice",
            "task_text": "Draft implementation plan",
            "source_reference": "history:2026-03-16T10:00",
        }
    ])
    assert "Draft implementation plan" in (tmp_path / "TODO.md").read_text(encoding="utf-8")
```

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_membeat_emit_todo.py -v`

Expected: FAIL，因为 `emit_todo` 还没有实现。

**Step 3: 写最小实现**

在 `nanobot/memory_governor/service.py` 中：

- 内部实例化 `TodoTool`，或通过依赖注入获取它
- 处理 `emit_todo` 时，不要直接写 markdown，而是调用确定性的 tool API

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_membeat_emit_todo.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/memory_governor/service.py nanobot/agent/memory.py tests/test_membeat_emit_todo.py
git commit -m "feat(memory): project todo actions into TODO file"
```

## Phase 3 - 替换旧同步 consolidation，并增加显式控制项

### Task 11: 增加 memory governor 的 rollout 配置项

**Files:**
- Modify: `nanobot/config/schema.py`
- Test: `tests/test_config_migration.py`

**Step 1: 先写失败测试**

给以下 AgentDefaults 配置项补测试：

- `memory_governor_enabled: bool = True`
- `memory_governor_model: str | None = None`
- `memory_governor_batch_s: int = 0`

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_config_migration.py -k memory -v`

Expected: FAIL，因为 schema 里还没有这些字段。

**Step 3: 写最小实现**

在 `nanobot/config/schema.py` 的 `AgentDefaults` 中加上这些字段。

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_config_migration.py -k memory -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/config/schema.py tests/test_config_migration.py
git commit -m "feat(config): add memory governor settings"
```

### Task 12: 用 governor dispatch 替换 preflight/postflight 同步 consolidation

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `tests/test_loop_consolidation_tokens.py`
- Create: `tests/test_memory_governor_replaces_sync_consolidation.py`

**Step 1: 先写失败测试**

新增覆盖，证明：

- governor mode 启用时，`process_direct(...)` 不再 await `maybe_consolidate_by_tokens(...)`
- 而是改为 dispatch memory events

**Step 2: 跑测试，确认先失败**

Run: `pytest tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py -v`

Expected: FAIL，因为同步 consolidation 仍然存在。

**Step 3: 写最小实现**

在 `nanobot/agent/loop.py` 中：

- 用新配置项包住旧的 `self.memory_consolidator.maybe_consolidate_by_tokens(session)` 调用
- governor mode 开启时，改为发射 / 转发 events
- 确保 `/new` 的归档路径仍可工作，可以通过 `memory_governor` 或独立 archival helper 实现

**Step 4: 再跑测试，确认通过**

Run: `pytest tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py -v`

Expected: PASS。

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py
git commit -m "refactor(memory): replace sync consolidation with governor dispatch"
```

### Task 13: 增加显式 memory-agent 文档和 skill 说明

**Files:**
- Modify: `nanobot/skills/memory/SKILL.md`
- Modify: `docs/plans/2026-03-16-memory-governor-design.md`
- Modify: `docs/plans/2026-03-16-memory-governor-design.zh-CN.md`
- Optional Create: `nanobot/skills/memory-agent/SKILL.md`

**Step 1: 先写 doc 校验任务**

如果当前仓库没有 doc lint，就把这一项当成手工文档校验任务。

**Step 2: 最小更新文档**

- 解释 tagged block 格式
- 解释 `TODO.md`
- 解释 memory 写入现在是异步治理而不是主链路直接写入

**Step 3: 验证文档相关回归**

Run: `pytest tests/test_commands.py -k memory -v`

Expected: 现有 memory 相关测试仍然 PASS。

**Step 4: Commit**

```bash
git add nanobot/skills/memory/SKILL.md docs/plans/2026-03-16-memory-governor-design.md docs/plans/2026-03-16-memory-governor-design.zh-CN.md nanobot/skills/memory-agent/SKILL.md
git commit -m "docs(memory): describe governor-style memory system"
```

## 最终验证

按顺序运行聚焦测试：

```bash
pytest tests/test_memory_tagged_blocks.py -v
pytest tests/test_membeat_tool_schema.py -v
pytest tests/test_memory_event_emission.py -v
pytest tests/test_memory_governor_service.py -v
pytest tests/test_memory_materialization.py -v
pytest tests/test_memory_governor_wiring.py -v
pytest tests/test_todo_tool.py -v
pytest tests/test_membeat_emit_todo.py -v
pytest tests/test_loop_consolidation_tokens.py -v
pytest tests/test_consolidate_offset.py -v
pytest tests/test_heartbeat_service.py -v
```

再运行一轮更宽的回归验证：

```bash
pytest tests/test_memory_consolidation_types.py -v
pytest tests/test_commands.py -k "memory or TODO or workspace" -v
pytest tests/test_tool_validation.py -v
ruff check nanobot/ tests/
```

Expected:

- 所有新增聚焦测试 PASS
- 现有 memory / tool validation 测试 PASS
- 修改过的文件没有新增 ruff 问题

## 执行注意事项

- 在 governor 路径有足够测试覆盖前，先保留旧同步路径
- 不要一次性破坏性重写现有 `MEMORY.md` 内容格式，要支持平滑迁移
- 优先增加小 helper，不要一上来就在 `AgentLoop` 里做大手术
- `emit_todo` 从第一天起就必须确定性、可幂等
- `_MEMBEAT_TOOL` 绝不能直接写文件

## 推荐提交顺序

1. `feat(memory): add tagged history block formatter`
2. `feat(memory): add membeat tool schema`
3. `refactor(memory): add memory event emission hook`
4. `feat(memory): add governor service decision layer`
5. `feat(memory): materialize membeat actions`
6. `feat(memory): wire governor service into agent loop`
7. `feat(todo): add workspace TODO template`
8. `feat(todo): add deterministic todo tool`
9. `feat(todo): register todo tool`
10. `feat(memory): project todo actions into TODO file`
11. `feat(config): add memory governor settings`
12. `refactor(memory): replace sync consolidation with governor dispatch`
13. `docs(memory): describe governor-style memory system`

计划已保存到 `docs/plans/2026-03-16-memory-governor-implementation-plan.zh-CN.md`。

两种执行方式：

**1. Subagent-Driven（当前会话）** - 我在这个会话里按任务逐个派发、逐个 review，迭代快

**2. Parallel Session（新会话）** - 你开一个新会话，用 executing-plans 按批次推进

你想走哪一种？
