from everos.umif.canonical import content_hash, record_id


def test_stable_ids_and_hashes_ignore_mapping_order():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert record_id("deepseek_harness", "message", "m1", "main") == record_id(
        "deepseek_harness", "message", "m1", "main"
    )
    assert record_id("deepseek_harness", "message", "m1", "main") != record_id(
        "deepseek_harness", "message", "m2", "main"
    )
import json
from pathlib import Path

import pytest

from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
from everos.entrypoints.memo_vault.imports import ImportWorkflowError


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("toolCallId", ["invalid"]),
        ("time", 10**30),
        ("sourceEventSeqs", 42),
    ],
)
def test_malformed_harness_fields_raise_import_error(field: str, value: object) -> None:
    lines = [json.loads(line) for line in Path(
        "tests/fixtures/memo_vault/deepseek_harness_v4.jsonl"
    ).read_text().splitlines() if line]
    for row in lines:
        if field == "time" and row.get("type") == "user/message":
            row["time"] = value
            break
        if field in {"toolCallId", "sourceEventSeqs"} and row.get("type") == "tool/result":
            if field == "toolCallId":
                row["data"]["message"][field] = value
            else:
                row[field] = value
            break
    payload = "\n".join(json.dumps(row) for row in lines).encode()
    with pytest.raises(ImportWorkflowError) as error:
        convert_harness_v4(payload, "personal")
    assert error.value.code == "IMPORT_PARSE_FAILED"
