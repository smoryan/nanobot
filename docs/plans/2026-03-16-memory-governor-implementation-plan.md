# Memory Governor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a governor-style memory architecture for nanobot where the main agent emits memory events, a dedicated asynchronous `memory-agent` governs persistence through `_MEMBEAT_TOOL`, and tagged memory blocks plus `TODO.md` become the durable outputs.

**Architecture:** Keep the main agent on the read path for `memory/MEMORY.md`, but move memory governance and write decisions behind a dedicated service/agent boundary. Reuse the existing `HeartbeatService` pattern for a virtual tool-driven decision phase, then materialize constrained actions deterministically into `HISTORY.md`, `MEMORY.md`, and later `TODO.md`.

**Tech Stack:** Python 3.11+, asyncio, Pydantic config schema, existing `LLMProvider`, `Tool` / `ToolRegistry`, markdown file storage, pytest, pytest-asyncio.

---

## Implementation Strategy

按阶段落地，先打通最小闭环，再扩展 TODO 系统，最后补 memory-agent skill / scripts。每个任务都尽量走 TDD：先写失败测试，再补最小实现，再跑局部测试，最后再扩大验证范围。

本计划默认先实现 Phase 1 和 Phase 2 的主链路；Phase 3 保留为后续扩展任务，不在第一轮强行一起做完。

## Phase 1 - Tagged Memory + Memory Event + `_MEMBEAT_TOOL`

### Task 1: Add tagged-memory primitives in `memory.py`

**Files:**
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_memory_tagged_blocks.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_tagged_blocks.py` with focused tests for:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_tagged_blocks.py -v`

Expected: FAIL because `append_history_block` does not exist yet.

**Step 3: Write minimal implementation**

In `nanobot/agent/memory.py`:

- Add a small formatter helper for tagged blocks
- Add `append_history_block(...)`
- Keep the existing `append_history(...)` for backward compatibility during migration
- Do not change consolidation behavior yet

Suggested shape:

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

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_tagged_blocks.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py tests/test_memory_tagged_blocks.py
git commit -m "feat(memory): add tagged history block formatter"
```

### Task 2: Introduce `_MEMBEAT_TOOL` schema and decision normalization

**Files:**
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_membeat_tool_schema.py`

**Step 1: Write the failing tests**

Create `tests/test_membeat_tool_schema.py`:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_membeat_tool_schema.py -v`

Expected: FAIL because `_MEMBEAT_TOOL` and `normalize_membeat_actions` are not defined.

**Step 3: Write minimal implementation**

In `nanobot/agent/memory.py`:

- Add `_MEMBEAT_TOOL`
- Define allowed action kinds exactly as approved
- Add a normalization helper that returns `list[dict[str, Any]]`
- Reject malformed payloads early and deterministically

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_membeat_tool_schema.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py tests/test_membeat_tool_schema.py
git commit -m "feat(memory): add membeat tool schema"
```

### Task 3: Add `MemoryEvent` and event emission contract

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `nanobot/agent/loop.py`
- Test: `tests/test_memory_event_emission.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_event_emission.py`:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_event_emission.py -v`

Expected: FAIL because `emit_memory_event` does not exist or is not called.

**Step 3: Write minimal implementation**

In `nanobot/agent/memory.py`:

- Add a simple `MemoryEvent` dataclass or typed dict

In `nanobot/agent/loop.py`:

- Add `emit_memory_event(...)`
- Call it after `_save_turn(...)` and `self.sessions.save(session)`
- Keep current synchronous consolidation in place for now so behavior does not regress yet
- First implementation can be a no-op stub that prepares the future service boundary

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_event_emission.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py nanobot/agent/loop.py tests/test_memory_event_emission.py
git commit -m "refactor(memory): add memory event emission hook"
```

### Task 4: Create `MemoryGovernorService` using heartbeat-style decision flow

**Files:**
- Create: `nanobot/memory_governor/service.py`
- Test: `tests/test_memory_governor_service.py`
- Reference: `nanobot/heartbeat/service.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_governor_service.py` with tests for:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_governor_service.py -v`

Expected: FAIL because the service module does not exist.

**Step 3: Write minimal implementation**

Create `nanobot/memory_governor/service.py`:

- model it after `HeartbeatService`
- expose `decide_actions(prompt: str) -> list[dict[str, Any]]`
- call `provider.chat_with_retry(..., tools=_MEMBEAT_TOOL, model=self.model)`
- normalize the tool payload with `normalize_membeat_actions`

Do not wire it into the main runtime yet.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_governor_service.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/memory_governor/service.py tests/test_memory_governor_service.py
git commit -m "feat(memory): add governor service decision layer"
```

