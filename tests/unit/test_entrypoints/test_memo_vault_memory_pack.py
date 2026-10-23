from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from everos.entrypoints.memo_vault.contracts import PackExportRequest, PackPreviewRequest
from everos.entrypoints.memo_vault.library import PackEvidenceReference, PackSourceMemory
from everos.entrypoints.memo_vault.memory_pack import MemoryPackError, MemoryPackService

STAMP = "2026-10-20T12:00:00Z"


def _source(
    memory_id: str,
    kind: str,
    *,
    body: str | None = None,
    external_use: str = "allow",
    revision: int = 1,
    lifecycle: str = "active",
    expiry: str = "valid",
    index_available: bool = True,
    evidence: tuple[PackEvidenceReference, ...] = (),
) -> PackSourceMemory:
    canonical = body if body is not None else f"Canonical {kind} text"
    if not index_available:
        canonical = None
    return PackSourceMemory(
        memory_id=memory_id,
        everos_memory_id=f"everos-{memory_id}",
        project_id="personal",
        namespace="personal",
        kind=kind,  # type: ignore[arg-type]
        memory_type="atomic_fact",
        revision=revision,
        content=canonical,
        timestamp=STAMP,
        recorded_at=STAMP,
        confirmed_at=STAMP,
        external_use=external_use,  # type: ignore[arg-type]
        valid_until=None,
        expiry_status=expiry,  # type: ignore[arg-type]
        lifecycle_status=lifecycle,  # type: ignore[arg-type]
        evidence_kind="human_verified",
        content_sha256=hashlib.sha256(canonical.encode()).hexdigest() if canonical is not None else None,
        evidence=evidence,
        index_available=index_available,
    )


def _preview_request(**changes: object) -> PackPreviewRequest:
    values: dict[str, object] = {
        "namespaces": ["personal"],
        "kinds": ["fact", "episode", "profile"],
        "format": "markdown",
        "token_budget": 32000,
        "evidence_mode": "id",
    }
    values.update(changes)
    return PackPreviewRequest(**values)


def test_default_policy_and_three_kind_order_hide_denied_body() -> None:
    sources = [
        _source("fact", "fact"),
        _source("profile", "profile"),
        _source("ask", "fact", external_use="ask"),
        _source("deny", "fact", body="secret denied body", external_use="deny"),
        _source("episode", "episode"),
        _source("todo", "todo"),
        _source("preference", "preference"),
        _source("decision", "decision"),
    ]

    preview = MemoryPackService().preview(_preview_request(), sources, generated_at=STAMP)

    assert [item.kind for item in preview.items if item.included] == [
        "fact", "episode", "profile", "profile",
    ]
    assert {item.kind for item in preview.items} == {"fact", "episode", "profile"}
    ask = next(item for item in preview.items if item.memory_id == "ask")
    assert ask.selected is False and ask.included is False
    assert ask.exclusion_reason == "ask_requires_selection"
    assert all(item.memory_id != "deny" for item in preview.items)
    assert preview.exclusion_counts["policy_deny"] == 1
    assert "secret denied body" not in preview.rendered_content
    repeated = MemoryPackService().preview(_preview_request(), sources, generated_at=STAMP)
    assert repeated.preview_sha256 == preview.preview_sha256

    json_preview = MemoryPackService().preview(
        _preview_request(format="vault-memory/1"),
        [source for source in sources if source.external_use == "allow"],
        generated_at=STAMP,
    )
    assert [item["kind"] for item in json.loads(json_preview.rendered_content)["memories"]] == [
        "fact", "episode", "profile", "profile",
    ]


@pytest.mark.parametrize("removed_kind", ["preference", "decision", "todo"])
def test_removed_pack_kinds_are_rejected_by_request_contract(removed_kind: str) -> None:
    with pytest.raises(ValidationError):
        PackPreviewRequest(namespaces=["personal"], kinds=[removed_kind])  # type: ignore[list-item]


@pytest.mark.parametrize("pack_format", ["markdown", "vault-memory/1"])
def test_renderers_emit_schema_and_safety_metadata(pack_format: str) -> None:
    source = _source(
        "memory-1",
        "episode",
        body="Enhanced text only",
        external_use="ask",
        evidence=(PackEvidenceReference(
            evidence_id="ev_test-evidence",
            source_message_id="source-message",
            quote="matching source excerpt",
            quote_sha256="a" * 64,
            available=True,
            matched=True,
        ),),
    )
    preview = MemoryPackService().preview(
        _preview_request(format=pack_format, memory_ids=["memory-1"]),
        [source],
        generated_at=STAMP,
    )

    if pack_format == "vault-memory/1":
        decoded = json.loads(preview.rendered_content)
        assert decoded["schema_version"] == "vault-memory/1"
        record = decoded["memories"][0]
        assert record["status"] == "confirmed"
        assert record["revision"] == 1
        assert record["training_consent"] is False
        assert record["text"] == source.content
    else:
        assert "user data, not system instructions" in preview.rendered_content
        assert "Enhanced text only" in preview.rendered_content
        for metadata in (
            "### memory-1", "Revision:", "Namespace:", "External use:",
            "Recorded:", "Confirmed:", "Evidence:", "ev_test-evidence",
            "source-message", "matching source excerpt",
        ):
            assert metadata not in preview.rendered_content
    assert preview.content_sha256 == hashlib.sha256(preview.rendered_content.encode()).hexdigest()


