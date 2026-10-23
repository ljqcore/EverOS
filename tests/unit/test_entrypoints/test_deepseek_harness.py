from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3

import pytest

from everos.entrypoints.memo_vault.imports import (
    DEFAULT_MAX_FILE_BYTES,
    ImportService,
    ImportWorkflowError,
    parse_import_file,
)
from everos.entrypoints.memo_vault.storage import VaultStore


def test_deepseek_harness_v4_normalizes_chat_and_tool_trace_events() -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import parse_deepseek_harness

    fixture = Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl").read_bytes()
    parsed = parse_deepseek_harness(fixture)

    assert parsed.session_id == "session-fixture-1"
    assert [(message.role, message.content) for message in parsed.messages] == [
        ("user", "请比较方案甲和方案乙。"),
        ("assistant", "我会比较两种方案。"),
        ("user", "请比较方案甲和方案乙。"),
    ]
    assert parsed.messages[0].timestamp_ms == 1791942853521
    assert parsed.messages[0].source_message_id == "session-fixture-1:user/message:1"
    assert len(parsed.tool_events) == 2
    call, result = parsed.tool_events
    assert (call.event_type, call.call_id, call.tool_name) == (
        "tool/call",
        "call-1",
        "read_file",
    )
    assert call.arguments == {"path": "notes.txt"}
    assert (result.event_type, result.call_id, result.result_text, result.is_error) == (
        "tool/result",
        "call-1",
        "文件内容",
        False,
    )
    assert result.source_event_seqs == (4,)
    assert parsed.skipped_event_counts["agent/inbox/spliced"] == 1
    assert parsed.skipped_event_counts["harness_runtime_context"] == 1
    assert not parsed.warnings


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"type":"session","version":3,"id":"s"}\n', "version"),
        (b'{"type":"session","version":4,"id":"s"}\n{bad json}\n', "line 2"),
        (
            b'{"type":"session","version":4,"id":"s"}\n'
            b'{"type":"user/message","time":1,"data":{"content":[]}}\n',
            "seq",
        ),
        (
            b'{"type":"session","version":4,"id":"s"}\n'
            b'{"type":"user/message","seq":1,"time":1,"data":{"content":[]}}\n'
            b'{"type":"user/message","seq":1,"time":2,"data":{"content":[]}}\n',
            "duplicate",
        ),
    ],
)
def test_deepseek_harness_rejects_invalid_event_stream(
    payload: bytes, message: str
) -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import parse_deepseek_harness

    with pytest.raises(ImportWorkflowError, match=message):
        parse_deepseek_harness(payload)


def test_deepseek_harness_requires_json_tool_arguments() -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import parse_deepseek_harness

    payload = (
        b'{"type":"session","version":4,"id":"s"}\n'
        b'{"type":"tool/call","seq":1,"time":1,"data":{"callId":"c",'
        b'"name":"read_file","arguments":"not-json"}}\n'
    )
    with pytest.raises(ImportWorkflowError, match="arguments"):
        parse_deepseek_harness(payload)


def test_jsonl_import_dispatches_to_deepseek_parser() -> None:
    fixture = Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl").read_bytes()

    parsed = parse_import_file(
        "session.v4.jsonl", fixture, content_type="application/x-ndjson"
    )

    assert parsed.conversation_count == 1
    assert parsed.message_count == 3
    assert parsed.tool_call_count == 1
    assert len(parsed.tool_events) == 2


def test_default_single_file_upload_limit_is_100_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DEFAULT_MAX_FILE_BYTES == 100 * 1024 * 1024
    monkeypatch.delenv("MEMO_VAULT_MAX_IMPORT_BYTES", raising=False)
    from everos.entrypoints.memo_vault.config import get_settings

    assert get_settings().max_import_bytes == 100 * 1024 * 1024


def test_preview_rejects_files_above_the_configured_upload_limit(tmp_path: Path) -> None:
    service = ImportService(VaultStore(tmp_path / "vault"), max_file_bytes=4)

    with pytest.raises(ImportWorkflowError) as error:
        service.preview("notes.txt", "generic", b"12345")
    assert error.value.code == "IMPORT_SECURITY_REJECTED"


