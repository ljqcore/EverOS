import asyncio
import json
from types import SimpleNamespace

from everos.entrypoints.memo_vault.contracts import ManualCandidateRequest
from everos.entrypoints.memo_vault.routes.candidates import create_manual_candidate
from everos.entrypoints.memo_vault.storage import VaultStore


def test_manual_profile_has_native_type_and_publish_metadata(tmp_path):
    store = VaultStore(tmp_path)
    store.initialize()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(vault_store=store)))
    result = asyncio.run(create_manual_candidate(
        ManualCandidateRequest(kind="preference", namespace="personal", content="用户喜欢简洁中文回答。"), request,
    ))
    assert result.data["memory_type"] == "profile"
    assert result.data["origin"] == "manual"
    with store.connect() as connection:
        row = connection.execute("SELECT memory_type, metadata_json FROM candidates WHERE id = ?", (result.data["id"],)).fetchone()
    assert row["memory_type"] == "profile"
    metadata = json.loads(row["metadata_json"])
    assert metadata["section"] == "explicit_info"
    assert metadata["item"]["description"] == result.data["content"]
    assert metadata["timestamp_ms"] > 0
