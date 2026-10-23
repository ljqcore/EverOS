from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from everos.config import load_settings
from everos.entrypoints.api.app import create_app


def test_candidate_extraction_api_returns_drafts_without_running_memorize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import everos.entrypoints.api.routes.memo_vault_candidates as route

    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))
    load_settings.cache_clear()
    observed: dict[str, object] = {}

    async def fake_extract(**kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        return [
            {
                "candidate_id": "candidate-1",
                "kind": "fact",
                "content": "User prefers concise responses.",
                "source_message_ids": ["message-1", "message-2"],
            }
        ]

    monkeypatch.setattr(route, "extract_chat_candidates", fake_extract)
    monkeypatch.setattr(route, "get_llm_client", lambda: object())
    app = create_app(lifespan_providers=[])

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/v2/memo-vault/candidates/extract",
                json={
                    "batch_id": "batch-1",
                    "session_id": "session-1",
                    "app_id": "memo-vault",
                    "project_id": "project-a",
                    "user_id": "user-1",
                    "agent_id": "agent-1",
                    "messages": [
                        {
                            "id": "message-1",
                            "role": "user",
                            "content": "Please be concise.",
                            "timestamp_ms": 1000,
                        },
                        {
                            "id": "message-2",
                            "role": "assistant",
                            "content": "Understood.",
                            "timestamp_ms": 1234,
                        },
                    ],
                },
            )

    response = asyncio.run(request())
    load_settings.cache_clear()

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidate_count"] == 1
    assert data["candidates"][0]["kind"] == "fact"
    assert observed["user_id"] == "user-1"
    assert observed["messages"][1]["role"] == "assistant"
    assert "agent_id" not in observed


def test_candidate_extraction_api_rejects_non_chat_roles() -> None:
    from everos.entrypoints.api.app import create_app

    app = create_app(lifespan_providers=[])

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/v2/memo-vault/candidates/extract",
                json={
                    "batch_id": "batch-1",
                    "session_id": "session-1",
                    "app_id": "memo-vault",
                    "project_id": "project-a",
                    "user_id": "user-1",
                    "agent_id": "agent-1",
                    "messages": [
                        {
                            "id": "message-1",
                            "role": "system",
                            "content": "system prompt",
                            "timestamp_ms": 1000,
                        }
                    ],
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422


def test_candidate_extraction_maps_invalid_atomic_fact_output_to_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import everos.entrypoints.api.routes.memo_vault_candidates as route
    from everos.service.memo_vault_candidates import CandidateExtractionFormatError

    async def fail_extraction(**kwargs):  # type: ignore[no-untyped-def]
        raise CandidateExtractionFormatError("invalid model output")

    monkeypatch.setattr(route, "load_settings", lambda: SimpleNamespace(
        boundary_detection=SimpleNamespace(hard_token_limit=4096, hard_msg_limit=50)
    ))
    monkeypatch.setattr(route, "get_llm_client", lambda: object())
    monkeypatch.setattr(route, "extract_chat_candidates", fail_extraction)
    app = create_app(lifespan_providers=[])

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/v2/memo-vault/candidates/extract",
                json={
                    "batch_id": "batch-1",
                    "session_id": "session-1",
                    "app_id": "memo-vault",
                    "project_id": "project-a",
                    "user_id": "user-1",
                    "agent_id": "agent-1",
                    "messages": [{
                        "id": "message-1",
                        "role": "user",
                        "content": "Please be concise.",
                        "timestamp_ms": 1000,
                    }],
                },
            )

    response = asyncio.run(request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNAVAILABLE"
    assert "可以稍后重试" in response.json()["error"]["message"]


def test_candidate_extraction_reports_missing_llm_config_without_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import everos.entrypoints.api.routes.memo_vault_candidates as route

    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))

    def fail_llm_client() -> object:
        raise route.LLMNotConfiguredError("missing local LLM config")

    monkeypatch.setattr(
        route,
        "get_llm_client",
        fail_llm_client,
    )
    monkeypatch.setattr(
        route,
        "load_settings",
        lambda: SimpleNamespace(
            boundary_detection=SimpleNamespace(hard_token_limit=4096, hard_msg_limit=50)
        ),
    )
    app = create_app(lifespan_providers=[])

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/v2/memo-vault/candidates/extract",
                json={
                    "batch_id": "batch-1",
                    "session_id": "session-1",
                    "app_id": "memo-vault",
                    "project_id": "project-a",
                    "user_id": "user-1",
                    "agent_id": "agent-1",
                    "messages": [{
                        "id": "message-1",
                        "role": "user",
                        "content": "Please be concise.",
                        "timestamp_ms": 1000,
                    }],
                },
            )

    response = asyncio.run(request())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert "section [llm]" in response.json()["error"]["message"]


