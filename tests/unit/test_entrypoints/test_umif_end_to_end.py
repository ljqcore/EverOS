"""Redacted in-process acceptance for the whole reviewed Memory Pack path."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from everos.entrypoints.memo_vault.adapter import EverOSMemoryRecord, EverOSMemoryRef
from everos.entrypoints.memo_vault.app import app


def _zip(payload: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("session.v4.jsonl", payload)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_redacted_harness_zip_to_review_and_markdown_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import everos.entrypoints.memo_vault.routes.imports as import_routes
    monkeypatch.setenv("MEMO_VAULT_DATA_DIR", str(tmp_path / "vault"))

    class LocalEverOS:
        def __init__(self) -> None:
            self.published: str | None = None

        async def extract_import(self, **kwargs):  # type: ignore[no-untyped-def]
            message = next(m for m in kwargs["messages"] if m["role"] == "user")
            return {"status": "extracted", "method": "local", "candidate_count": 1,
                    "candidate_scope": {"app_id": kwargs["app_id"], "project_id": kwargs["project_id"], "user_id": kwargs["user_id"]},
                    "candidates": [{"candidate_id": "umif-review-1", "kind": "fact", "content": message["content"],
                                    "source_message_ids": [message["id"]]}],
                    "deferred_tool_message_count": 0, "unsupported_role_message_count": 0}

        async def publish_approved(self, **kwargs):  # type: ignore[no-untyped-def]
            self.published = kwargs["content"]
            return EverOSMemoryRef("everos-umif-review-1", kwargs["scope"], kwargs["content"], 1)

        async def list_user_memories(self, **kwargs):  # type: ignore[no-untyped-def]
            if self.published is None: return []
            if kwargs["memory_type"] != "atomic_fact": return []
            return [EverOSMemoryRecord("everos-umif-review-1", "atomic_fact", self.published,
                                       "2026-10-23T00:00:00Z", {})]

    fake = LocalEverOS()
    monkeypatch.setattr(import_routes, "EverOSHttpAdapter", lambda *_args, **_kwargs: fake)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        app.state.everos_adapter = fake
        payload = _zip(Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl").read_bytes())
        preview = await client.post("/api/v1/imports/preview",
            data={"source_type": "deepseek_harness", "project_id": "personal"},
            files={"file": ("export.zip", payload, "application/zip")})
        assert preview.status_code == 200, preview.text
        batch = await client.post("/api/v1/imports/commit", json={"preview_id": preview.json()["data"]["preview_id"], "project_id": "personal"})
        assert batch.status_code == 200, batch.text
        batch_id = batch.json()["data"]["batch_id"]
        extracted = await client.post(f"/api/v1/imports/{batch_id}/extract")
        assert extracted.status_code == 200, extracted.text
        assert extracted.json()["data"]["candidate_count"] == 1
        assert fake.published is None
        approved = await client.post("/api/v1/candidates/umif-review-1/confirm",
            json={"revision": 1, "kind": "fact", "namespace": "personal", "external_use": "allow", "evidence_kind": "human_verified"})
        assert approved.status_code == 200, approved.text
        assert fake.published is not None
        request = {"namespaces": ["personal"], "kinds": ["fact"], "format": "markdown",
                   "token_budget": 4000, "evidence_mode": "id", "memory_ids": ["umif-review-1"]}
        pack_preview = await client.post("/api/v1/packs/preview", json=request)
        assert pack_preview.status_code == 200, pack_preview.text
        data = pack_preview.json()["data"]
        assert data["included_count"] == 1
        exported = await client.post("/api/v1/packs/export", json={**request,
            "preview_sha256": data["preview_sha256"], "preview_generated_at": data["generated_at"],
            "confirmed_ask_ids": [], "confirm_evidence": False,
            "confirm_unrecoverable_transfer": True, "delivery_action": "download"})
        assert exported.status_code == 200, exported.text
        assert fake.published in exported.json()["data"]["rendered_content"]
