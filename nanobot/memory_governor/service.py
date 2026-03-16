from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent import memory as memory_module
from nanobot.agent.memory import MemoryEvent, MemoryStore
from nanobot.providers.base import LLMProvider


class MemoryGovernorService:
    def __init__(self, workspace: Path, provider: LLMProvider | None, model: str):
        self.workspace = workspace
        self.provider = provider
        self.model = model

    async def decide_actions(self, prompt: str) -> list[dict[str, Any]]:
        if self.provider is None:
            raise ValueError("provider is required to decide actions")

        response = await self.provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You are a memory governor. Call the membeat tool to report actions.",
                },
                {"role": "user", "content": prompt},
            ],
            tools=memory_module._MEMBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return []

        return memory_module.normalize_membeat_actions(response.tool_calls[0].arguments)

    async def apply_actions(self, actions: list[dict[str, Any]]) -> None:
        store = MemoryStore(self.workspace)
        for action in actions:
            store.apply_membeat_action(action)

    async def handle_event(self, event: MemoryEvent) -> None:
        actions = await self.decide_actions(
            "\n".join(
                [
                    "Review the memory event and report membeat actions.",
                    f"session_key: {event.session_key}",
                    f"channel: {event.channel}",
                    f"chat_id: {event.chat_id}",
                    f"message_count: {event.message_count}",
                    f"timestamp: {event.timestamp.isoformat()}",
                ]
            )
        )
        await self.apply_actions(actions)
