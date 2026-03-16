from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.memory_governor.service import MemoryGovernorService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class EndToEndProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "model": model})

        tool_names = {
            tool.get("function", {}).get("name") for tool in (tools or []) if isinstance(tool, dict)
        }

        if "membeat" in tool_names:
            prompt = str(messages[-1]["content"])
            if "remember apples" not in prompt or "assistant stores apples" not in prompt:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            id="mb_noop",
                            name="membeat",
                            arguments={"actions": [{"kind": "noop", "id": "noop-1"}]},
                        )
                    ],
                )

            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="mb_1",
                        name="membeat",
                        arguments={
                            "actions": [
                                {
                                    "kind": "append_history",
                                    "id": "a1",
                                    "timestamp": "2026-03-16 10:00",
                                    "type": "decision",
                                    "tags": ["project"],
                                    "source": "cli:test",
                                    "importance": "high",
                                    "body": "remember apples -> assistant stores apples",
                                },
                                {
                                    "kind": "upsert_memory",
                                    "id": "m1",
                                    "merge_key": "fact:apples",
                                    "type": "fact",
                                    "tags": ["fact"],
                                    "source": "history:2026-03-16T10:00",
                                    "importance": "high",
                                    "body": "assistant stores apples",
                                },
                            ]
                        },
                    )
                ],
            )

        return LLMResponse(content="assistant stores apples", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_process_direct_runs_phase1_governor_flow_end_to_end(tmp_path: Path) -> None:
    provider = EndToEndProvider()
    governor = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_governor=governor,
        context_window_tokens=65_536,
    )

    original_maybe_consolidate = loop.memory_consolidator.maybe_consolidate_by_tokens
    loop.memory_consolidator.maybe_consolidate_by_tokens = AsyncMock(
        wraps=original_maybe_consolidate
    )

    response = await loop.process_direct("remember apples", session_key="cli:test")

    history_text = (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    memory_text = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    assert response == "assistant stores apples"
    assert "remember apples -> assistant stores apples" in history_text
    assert "assistant stores apples" in memory_text
    assert loop.memory_consolidator.maybe_consolidate_by_tokens.await_count == 2


@pytest.mark.asyncio
async def test_governor_prompt_includes_structured_event_evidence(tmp_path: Path) -> None:
    provider = EndToEndProvider()
    governor = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_governor=governor,
        context_window_tokens=65_536,
    )

    await loop.process_direct("remember apples", session_key="cli:test")

    governor_call = next(
        call
        for call in provider.calls
        if {tool.get("function", {}).get("name") for tool in (call["tools"] or [])} == {"membeat"}
    )
    system_prompt = str(governor_call["messages"][0]["content"])
    user_prompt = str(governor_call["messages"][1]["content"])

    assert "memory governor" in system_prompt.lower()
    assert "deterministic" in system_prompt.lower()
    assert "session_key: cli:test" in user_prompt
    assert "channel: cli" in user_prompt
    assert "chat_id: direct" in user_prompt
    assert "message_count: 2" in user_prompt
    assert "use the recent turn messages as evidence" in user_prompt.lower()
    assert "turn_messages:" in user_prompt
    assert "USER: remember apples" in user_prompt
    assert "ASSISTANT: assistant stores apples" in user_prompt