def test_approved_candidate_publish_is_idempotent_and_writes_exact_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import everos.entrypoints.api.routes.memo_vault_candidates as route

    class Root:
        def __init__(self) -> None:
            self.root = tmp_path

        @classmethod
        def resolve(cls):  # type: ignore[no-untyped-def]
            return cls()

    writes: list[dict[str, object]] = []

    class Writer:
        def __init__(self, *, root: Root) -> None:
            pass

        async def append_entry(
            self, scope_id: str, **kwargs
        ):  # type: ignore[no-untyped-def]
            writes.append({"scope_id": scope_id, **kwargs})
            return type("EntryId", (), {"format": lambda self: "af_20261020_0001"})()

    monkeypatch.setattr(route, "MemoryRoot", Root)
    monkeypatch.setattr(route, "AtomicFactWriter", Writer)
    app = create_app(lifespan_providers=[])

    async def request() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {
                "candidate_id": "candidate-1",
                "app_id": "memo-vault",
                "project_id": "project-a",
                "user_id": "user-1",
                "content": "User prefers concise responses.",
            }
            first = await client.post(
                "/api/v2/memo-vault/candidates/candidate-1/publish", json=body
            )
            second = await client.post(
                "/api/v2/memo-vault/candidates/candidate-1/publish", json=body
            )
            return first, second

    first, second = asyncio.run(request())
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"] == second.json()["data"]
    assert len(writes) == 1
    assert writes[0]["scope_id"] == "user-1"
    assert writes[0]["sections"] == {"Fact": "User prefers concise responses."}
    assert writes[0]["app_id"] == "memo-vault"
    assert writes[0]["project_id"] == "project-a"


def test_episode_and_profile_publication_use_their_native_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import everos.entrypoints.api.routes.memo_vault_candidates as route

    class Root:
        def __init__(self) -> None:
            self.root = tmp_path

        @classmethod
        def resolve(cls):  # type: ignore[no-untyped-def]
            return cls()

    episode_writes: list[dict[str, object]] = []
    profile_writes: list[object] = []

    class EpisodeWriter:
        def __init__(self, *, root):  # type: ignore[no-untyped-def]
            pass

        async def append_entry(self, scope_id, **kwargs):  # type: ignore[no-untyped-def]
            episode_writes.append({"scope_id": scope_id, **kwargs})
            return type("EntryId", (), {"format": lambda self: "ep_20261020_0001"})()

    class ProfileReader:
        def __init__(self, *, root):  # type: ignore[no-untyped-def]
            pass

        async def read(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    class ProfileWriter:
        def __init__(self, *, root):  # type: ignore[no-untyped-def]
            pass

        async def write(self, scope_id, *, frontmatter, body, app_id, project_id):  # type: ignore[no-untyped-def]
            profile_writes.append(frontmatter)

    monkeypatch.setattr(route, "MemoryRoot", Root)
    monkeypatch.setattr(route, "EpisodeWriter", EpisodeWriter)
    monkeypatch.setattr(route, "ProfileReader", ProfileReader)
    monkeypatch.setattr(route, "ProfileWriter", ProfileWriter)
    app = create_app(lifespan_providers=[])

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            common = {"app_id": "memo-vault", "project_id": "project-a", "user_id": "user-1"}
            episode = await client.post("/api/v2/memo-vault/candidates/ep-1/publish", json={
                **common, "candidate_id": "ep-1", "content": "用户讨论了项目计划。",
                "memory_type": "episode", "metadata": {"title": "项目计划", "timestamp_ms": 1234},
            })
            assert episode.status_code == 200, episode.text
            assert episode.json()["data"]["memory_id"] == "user-1_ep_20261020_0001"
            profile_body = {
                **common, "candidate_id": "profile-1", "content": "用户偏好简洁回答。",
                "memory_type": "profile", "metadata": {
                    "section": "explicit_info", "item": {"category": "偏好", "description": "用户偏好简洁回答。", "evidence": "请简洁回答"}, "timestamp_ms": 1234,
                },
            }
            profile = await client.post("/api/v2/memo-vault/candidates/profile-1/publish", json=profile_body)
            repeated = await client.post("/api/v2/memo-vault/candidates/profile-1/publish", json=profile_body)
            assert profile.status_code == 200, profile.text
            assert repeated.status_code == 200
            assert profile.json()["data"] == repeated.json()["data"]

    asyncio.run(scenario())
    assert episode_writes[0]["sections"] == {"Subject": "项目计划", "Content": "用户讨论了项目计划。"}
    assert len(profile_writes) == 1
    assert profile_writes[0].explicit_info[0]["description"] == "用户偏好简洁回答。"


