from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from everos.entrypoints.memo_vault import library as library_module
from everos.entrypoints.memo_vault.adapter import EverOSMemoryRecord
from everos.entrypoints.memo_vault.library import (
    LibraryError,
    MemoVaultLibraryService,
    ProjectNotFound,
)
from everos.entrypoints.memo_vault.storage import VaultStore


class FakeAdapter:
    def __init__(self, records: list[EverOSMemoryRecord]) -> None:
        self.records = records
        self.calls: list[dict[str, str]] = []

    async def list_user_memories(self, **scope: str) -> list[EverOSMemoryRecord]:
        self.calls.append(scope)
        memory_type = scope["memory_type"]
        return [record for record in self.records if record.memory_type == memory_type]


def _seed_memory(
    store: VaultStore,
    *,
    memory_id: str,
    everos_memory_id: str,
    kind: str,
    memory_type: str = "atomic_fact",
    external_use: str = "allow",
    lifecycle_status: str = "active",
    valid_until: str | None = None,
    evidence: bool = False,
) -> None:
    identity = store.get_identity()
    batch_id = f"batch-{memory_id}"
    now = datetime.now(UTC).isoformat()
    with store.connect() as connection:
        connection.execute(
            """INSERT INTO import_batches
               (id, source_name, file_sha256, status, namespace, app_id, project_id,
                user_id, agent_id, raw_relpath)
               VALUES (?, ?, ?, 'archived', 'personal', ?, 'personal', ?, ?, ?)""",
            (
                batch_id,
                f"{memory_id}.txt",
                hashlib.sha256(memory_id.encode()).hexdigest(),
                identity["app_id"],
                identity["user_id"],
                identity["agent_id"],
                "evidence/source.txt",
            ),
        )
        connection.execute(
            """INSERT INTO candidates
               (id, batch_id, everos_scope, everos_memory_id, kind, memory_type,
                content, status, external_use, target_project_id, created_at)
               VALUES (?, ?, 'user', ?, ?, ?, ?, 'confirmed', ?, 'personal', ?)""",
            (
                memory_id,
                batch_id,
                everos_memory_id,
                kind,
                memory_type,
                f"candidate-only-{memory_id}",
                external_use,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO memories
               (id, everos_memory_id, namespace, kind, memory_type, status,
                evidence_kind, external_use, valid_until, lifecycle_status, confirmed_at)
               VALUES (?, ?, 'personal', ?, ?, 'confirmed', 'human_verified', ?, ?, ?, ?)""",
            (
                memory_id,
                everos_memory_id,
                kind,
                memory_type,
                external_use,
                valid_until,
                lifecycle_status,
                now,
            ),
        )
        if evidence:
            connection.execute(
                """INSERT INTO normalized_messages
                   (id, batch_id, conversation_id, ordinal, role, content, content_sha256)
                   VALUES (?, ?, 'conversation-1', 1, 'user', ?, ?)""",
                (
                    f"message-{memory_id}",
                    batch_id,
                    "The user prefers canonical tea every morning.",
                    hashlib.sha256(b"The user prefers canonical tea every morning.").hexdigest(),
                ),
            )
            quote = "The user prefers canonical tea every morning."
            connection.execute(
                """INSERT INTO candidate_evidence
                   (candidate_id, message_id, char_start, char_end, quote, quote_sha256)
                   VALUES (?, ?, 0, ?, ?, ?)""",
                (
                    memory_id,
                    f"message-{memory_id}",
                    len(quote),
                    quote,
                    hashlib.sha256(quote.encode()).hexdigest(),
                ),
            )


def test_pack_sources_use_scoped_canonical_records_and_all_six_kinds(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    records = [
        EverOSMemoryRecord("everos-preference", "atomic_fact", "Canonical preference", "2026-10-20T10:00:00Z", {}),
        EverOSMemoryRecord("everos-fact", "atomic_fact", "Canonical fact", "2026-10-20T11:00:00Z", {}),
        EverOSMemoryRecord("everos-decision", "atomic_fact", "Canonical decision", "2026-10-20T12:00:00Z", {}),
        EverOSMemoryRecord("everos-todo", "atomic_fact", "Canonical todo", "2026-10-20T13:00:00Z", {}),
        EverOSMemoryRecord("everos-episode", "episode", "Canonical episode", "2026-10-20T14:00:00Z", {}),
        EverOSMemoryRecord("profile_user_profile", "profile", "Linked profile entry", None, {"item": {"description": "Linked profile entry"}}),
    ]
    for kind, memory_id, everos_id, memory_type in (
        ("preference", "preference", "everos-preference", "atomic_fact"),
        ("fact", "fact", "everos-fact", "atomic_fact"),
        ("decision", "decision", "everos-decision", "atomic_fact"),
        ("todo", "todo", "everos-todo", "atomic_fact"),
        ("episode", "episode", "everos-episode", "episode"),
        ("profile", "profile", "profile_user_profile", "profile"),
    ):
        _seed_memory(
            store,
            memory_id=memory_id,
            everos_memory_id=everos_id,
            kind=kind,
            memory_type=memory_type,
            evidence=(kind == "preference"),
        )

    adapter = FakeAdapter(records)
    sources = asyncio.run(MemoVaultLibraryService(store, adapter).list_pack_sources("personal"))
    by_id = {source.memory_id: source for source in sources}

    assert {source.kind for source in sources} == {
        "preference", "fact", "decision", "todo", "episode", "profile",
    }
    assert by_id["preference"].content == "Canonical preference"
    assert "candidate-only" not in (by_id["preference"].content or "")
    assert by_id["profile"].content == "Linked profile entry"
    assert by_id["profile"].content != "candidate-only-profile"
    assert all(source.project_id == "personal" for source in sources)
    assert all(source.namespace == "personal" for source in sources)
    assert all(call["app_id"] == store.get_identity()["app_id"] for call in adapter.calls)
    assert all(call["user_id"] == store.get_identity()["user_id"] for call in adapter.calls)
    assert all(call["project_id"] == "personal" for call in adapter.calls)

    evidence = by_id["preference"].evidence[0]
    expected = hashlib.sha256(
        "\0".join(("preference", "message-preference", "0", str(len("The user prefers canonical tea every morning.")), hashlib.sha256(b"The user prefers canonical tea every morning.").hexdigest())).encode()
    ).hexdigest()[:24]
    assert evidence.evidence_id == f"ev_{expected}"
    assert evidence.source_message_id == "message-preference"
    assert evidence.quote == "The user prefers canonical tea every morning."
    assert evidence.matched is True


def test_pack_sources_never_fall_back_or_include_inactive_body(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    _seed_memory(
        store,
        memory_id="missing",
        everos_memory_id="missing-everos",
        kind="fact",
    )
    _seed_memory(
        store,
        memory_id="withdrawn",
        everos_memory_id="withdrawn-everos",
        kind="fact",
        lifecycle_status="withdrawn",
    )
    _seed_memory(
        store,
        memory_id="deleted",
        everos_memory_id="deleted-everos",
        kind="fact",
        lifecycle_status="deleted",
    )

    sources = asyncio.run(MemoVaultLibraryService(store, FakeAdapter([])).list_pack_sources("personal"))
    by_id = {source.memory_id: source for source in sources}
    assert by_id["missing"].content is None
    assert by_id["withdrawn"].content is None
    assert by_id["deleted"].content is None
    assert by_id["missing"].index_available is False
    assert by_id["withdrawn"].lifecycle_status == "withdrawn"
    assert by_id["deleted"].lifecycle_status == "deleted"


def test_pack_sources_preserve_external_use_and_validate_scope_before_adapter(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    _seed_memory(store, memory_id="ask", everos_memory_id="ask-everos", kind="fact", external_use="ask")
    _seed_memory(store, memory_id="deny", everos_memory_id="deny-everos", kind="fact", external_use="deny")
    adapter = FakeAdapter([
        EverOSMemoryRecord("ask-everos", "atomic_fact", "Ask body", None, {}),
        EverOSMemoryRecord("deny-everos", "atomic_fact", "Deny body", None, {}),
    ])
    service = MemoVaultLibraryService(store, adapter)
    sources = asyncio.run(service.list_pack_sources("personal"))
    assert {source.memory_id: source.external_use for source in sources} == {"ask": "ask", "deny": "deny"}
    assert next(source for source in sources if source.memory_id == "deny").content is None

    with pytest.raises(ProjectNotFound):
        asyncio.run(service.list_pack_sources("not-a-project"))
    assert len(adapter.calls) == 1


def test_pack_sources_revalidation_detects_policy_change_during_everos_read(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    _seed_memory(store, memory_id="memory-1", everos_memory_id="everos-1", kind="fact")

    class MutatingAdapter(FakeAdapter):
        async def list_user_memories(self, **scope: str) -> list[EverOSMemoryRecord]:
            records = await super().list_user_memories(**scope)
            with store.connect() as connection:
                connection.execute(
                    "UPDATE memories SET external_use = 'deny' WHERE id = 'memory-1'"
                )
            return records

    service = MemoVaultLibraryService(
        store,
        MutatingAdapter([EverOSMemoryRecord("everos-1", "atomic_fact", "Canonical", None, {})]),
    )
    loaded_sources = asyncio.run(service.list_pack_sources("personal"))

    with pytest.raises(LibraryError) as changed:
        service.revalidate_pack_sources(["personal"], loaded_sources)

    assert changed.value.code == "PACK_SOURCE_CHANGED"
    assert changed.value.status_code == 409


def test_pack_sources_revalidation_recomputes_expiry_at_final_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    expiry = datetime.now(UTC) + timedelta(minutes=1)
    _seed_memory(
        store,
        memory_id="soon-expired",
        everos_memory_id="everos-soon-expired",
        kind="fact",
        valid_until=expiry.isoformat(),
    )
    adapter = FakeAdapter([
        EverOSMemoryRecord("everos-soon-expired", "atomic_fact", "Canonical", None, {})
    ])
    service = MemoVaultLibraryService(store, adapter)
    sources = asyncio.run(service.list_pack_sources("personal"))
    assert sources[0].expiry_status == "valid"

    class FutureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            future = expiry + timedelta(seconds=1)
            return future if tz is None else future.astimezone(tz)

    monkeypatch.setattr(library_module, "datetime", FutureDateTime)
    with pytest.raises(LibraryError) as changed:
        service.revalidate_pack_sources(["personal"], sources)

    assert changed.value.code == "PACK_SOURCE_CHANGED"