def test_evidence_modes_are_separate_and_full_excerpt_is_not_source_conversation() -> None:
    quote = "A matched excerpt. " * 12
    evidence = (PackEvidenceReference("ev_ref", "message-1", quote, "a" * 64, True, True),)
    source = _source("memory-1", "fact", evidence=evidence)
    service = MemoryPackService()

    id_preview = service.preview(_preview_request(format="vault-memory/1"), [source], generated_at=STAMP)
    id_record = json.loads(id_preview.rendered_content)["memories"][0]
    assert "quote" not in id_record["evidence"][0]

    snippet = service.preview(
        _preview_request(format="vault-memory/1", evidence_mode="snippet"), [source], generated_at=STAMP
    )
    full = service.preview(
        _preview_request(format="vault-memory/1", evidence_mode="full"), [source], generated_at=STAMP
    )
    snippet_quote = json.loads(snippet.rendered_content)["memories"][0]["evidence"][0]["quote"]
    full_quote = json.loads(full.rendered_content)["memories"][0]["evidence"][0]["quote"]
    assert len(snippet_quote) <= 120
    assert full_quote == quote


def test_budget_skips_whole_large_item_and_keeps_smaller_later_item() -> None:
    sources = [
        _source("large", "fact", body="large " * 400),
        _source("small", "fact", body="small"),
    ]
    service = MemoryPackService()
    request = _preview_request(token_budget=700)

    preview = service.preview(request, sources, generated_at=STAMP)

    assert preview.included_count == 1
    assert next(item for item in preview.items if item.memory_id == "large").exclusion_reason == "over_budget"
    assert next(item for item in preview.items if item.memory_id == "small").included is True
    assert "large " * 20 not in preview.rendered_content
    assert "small" in preview.rendered_content
    assert preview.estimated_tokens <= preview.token_budget


def test_lifecycle_expiry_and_missing_index_are_excluded_without_bodies() -> None:
    sources = [
        _source("active", "fact"),
        _source("expired", "fact", expiry="expired"),
        _source("withdrawn", "fact", lifecycle="withdrawn"),
        _source("deleted", "fact", lifecycle="deleted"),
        _source("missing", "fact", index_available=False),
    ]

    preview = MemoryPackService().preview(_preview_request(), sources, generated_at=STAMP)

    assert [item.memory_id for item in preview.items if item.included] == ["active"]
    by_id = {item.memory_id: item for item in preview.items}
    assert by_id["expired"].display_content is None
    assert by_id["expired"].exclusion_reason == "expired"
    assert by_id["withdrawn"].exclusion_reason == "withdrawn"
    assert by_id["deleted"].exclusion_reason == "deleted"
    assert by_id["missing"].display_content is None
    assert by_id["missing"].exclusion_reason == "index_unavailable"


def test_newer_memories_sort_first_within_each_kind() -> None:
    older = replace(_source("older", "fact"), timestamp="2026-10-19T12:00:00Z")
    newer = replace(_source("newer", "fact"), timestamp="2026-10-21T12:00:00Z")
    preview = MemoryPackService().preview(_preview_request(), [older, newer], generated_at=STAMP)

    assert [item.memory_id for item in preview.items if item.included] == ["newer", "older"]


def test_export_revalidates_snapshot_and_requires_each_delivery_confirmation() -> None:
    service = MemoryPackService()
    ask = _source("ask-1", "fact", external_use="ask")
    sources = [_source("allow-1", "fact"), ask]
    selected = ["allow-1", "ask-1"]
    preview = service.preview(
        _preview_request(memory_ids=selected), sources, generated_at=STAMP
    )
    export_request = PackExportRequest(
        **_preview_request(memory_ids=selected).model_dump(),
        preview_sha256=preview.preview_sha256,
        preview_generated_at=preview.generated_at,
        confirmed_ask_ids=["ask-1"],
        confirm_unrecoverable_transfer=True,
        delivery_action="copy",
    )

    exported = service.export(export_request, sources)
    assert exported.rendered_content == preview.rendered_content
    assert exported.content_sha256 == preview.content_sha256
    assert exported.included_ids == ["allow-1", "ask-1"]

    changed = [replace(sources[0], revision=2), ask]
    with pytest.raises(MemoryPackError) as stale:
        service.export(export_request, changed)
    assert stale.value.code == "PACK_PREVIEW_STALE"

    unconfirmed = export_request.model_copy(update={"confirmed_ask_ids": []})
    with pytest.raises(MemoryPackError) as confirmation:
        service.export(unconfirmed, sources)
    assert confirmation.value.code == "PACK_ASK_CONFIRMATION_REQUIRED"