def _fixture_bytes() -> bytes:
    return Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl").read_bytes()


def _preview_and_commit(store: VaultStore, payload: bytes) -> dict[str, object]:
    service = ImportService(store)
    preview = service.preview("session.v4.jsonl", "deepseek_harness", payload, project_id="personal")
    return service.commit(preview["preview_id"], "personal")


def test_vault_schema_creates_trace_table_for_new_and_existing_databases(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()

    with store.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "normalized_tool_events" in tables

    reopened = VaultStore(tmp_path / "vault")
    reopened.initialize()
    with reopened.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_tool_events"
        ).fetchone()[0] == 0


def test_commit_persists_messages_and_tool_trace_events_atomically(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()

    batch = _preview_and_commit(store, _fixture_bytes())

    with store.connect() as connection:
        messages = connection.execute(
            "SELECT role, source_message_id, is_duplicate FROM normalized_messages "
            "WHERE batch_id = ? ORDER BY ordinal",
            (batch["batch_id"],),
        ).fetchall()
        events = connection.execute(
            "SELECT event_type, call_id, tool_name, arguments_json, result_text, "
            "source_event_seqs_json FROM normalized_tool_events "
            "WHERE batch_id = ? ORDER BY ordinal",
            (batch["batch_id"],),
        ).fetchall()
    assert len(messages) == 3
    assert all(not message[2] for message in messages)
    assert [(event[0], event[1]) for event in events] == [
        ("tool/call", "call-1"),
        ("tool/result", "call-1"),
    ]
    assert json.loads(events[0][3]) == {"path": "notes.txt"}
    assert events[1][4] == "文件内容"
    assert json.loads(events[1][5]) == [4]


def test_same_source_event_with_changed_content_blocks_commit(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    service = ImportService(store)
    first = service.preview("session.v4.jsonl", "deepseek_harness", _fixture_bytes(), project_id="personal")
    service.commit(first["preview_id"], "personal")

    changed = _fixture_bytes().replace("请比较方案甲和方案乙。".encode(), "请比较新方案。".encode(), 1)
    preview = service.preview("session.v4.jsonl", "deepseek_harness", changed, project_id="personal")

    assert preview["source_event_conflict_count"] == 1
    with pytest.raises(ImportWorkflowError, match="source event"):
        service.commit(preview["preview_id"], "personal")


def test_trace_persistence_failure_rolls_back_import_batch_and_messages(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_trace BEFORE INSERT ON normalized_tool_events "
            "BEGIN SELECT RAISE(ABORT, 'forced trace failure'); END"
        )
    service = ImportService(store)
    preview = service.preview(
        "session.v4.jsonl", "deepseek_harness", _fixture_bytes(), project_id="personal"
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced trace failure"):
        service.commit(preview["preview_id"], "personal")

    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM normalized_messages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM normalized_tool_events").fetchone()[0] == 0


def test_harness_preview_includes_redacted_trace_samples_and_warnings(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    payload = (
        b'{"type":"session","version":4,"id":"preview-session"}\n'
        b'{"type":"tool/call","seq":1,"time":10,"data":{"callId":"c1",'
        b'"name":"fetch","arguments":"{\\"api_key\\":\\"secret-value\\"}"}}\n'
        b'{"type":"tool/result","seq":2,"time":11,"data":{"message":'
        b'{"role":"tool","toolCallId":"missing-call","content":[{"type":"text",'
        b'"text":"token=abc123"}],"isError":true}}}\n'
    )

    preview = ImportService(store).preview(
        "session.v4.jsonl", "deepseek_harness", payload, project_id="personal"
    )

    assert preview["tool_call_count"] == 1
    assert preview["tool_result_count"] == 1
    assert preview["warnings"]
    assert preview["tool_events"][0]["arguments"] == {"api_key": "[REDACTED]"}
    assert "secret-value" not in json.dumps(preview["tool_events"])
    assert "abc123" not in json.dumps(preview["tool_events"])


def test_harness_source_requires_jsonl_and_generic_source_rejects_jsonl(
    tmp_path: Path,
) -> None:
    service = ImportService(VaultStore(tmp_path / "vault"))

    with pytest.raises(ImportWorkflowError, match="require a .jsonl"):
        service.preview("session.json", "deepseek_harness", b"{}")
    with pytest.raises(ImportWorkflowError, match="DeepSeek Harness source"):
        service.preview("session.jsonl", "generic", _fixture_bytes())


def test_all_filtered_messages_still_archive_tool_traces_and_skip_chat_extraction(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    payload = (
        b'{"type":"session","version":4,"id":"context-only"}\n'
        b'{"type":"user/message","seq":1,"time":10,"data":{"content":'
        b'[{"type":"text","text":"Current runtime context. injected."}]}}\n'
        b'{"type":"tool/call","seq":2,"time":11,"data":{"callId":"c1",'
        b'"name":"read_file","arguments":"{\\"path\\":\\"a.txt\\"}"}}\n'
        b'{"type":"diagnostic/custom","seq":3,"time":12,"data":{}}\n'
    )
    service = ImportService(store)

    preview = service.preview("session.v4.jsonl", "deepseek_harness", payload, project_id="personal")
    batch = service.commit(preview["preview_id"], "personal")

    assert preview["message_count"] == 0
    assert preview["tool_call_count"] == 1
    assert preview["skipped_event_counts"]["diagnostic/custom"] == 1
    assert preview["skipped_event_counts"]["harness_runtime_context"] == 1
    with store.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_messages WHERE batch_id = ?",
            (batch["batch_id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_tool_events WHERE batch_id = ?",
            (batch["batch_id"],),
        ).fetchone()[0] == 1


def test_reimported_source_events_are_duplicates_but_not_lost(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    service = ImportService(store)
    first = service.preview("session.v4.jsonl", "deepseek_harness", _fixture_bytes(), project_id="personal")
    service.commit(first["preview_id"], "personal")
    altered = _fixture_bytes().replace(
        b'"type":"session","version":4,"id":"session-fixture-1"',
        b'"type":"session","version":4,"id":"session-fixture-1","export":"2"',
    )

    preview = service.preview("session.v4.jsonl", "deepseek_harness", altered, project_id="personal")

    assert preview["duplicate_batch_id"] is None
    assert preview["duplicate_message_count"] == 3
    assert preview["duplicate_tool_event_count"] == 2
    assert all(message["duplicate"] for message in preview["messages"])
    assert all(event["duplicate"] for event in preview["tool_events"])


def test_harness_source_event_deduplication_is_project_scoped(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    project = store.create_project(name="Project B", parent_project_id="personal")
    service = ImportService(store)
    first = service.preview(
        "session.v4.jsonl", "deepseek_harness", _fixture_bytes(), project_id="personal"
    )
    service.commit(first["preview_id"], "personal")
    same_events = _fixture_bytes().replace(
        b'"type":"session","version":4,"id":"session-fixture-1"',
        b'"type":"session","version":4,"id":"session-fixture-1","export":"2"',
    )

    preview = service.preview(
        "session.v4.jsonl", "deepseek_harness", same_events, project_id=project["project_id"]
    )

    assert preview["duplicate_batch_id"] is None
    assert preview["duplicate_message_count"] == 0
    assert preview["duplicate_tool_event_count"] == 0
    committed = service.commit(preview["preview_id"], project["project_id"])
    assert committed["project_id"] == project["project_id"]


def test_harness_zip_and_jsonl_produce_same_umif_core(tmp_path: Path) -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
    from everos.entrypoints.memo_vault.imports import ImportLimits, read_harness_export
    from everos.umif.package import write_package
    payload = _fixture_bytes()
    zipped = _make_harness_zip({"session.v4.jsonl": payload})
    extracted = read_harness_export(zipped, "export.zip", ImportLimits())
    assert extracted == payload
    direct = convert_harness_v4(payload, "personal")
    via_zip = convert_harness_v4(extracted, "personal")
    write_package(direct, tmp_path / "direct")
    write_package(via_zip, tmp_path / "zip")
    assert (tmp_path / "direct" / "events.jsonl").read_bytes() == (tmp_path / "zip" / "events.jsonl").read_bytes()


def _make_harness_zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_harness_zip_rejects_unsafe_and_multiple_members() -> None:
    from everos.entrypoints.memo_vault.imports import ImportLimits, read_harness_export
    for entries in ({"../session.v4.jsonl": _fixture_bytes()},
                    {"session.v4.jsonl": _fixture_bytes(), "other.txt": b"x"}):
        with pytest.raises(ImportWorkflowError):
            read_harness_export(_make_harness_zip(entries), "export.zip", ImportLimits())
    with pytest.raises(ImportWorkflowError) as too_large:
        read_harness_export(
            _make_harness_zip({"session.v4.jsonl": _fixture_bytes()}),
            "export.zip", ImportLimits(max_unpacked_bytes=16),
        )
    assert too_large.value.code == "IMPORT_SECURITY_REJECTED"


def test_umif_conversion_rejects_unknown_harness_version_explicitly() -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
    with pytest.raises(ImportWorkflowError) as unsupported:
        convert_harness_v4(b'{"type":"session","version":5,"id":"s"}\n', "personal")
    assert unsupported.value.code == "IMPORT_VERSION_UNSUPPORTED"


def test_umif_preserves_invalid_tool_arguments_and_missing_time() -> None:
    from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
    from everos.umif.validator import validate_package
    payload = (
        b'{"type":"session","version":4,"id":"s"}\n'
        b'{"type":"tool/call","seq":1,"data":{"callId":"c","name":"read_file","arguments":"not-json"}}\n'
    )
    package = convert_harness_v4(payload, "personal")
    call = package.events[0]
    assert call.payload["arguments_text"] == "not-json"
    assert call.payload["arguments"] is None
    assert call.timestamp_ms is None
    assert call.provenance["time_quality"] == "unknown"
    assert validate_package(package).valid


def test_harness_zip_preview_commit_persists_umif_and_original(tmp_path: Path) -> None:
    from everos.umif.package import read_package
    from everos.umif.validator import validate_package
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    service = ImportService(store)
    archive = _make_harness_zip({"session.v4.jsonl": _fixture_bytes()})
    preview = service.preview("export.zip", "deepseek_harness", archive, project_id="personal")
    assert preview["umif_record_count"] > preview["message_count"]
    batch = service.commit(preview["preview_id"], "personal")
    with store.connect() as connection:
        row = connection.execute("SELECT raw_relpath, umif_package_relpath FROM import_batches WHERE id = ?", (batch["batch_id"],)).fetchone()
        mapped = connection.execute("SELECT COUNT(*) FROM umif_record_map WHERE batch_id = ? AND target_id IS NOT NULL", (batch["batch_id"],)).fetchone()[0]
    assert (store.data_dir / row["raw_relpath"]).read_bytes() == archive
    umif_package = read_package(store.data_dir / row["umif_package_relpath"])
    assert validate_package(umif_package).valid
    assert umif_package.manifest.source_exports[0]["archive_name"] == "export.zip"
    assert umif_package.manifest.source_exports[0]["archive_sha256"] == "sha256:" + hashlib.sha256(archive).hexdigest()
    assert mapped == preview["message_count"] + preview["tool_call_count"] + preview["tool_result_count"]


def test_changed_invalid_tool_argument_text_conflicts_by_umif_hash(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.initialize()
    service = ImportService(store)
    def source(argument: str) -> bytes:
        return (
            '{"type":"session","version":4,"id":"raw-arg-session"}\n'
            '{"type":"tool/call","seq":1,"time":1000,"data":{"callId":"c1",'
            '"name":"read_file","arguments":' + json.dumps(argument) + '}}\n'
        ).encode()
    first = service.preview("session.v4.jsonl", "deepseek_harness", source("{bad-one"), project_id="personal")
    service.commit(first["preview_id"], "personal")
    changed = service.preview("session.v4.jsonl", "deepseek_harness", source("{bad-two"), project_id="personal")
    assert changed["source_event_conflict_count"] == 1
    with pytest.raises(ImportWorkflowError) as conflict:
        service.commit(changed["preview_id"], "personal")
    assert conflict.value.code == "IMPORT_SOURCE_EVENT_CONFLICT"
