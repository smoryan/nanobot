# Memory Governor Design

## Overview

This design moves memory governance out of the main agent loop and into a dedicated,
default-asynchronous `memory-agent`, while preserving the current lightweight,
grep-first file-based memory model.

Final control flow:

`conversation -> memory event -> memory-agent -> _MEMBEAT_TOOL actions -> file materialization`

The main agent keeps the read path for `memory/MEMORY.md` so prompt construction stays
simple and predictable. The write path and governance path move to `memory-agent`, which
owns tagging, consolidation, history compaction, and TODO emission.

## Goals

- Add structured tag headers using non-Markdown-leading markers: `[%key:value]`
- Introduce a governor-style `memory-agent` that runs asynchronously by default
- Use `_MEMBEAT_TOOL` as the controlled action protocol for memory decisions
- Add `TODO.md` plus `todo_tools` as a separate task-management projection
- Keep the memory system auditable, grep-friendly, and file-based

## Non-Goals

- No vector database or heavy RAG pipeline
- No change to the main agent's direct read path for `memory/MEMORY.md`
- No session model redesign in the first phase
- No freeform file rewrites by the memory model

## Architecture

### Main Agent

- Reads `memory/MEMORY.md` into context as it does today
- Does not directly govern or materialize memory updates
- Emits a `memory event` after a conversation turn completes

### Memory Agent

- Acts as the single governor for memory management
- Consumes memory events asynchronously
- Interprets recent conversation state and decides whether to persist anything
- Calls `_MEMBEAT_TOOL` to obtain a constrained action list
- Hands approved actions to deterministic materializers

### _MEMBEAT_TOOL

- Returns structured memory actions only
- Does not directly edit files
- Encodes the decision boundary between memory interpretation and file mutation

### Materializers

- Persist `append_history` actions into `memory/HISTORY.md`
- Persist `upsert_memory` actions into `memory/MEMORY.md`
- Persist `emit_todo` actions into `TODO.md` through `todo_tools`

## File Formats

### memory/HISTORY.md

Append-only event log with tagged blocks.

Example:

```md
[2026-03-15 12:30]
[%type: decision]
[%tags: project,todo,constraint]
[%source: cli:alice]
[%importance: high]

User decided to introduce tagged memory and an async memory-agent.
```

Format rules:

- First line remains the existing timestamp anchor: `[YYYY-MM-DD HH:MM]`
- Metadata header lines use `[%key:value]`
- One blank line separates metadata from body
- Body stays human-readable natural language
- `HISTORY.md` remains append-only in normal operation

### memory/MEMORY.md

Consolidated long-term facts, also represented as human-readable blocks with `[%...]`
headers. It should bias toward stable facts rather than event logs.

Example:

```md
## Project Context

[%type: project]
[%tags: project,constraint]
[%source: history:2026-03-15T12:30]
[%importance: high]

The system should use a governor-style memory-agent and keep the main agent on the read path only.
```

### TODO.md

Workspace task file with fixed sections and fixed item semantics.

Sections:

- `## Active`
- `## Waiting on User`
- `## Completed`

Each item must carry:

- checkbox state
- executor type: `Agent` or `User`
- user object
- normalized task text
- optional source memory reference

Illustrative format:

```md
## Active

- [ ] [Agent] [user:alice] Draft memory-agent implementation plan [source:history:2026-03-15T12:30]

## Waiting on User

- [ ] [User] [user:alice] Review memory governor design draft

## Completed

- [x] [Agent] [user:alice] Approve memory governor architecture
```

## Tag Model

Initial tag enum:

- `profile`
- `preference`
- `project`
- `decision`
- `constraint`
- `todo`

Design notes:

- Tags express semantic class, not storage destination
- `todo` marks memory content that should be projected into the TODO system
- Multiple tags may appear in a single block via `[%tags:...]`

## Memory Event Schema

The main agent emits a lightweight event after a conversation turn.

Required fields:

- `session_key`
- `message_range`
- `trigger`
- `origin`
- `timestamp`

Optional fields:

- `context_excerpt`
- `message_ids`
- `channel`
- `chat_id`

The event is not a final memory write request. It is only an input signal for
`memory-agent` governance.

## _MEMBEAT_TOOL Action Schema

Allowed actions in v1:

- `append_history`
- `upsert_memory`
- `emit_todo`
- `noop`

### append_history

Purpose:

- add one tagged event block to `memory/HISTORY.md`

Required payload:

- stable action id
- timestamp
- type
- tags
- source
- importance
- body

### upsert_memory

Purpose:

- merge a stable fact into `memory/MEMORY.md`

Required payload:

- stable action id
- merge key
- type
- tags
- source reference
- importance
- body

### emit_todo

Purpose:

- create or update a normalized TODO item through `todo_tools`

Required payload:

- stable action id
- dedupe key
- executor type
- user object
- task text
- source reference

### noop

Purpose:

- explicitly record that no memory persistence is needed for the current event

## TODO System

`TODO.md` is a projection, not the source of truth for memory. The memory source of truth
remains the conversation plus persisted memory files.

Rules:

- `main agent` does not directly manage `TODO.md`
- `memory-agent` emits task intent via `emit_todo`
- `todo_tools` apply deterministic updates to `TODO.md`
- user tasks and agent tasks share one file, but retain explicit executor labels

## todo_tools Minimal API

Minimal API for v1:

- `add_todo`
- `update_todo`
- `complete_todo`
- `move_todo`
- `list_todos`

Deliberately excluded in v1:

- freeform rewrite
- bulk arbitrary replacement
- model-authored direct markdown editing

## Execution Flow

1. Main conversation turn completes.
2. Main agent saves normal session history.
3. Main agent emits a `memory event` asynchronously.
4. `memory-agent` receives the event and loads the necessary slice of context.
5. `memory-agent` calls `_MEMBEAT_TOOL`.
6. `_MEMBEAT_TOOL` returns constrained actions.
7. Deterministic materializers write `HISTORY.md`, `MEMORY.md`, and `TODO.md`.
8. Failures retry without blocking the main conversation path.

## Safety and Invariants

- Main agent never directly governs memory writes in the new design
- `_MEMBEAT_TOOL` never writes files directly
- File writes must be deterministic and auditable
- Replayed memory events must be idempotent
- `emit_todo` actions must be deduplicated
- `HISTORY.md` must stay grep-friendly and append-oriented
- `MEMORY.md` must stay readable by humans without auxiliary tooling

## Rollout Plan

### Phase 1

- Define tagged block format with `[%key:value]`
- Add memory event emission
- Introduce `_MEMBEAT_TOOL`
- Implement `append_history` and `upsert_memory`

### Phase 2

- Add `emit_todo`
- Introduce `TODO.md`
- Introduce `todo_tools`

### Phase 3

- Add memory-agent skill/tools/scripts
- Add explicit user-facing memory commands
- Refine compaction, dedupe, and prioritization

## Open Questions

- What should the `MEMORY.md` merge key granularity be?
- What exact dedupe key should `emit_todo` use?
- Should memory events be batched on a timer, a count, or both?
- When should subagent output be ingested into memory governance?
- Should `MEMORY.md` preserve category headings, or move fully to tagged blocks?

## Recommendation

Implement the system as a governor-style memory architecture:

- main agent remains simple and read-focused
- memory-agent becomes the sole governance boundary
- `_MEMBEAT_TOOL` standardizes model output into safe actions
- file materializers keep the system transparent and reviewable

This preserves nanobot's lightweight file-first philosophy while creating a clear path for
memory tagging, asynchronous consolidation, and TODO projection.
