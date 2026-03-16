from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nanobot.agent.memory import MemoryEvent
from nanobot.memory_governor.service import MemoryGovernorService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_decide_returns_membeat_actions(tmp_path) -> None:
    provider = DummyProvider(
        [
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
        ]
    )

    service = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")

    actions = await service.decide_actions("prompt")

    assert actions == [{"kind": "noop", "id": "noop-1"}]


@pytest.mark.asyncio
async def test_handle_event_decides_and_applies_actions(tmp_path) -> None:
    provider = DummyProvider([])
    service = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")
    service.decide_actions = AsyncMock(return_value=[{"kind": "noop", "id": "noop-1"}])
    service.apply_actions = AsyncMock(return_value=None)

    await service.handle_event(
        MemoryEvent(
            session_key="cli:test",
            channel="cli",
            chat_id="direct",
            message_count=2,
        )
    )

    service.decide_actions.assert_awaited_once()
    service.apply_actions.assert_awaited_once_with([{"kind": "noop", "id": "noop-1"}])


@pytest.mark.asyncio
async def test_decide_actions_returns_empty_without_tool_calls(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool", tool_calls=[])])
    service = MemoryGovernorService(workspace=tmp_path, provider=provider, model="test-model")

    actions = await service.decide_actions("prompt")

    assert actions == []
