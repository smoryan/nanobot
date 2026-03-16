from pathlib import Path

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.memory_governor.service import MemoryGovernorService


def test_apply_append_history_action_writes_tagged_block(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    store.apply_membeat_action(
        {
            "kind": "append_history",
            "id": "a1",
            "timestamp": "2026-03-16 10:00",
            "type": "decision",
            "tags": ["project"],
            "source": "cli:alice",
            "importance": "high",
            "body": "Adopt governor design.",
        }
    )

    assert "[%type: decision]" in store.history_file.read_text(encoding="utf-8")


def test_apply_upsert_memory_action_writes_memory_file(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    store.apply_membeat_action(
        {
            "kind": "upsert_memory",
            "id": "m1",
            "merge_key": "project:governor-style",
            "type": "project",
            "tags": ["project", "constraint"],
            "source": "history:2026-03-16T10:00",
            "importance": "high",
            "body": "Use governor-style memory-agent.",
        }
    )

    assert "Use governor-style memory-agent." in store.memory_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_service_apply_actions_materializes_with_store(tmp_path: Path) -> None:
    service = MemoryGovernorService(workspace=tmp_path, provider=None, model="test-model")

    await service.apply_actions(
        [
            {
                "kind": "append_history",
                "id": "a1",
                "timestamp": "2026-03-16 10:00",
                "type": "decision",
                "tags": ["project"],
                "source": "cli:alice",
                "importance": "high",
                "body": "Adopt governor design.",
            }
        ]
    )

    history_text = (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    assert "Adopt governor design." in history_text
