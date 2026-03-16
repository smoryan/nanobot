from nanobot.agent.memory import _MEMBEAT_TOOL, normalize_membeat_actions


def test_membeat_tool_exposes_allowed_actions() -> None:
    function = _MEMBEAT_TOOL[0]["function"]

    assert function["name"] == "membeat"
    actions = function["parameters"]["properties"]["actions"]["items"]["properties"]["kind"]["enum"]
    assert actions == ["append_history", "upsert_memory", "emit_todo", "noop"]


def test_normalize_membeat_actions_accepts_valid_payload() -> None:
    payload = {
        "actions": [
            {
                "kind": "append_history",
                "id": "a1",
                "timestamp": "2026-03-16 10:00",
                "type": "decision",
                "tags": ["project"],
                "source": "cli:alice",
                "importance": "high",
                "body": "Hello",
            }
        ]
    }

    actions = normalize_membeat_actions(payload)
    assert actions[0]["kind"] == "append_history"