### Task 5: Materialize `append_history` and `upsert_memory` actions deterministically

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `nanobot/memory_governor/service.py`
- Test: `tests/test_memory_materialization.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_materialization.py`:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_materialization.py -v`

Expected: FAIL because `apply_membeat_action` does not exist.

**Step 3: Write minimal implementation**

In `nanobot/agent/memory.py`:

- add `apply_membeat_action(...)`
- implement deterministic branches for `append_history` and `upsert_memory`
- for now, `upsert_memory` may append under a simple heading or merge by `merge_key` in a straightforward, explicit way

In `nanobot/memory_governor/service.py`:

- add `apply_actions(...)`
- iterate over normalized actions and delegate to `MemoryStore`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_materialization.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/memory.py nanobot/memory_governor/service.py tests/test_memory_materialization.py
git commit -m "feat(memory): materialize membeat actions"
```

### Task 6: Wire `MemoryGovernorService` into runtime without removing old consolidation yet

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/cli/commands.py`
- Test: `tests/test_memory_governor_wiring.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_governor_wiring.py`:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_governor_wiring.py -v`

Expected: FAIL because `memory_governor` is not yet wired.

**Step 3: Write minimal implementation**

In `nanobot/agent/loop.py`:

- accept optional `memory_governor` dependency in `AgentLoop.__init__`
- if configured, dispatch `emit_memory_event(...)` into `memory_governor.handle_event(...)`
- keep existing `MemoryConsolidator` active for migration safety

In `nanobot/cli/commands.py`:

- instantiate `MemoryGovernorService`
- pass it into `AgentLoop(...)`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_governor_wiring.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py nanobot/cli/commands.py tests/test_memory_governor_wiring.py
git commit -m "feat(memory): wire governor service into agent loop"
```

## Phase 2 - `TODO.md` + `todo_tools`

### Task 7: Add `TODO.md` template and workspace sync support

**Files:**
- Create: `nanobot/templates/TODO.md`
- Modify: `nanobot/utils/helpers.py`
- Test: `tests/test_commands.py`

**Step 1: Write the failing test**

Extend `tests/test_commands.py` with an assertion that `sync_workspace_templates(...)` creates `TODO.md`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_commands.py -k "TODO or onboard or workspace" -v`

Expected: FAIL because `TODO.md` is not created.

**Step 3: Write minimal implementation**

- Create `nanobot/templates/TODO.md` with the approved sections:
  - `## Active`
  - `## Waiting on User`
  - `## Completed`
- Update `nanobot/utils/helpers.py` workspace template sync to copy it

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_commands.py -k "TODO or onboard or workspace" -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/templates/TODO.md nanobot/utils/helpers.py tests/test_commands.py
git commit -m "feat(todo): add workspace TODO template"
```

### Task 8: Implement `TodoTool` primitives

**Files:**
- Create: `nanobot/agent/tools/todo.py`
- Modify: `nanobot/agent/tools/__init__` if needed
- Test: `tests/test_todo_tool.py`
- Reference: `nanobot/agent/tools/base.py`, `nanobot/agent/tools/cron.py`

**Step 1: Write the failing tests**

Create `tests/test_todo_tool.py` covering:

- `add_todo`
- `update_todo`
- `complete_todo`
- `move_todo`
- `list_todos`

Example skeleton:

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

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_todo_tool.py -v`

Expected: FAIL because tool does not exist.

**Step 3: Write minimal implementation**

Create `nanobot/agent/tools/todo.py`:

- single tool with an `action` enum to keep registration simple in v1
- actions: `add_todo`, `update_todo`, `complete_todo`, `move_todo`, `list_todos`
- deterministic markdown editing only
- no freeform rewrite path

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_todo_tool.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/tools/todo.py tests/test_todo_tool.py
git commit -m "feat(todo): add deterministic todo tool"
```

### Task 9: Register `TodoTool` in the main loop

**Files:**
- Modify: `nanobot/agent/loop.py`
- Test: `tests/test_tool_validation.py`

**Step 1: Write the failing test**

Add a test that creates `AgentLoop(...)` and asserts `loop.tools.has("todo")` is true.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tool_validation.py -k todo -v`

Expected: FAIL because the tool is not registered.

**Step 3: Write minimal implementation**

