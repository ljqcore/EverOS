from pathlib import Path

from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
from everos.umif.package import seal_package
from everos.umif.validator import validate_package

FIXTURE = Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl")


def _package():
    return convert_harness_v4(FIXTURE.read_bytes(), "personal")


def test_validator_detects_duplicate_id_and_missing_session() -> None:
    package = _package()
    duplicate = package.model_copy(update={"events": (*package.events, package.events[0])})
    assert "DUPLICATE_RECORD_ID" in validate_package(seal_package(duplicate)).errors
    missing = package.model_copy(update={"sessions": ()})
    assert "MISSING_SESSION" in validate_package(seal_package(missing)).errors


def test_validator_reports_orphan_tool_result_without_dropping_it() -> None:
    package = _package()
    result = next(event for event in package.events if event.record_type == "event.tool_result")
    package = package.model_copy(update={"events": (result,)})
    report = validate_package(seal_package(package))
    assert report.valid
    assert "ORPHAN_TOOL_RESULT" in report.warnings


def test_validator_detects_changed_payload_and_manifest_hash() -> None:
    package = _package()
    message = package.events[0].model_copy(update={"payload": {"role": "user"}})
    changed = package.model_copy(update={"events": (message, *package.events[1:])})
    assert "CONTENT_HASH_MISMATCH" in validate_package(seal_package(changed)).errors
    bad_entry = package.manifest.files[0].model_copy(update={"sha256": "sha256:" + "0" * 64})
    bad_manifest = package.manifest.model_copy(update={"files": [bad_entry, *package.manifest.files[1:]]})
    assert "FILE_HASH_MISMATCH" in validate_package(package.model_copy(update={"manifest": bad_manifest})).errors


def test_validator_rejects_unsafe_asset_blob_path() -> None:
    from everos.umif.canonical import content_hash
    from everos.umif.models import UmifRecord
    package = _package()
    body = {"blob_path": "../../outside", "available": True}
    asset = UmifRecord(
        record_type="asset", record_id="asset-unsafe",
        source={"provider": "fixture", "native_type": "attachment", "native_id": "a"},
        scope={"workspace_id": "personal", "project_id": "personal", "session_id": None},
        sequence=0, provenance={"content_sha256": content_hash(body)}, payload=body,
    )
    package = package.model_copy(update={"optional_records": {"assets.jsonl": (asset,)}})
    assert "UNSAFE_BLOB_PATH" in validate_package(seal_package(package)).errors


def test_validator_rejects_optional_records_missing_from_manifest() -> None:
    from everos.umif.canonical import content_hash
    from everos.umif.models import UmifRecord

    package = _package()
    body = {"available": False}
    asset = UmifRecord(record_type="asset", record_id="asset-unlisted",
                       source={"provider": "fixture", "native_type": "attachment", "native_id": "a"},
                       scope={"workspace_id": "personal", "project_id": "personal", "session_id": None},
                       sequence=0, provenance={"content_sha256": content_hash(body)}, payload=body)
    unlisted = package.model_copy(update={"optional_records": {"assets.jsonl": (asset,)}})
    assert "UNLISTED_OPTIONAL_FILE" in validate_package(unlisted).errors