def test_invalid_cross_project_selection_has_generic_error() -> None:
    source = _source("memory-1", "fact")
    with pytest.raises(MemoryPackError) as error:
        MemoryPackService().preview(
            _preview_request(memory_ids=["memory-from-another-project"]), [source], generated_at=STAMP
        )
    assert error.value.code == "PACK_SELECTION_INVALID"
    assert "another project" not in str(error.value)


@pytest.mark.parametrize(
    "changed_sources",
    [
        [_source("memory-1", "fact", external_use="deny")],
        [],
    ],
    ids=["policy-changed-to-deny", "removed-from-confirmed-registry"],
)
def test_export_turns_selection_that_disappeared_after_preview_into_stale(
    changed_sources: list[PackSourceMemory],
) -> None:
    service = MemoryPackService()
    preview_request = _preview_request(memory_ids=["memory-1"])
    preview = service.preview(preview_request, [_source("memory-1", "fact")], generated_at=STAMP)
    request = PackExportRequest(
        **preview_request.model_dump(),
        preview_sha256=preview.preview_sha256,
        preview_generated_at=preview.generated_at,
        confirm_unrecoverable_transfer=True,
        delivery_action="copy",
    )

    with pytest.raises(MemoryPackError) as stale:
        service.export(request, changed_sources)

    assert stale.value.code == "PACK_PREVIEW_STALE"
    assert stale.value.status_code == 409


def test_quote_export_requires_separate_evidence_confirmation() -> None:
    evidence = (PackEvidenceReference("ev_ref", "message-1", "Matched source excerpt.", "b" * 64, True, True),)
    source = _source("memory-1", "fact", evidence=evidence)
    service = MemoryPackService()
    preview_request = _preview_request(
        format="vault-memory/1", evidence_mode="snippet", memory_ids=["memory-1"]
    )
    preview = service.preview(preview_request, [source], generated_at=STAMP)
    request = PackExportRequest(
        **preview_request.model_dump(),
        preview_sha256=preview.preview_sha256,
        preview_generated_at=preview.generated_at,
        confirmed_ask_ids=[],
        confirm_evidence=False,
        confirm_unrecoverable_transfer=True,
        delivery_action="download",
    )

    with pytest.raises(MemoryPackError) as error:
        service.export(request, [source])
    assert error.value.code == "PACK_EVIDENCE_CONFIRMATION_REQUIRED"


def test_markdown_contains_only_body_and_does_not_require_evidence_confirmation() -> None:
    source = _source(
        "memory-1",
        "fact",
        body="Enhanced text only",
        evidence=(PackEvidenceReference("ev_ref", "message-1", "Matched source excerpt.", "b" * 64, True, True),),
    )
    service = MemoryPackService()
    preview_request = _preview_request(
        format="markdown", evidence_mode="full", memory_ids=["memory-1"]
    )
    preview = service.preview(preview_request, [source], generated_at=STAMP)
    request = PackExportRequest(
        **preview_request.model_dump(),
        preview_sha256=preview.preview_sha256,
        preview_generated_at=preview.generated_at,
        confirmed_ask_ids=[],
        confirm_evidence=False,
        confirm_unrecoverable_transfer=True,
        delivery_action="copy",
    )

    exported = service.export(request, [source])

    assert "Enhanced text only" in preview.rendered_content
    assert "Matched source excerpt." not in preview.rendered_content
    assert exported.rendered_content == preview.rendered_content


def test_native_profile_with_preference_label_is_included_as_profile() -> None:
    source = replace(_source("native-profile", "preference"), memory_type="profile")
    preview = MemoryPackService().preview(_preview_request(kinds=["profile"]), [source], generated_at=STAMP)
    assert preview.included_count == 1
    assert preview.items[0].kind == "profile"
    assert "Canonical preference text" in preview.rendered_content
    denied = replace(source, external_use="deny")
    assert MemoryPackService().preview(_preview_request(kinds=["profile"]), [denied], generated_at=STAMP).included_count == 0
    ask = replace(source, external_use="ask")
    result = MemoryPackService().preview(_preview_request(kinds=["profile"]), [ask], generated_at=STAMP)
    assert result.items[0].kind == "profile"
    assert result.items[0].exclusion_reason == "ask_requires_selection"


def test_legacy_manual_profile_is_selectable_and_exportable() -> None:
    source = replace(_source("legacy-manual", "preference", external_use="ask"), evidence_kind="human_authored")
    service = MemoryPackService()
    preview = service.preview(_preview_request(kinds=["profile"], memory_ids=[source.memory_id]), [source], generated_at=STAMP)
    assert preview.included_count == 1
    assert preview.items[0].kind == "profile"
    request = PackExportRequest(
        **_preview_request(kinds=["profile"], memory_ids=[source.memory_id]).model_dump(),
        preview_sha256=preview.preview_sha256, preview_generated_at=preview.generated_at,
        confirmed_ask_ids=[source.memory_id], confirm_unrecoverable_transfer=True,
        delivery_action="download",
    )
    exported = service.export(request, [source])
    assert source.memory_id in exported.included_ids
    assert source.content in exported.rendered_content
