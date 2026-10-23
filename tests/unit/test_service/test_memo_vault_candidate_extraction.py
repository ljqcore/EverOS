from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import everos.service.memo_vault_candidates as extraction
from everalgo.types import MemCell


def test_candidate_extraction_keeps_chat_under_user_and_returns_source_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def detect(messages, **kwargs):  # type: ignore[no-untyped-def]
        seen["messages"] = messages
        seen["boundary_kwargs"] = kwargs
        return SimpleNamespace(
            cells=[MemCell(items=messages, timestamp=messages[-1].timestamp)]
        )

    class EpisodeExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract(
            self, cell, *, sender_id
        ):  # type: ignore[no-untyped-def]
            seen["episode_sender_id"] = sender_id
            return SimpleNamespace(
                episode="用户要求简洁回答。", subject="回答风格", timestamp=1234
            )

    class AtomicFactExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract_from_text(
            self, text, *, timestamp, prompt
        ):  # type: ignore[no-untyped-def]
            seen["fact_input"] = text
            seen["fact_prompt"] = prompt
            return [SimpleNamespace(content="用户偏好简洁回答。")]

    class ProfileExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract(self, memcells, *, sender_id, old_profile):  # type: ignore[no-untyped-def]
            seen["profile_messages"] = [item for cell in memcells for item in cell.items]
            seen["profile_sender_id"] = sender_id
            return SimpleNamespace(
                explicit_info=[{"category": "偏好", "description": "用户偏好简洁回答。", "evidence": "Please be concise."}],
                implicit_traits=[],
                timestamp=1234,
            )

    monkeypatch.setattr(extraction, "detect_boundaries", detect)
    monkeypatch.setattr(extraction, "EpisodeExtractor", EpisodeExtractor)
    monkeypatch.setattr(extraction, "AtomicFactExtractor", AtomicFactExtractor)
    monkeypatch.setattr(extraction, "ProfileExtractor", ProfileExtractor)

    candidates = asyncio.run(extraction.extract_chat_candidates(
        batch_id="batch-1",
        session_id="session-1",
        user_id="user-1",
        messages=[
            {
                "id": "message-user",
                "role": "user",
                "content": "Please be concise.",
                "timestamp_ms": 1000,
            },
            {
                "id": "message-assistant",
                "role": "assistant",
                "content": "Understood.",
                "timestamp_ms": 1234,
            },
        ],
        llm_client=object(),
        prompt_loader=SimpleNamespace(load=lambda name: f"prompt:{name}"),
        hard_token_limit=4096,
        hard_msg_limit=50,
    ))

    messages = seen["messages"]
    assert [message.role for message in messages] == ["user", "assistant"]
    assert {message.sender_id for message in messages} == {"user-1"}
    assert seen["episode_sender_id"] is None
    assert [item.role for item in seen["profile_messages"]] == ["user", "assistant"]
    assert seen["profile_sender_id"] == "user-1"
    assert [(item["memory_type"], item["kind"], item["content"]) for item in candidates] == [
        ("episode", "episode", "用户要求简洁回答。"),
        ("atomic_fact", "preference", "用户偏好简洁回答。"),
    ]
    assert candidates[0]["source_message_ids"] == ["message-user", "message-assistant"]
    assert candidates[1]["source_message_ids"] == ["message-user", "message-assistant"]
    assert candidates[1]["metadata"]["category"] == "偏好"


def test_candidate_extraction_retries_malformed_atomic_fact_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def detect(messages, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            cells=[MemCell(items=messages, timestamp=messages[-1].timestamp)]
        )

    class EpisodeExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract(self, cell, *, sender_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(episode="用户希望回答简洁。", subject="回答风格", timestamp=1234)

    class AtomicFactExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract_from_text(self, text, *, timestamp, prompt):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise json.JSONDecodeError("Unterminated string", '{"atomic_facts":', 16)
            return [SimpleNamespace(content="用户希望回答简洁。")]

    class ProfileExtractor:
        def __init__(self, *, llm):  # type: ignore[no-untyped-def]
            pass

        async def aextract(self, memcells, *, sender_id, old_profile):  # type: ignore[no-untyped-def]
            return SimpleNamespace(explicit_info=[], implicit_traits=[], timestamp=1234)

    monkeypatch.setattr(extraction, "detect_boundaries", detect)
    monkeypatch.setattr(extraction, "EpisodeExtractor", EpisodeExtractor)
    monkeypatch.setattr(extraction, "AtomicFactExtractor", AtomicFactExtractor)
    monkeypatch.setattr(extraction, "ProfileExtractor", ProfileExtractor)

    candidates = asyncio.run(extraction.extract_chat_candidates(
        batch_id="batch-1",
        session_id="session-1",
        user_id="user-1",
        messages=[{
            "id": "message-user",
            "role": "user",
            "content": "Please be concise.",
            "timestamp_ms": 1000,
        }],
        llm_client=object(),
        prompt_loader=SimpleNamespace(load=lambda name: f"prompt:{name}"),
        hard_token_limit=4096,
        hard_msg_limit=50,
    ))

    assert attempts == 0
    assert [(candidate["memory_type"], candidate["content"]) for candidate in candidates] == [
        ("episode", "用户希望回答简洁。"),
    ]


def test_candidate_extraction_stops_after_repeated_invalid_atomic_fact_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class AtomicFactExtractor:
        async def aextract_from_text(self, text, *, timestamp):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            raise json.JSONDecodeError("Unterminated string", '{"atomic_facts":', 16)

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(extraction.asyncio, "sleep", no_wait)

    with pytest.raises(extraction.CandidateExtractionFormatError):
        asyncio.run(
            extraction._extract_atomic_facts_with_retry(
                AtomicFactExtractor(), "episode text", timestamp=1234
            )
        )

    assert attempts == extraction._ATOMIC_FACT_MAX_ATTEMPTS == 3