Update `AgentLoop._register_default_tools()` to register `TodoTool(workspace=self.workspace)`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_tool_validation.py -k todo -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py tests/test_tool_validation.py
git commit -m "feat(todo): register todo tool"
```

### Task 10: Materialize `emit_todo` actions through `todo_tools`

**Files:**
- Modify: `nanobot/memory_governor/service.py`
- Modify: `nanobot/agent/memory.py`
- Test: `tests/test_membeat_emit_todo.py`

**Step 1: Write the failing tests**

Create `tests/test_membeat_emit_todo.py`:

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

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_membeat_emit_todo.py -v`

Expected: FAIL because `emit_todo` handling is not implemented.

**Step 3: Write minimal implementation**

In `nanobot/memory_governor/service.py`:

- instantiate `TodoTool` internally or inject it
- on `emit_todo`, call the deterministic tool API instead of writing markdown inline

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_membeat_emit_todo.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/memory_governor/service.py nanobot/agent/memory.py tests/test_membeat_emit_todo.py
git commit -m "feat(memory): project todo actions into TODO file"
```

## Phase 3 - Replace old synchronous consolidation and add explicit controls

### Task 11: Add config flags for memory governor rollout

**Files:**
- Modify: `nanobot/config/schema.py`
- Test: `tests/test_config_migration.py`

**Step 1: Write the failing test**

Add coverage for new agent defaults such as:

- `memory_governor_enabled: bool = True`
- `memory_governor_model: str | None = None`
- `memory_governor_batch_s: int = 0`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_migration.py -k memory -v`

Expected: FAIL because schema fields do not exist.

**Step 3: Write minimal implementation**

Add the fields to `AgentDefaults` in `nanobot/config/schema.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_migration.py -k memory -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/config/schema.py tests/test_config_migration.py
git commit -m "feat(config): add memory governor settings"
```

### Task 12: Replace preflight/postflight synchronous consolidation with governor dispatch

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `tests/test_loop_consolidation_tokens.py`
- Create: `tests/test_memory_governor_replaces_sync_consolidation.py`

**Step 1: Write the failing tests**

Create coverage that proves:

- `process_direct(...)` no longer awaits `maybe_consolidate_by_tokens(...)` when governor mode is enabled
- instead, it dispatches memory events

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py -v`

Expected: FAIL because sync consolidation is still active.

**Step 3: Write minimal implementation**

In `nanobot/agent/loop.py`:

- gate old `self.memory_consolidator.maybe_consolidate_by_tokens(session)` calls behind the new config flag
- when governor mode is enabled, emit/dispatch events instead
- keep `/new` archival path working by routing it through `memory_governor` or a dedicated archival helper

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add nanobot/agent/loop.py tests/test_loop_consolidation_tokens.py tests/test_memory_governor_replaces_sync_consolidation.py
git commit -m "refactor(memory): replace sync consolidation with governor dispatch"
```

### Task 13: Add explicit memory-agent docs and skill-facing guidance

**Files:**
- Modify: `nanobot/skills/memory/SKILL.md`
- Modify: `docs/plans/2026-03-16-memory-governor-design.md`
- Modify: `docs/plans/2026-03-16-memory-governor-design.zh-CN.md`
- Optional Create: `nanobot/skills/memory-agent/SKILL.md`

**Step 1: Write the failing doc/tests check**

If there is no doc linting, treat this as a manual doc-validation task.

**Step 2: Update docs minimally**

- explain tagged block format
- explain `TODO.md`
- explain that memory writes are now governed asynchronously

**Step 3: Verify docs**

Run: `pytest tests/test_commands.py -k memory -v`

Expected: Existing memory-related tests still PASS.

**Step 4: Commit**

```bash
git add nanobot/skills/memory/SKILL.md docs/plans/2026-03-16-memory-governor-design.md docs/plans/2026-03-16-memory-governor-design.zh-CN.md nanobot/skills/memory-agent/SKILL.md
git commit -m "docs(memory): describe governor-style memory system"
```

## Final Verification

Run the focused suites in order:

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

Then run broader regression coverage:

```bash
pytest tests/test_memory_consolidation_types.py -v
pytest tests/test_commands.py -k "memory or TODO or workspace" -v
pytest tests/test_tool_validation.py -v
ruff check nanobot/ tests/
```

Expected:

- all new targeted tests PASS
- existing memory and tool validation tests PASS
- no new ruff violations in modified files

## Execution Notes

- Keep the old synchronous path until the governor path is covered by tests
- Do not rewrite existing `MEMORY.md` content format in one destructive step; support a migration-friendly transition
- Prefer adding new helpers over large in-place refactors inside `AgentLoop`
- Keep `emit_todo` deterministic and idempotent from day one
- Do not let `_MEMBEAT_TOOL` write files directly

## Recommended Commit Sequence

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
