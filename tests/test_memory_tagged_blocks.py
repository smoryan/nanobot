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
