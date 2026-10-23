from pathlib import Path

from everos.entrypoints.memo_vault.deepseek_harness import convert_harness_v4
from everos.umif.package import read_package, write_package
from everos.umif.validator import validate_package

FIXTURE = Path("tests/fixtures/memo_vault/deepseek_harness_v4.jsonl")


def test_package_serialization_is_deterministic_and_readable(tmp_path: Path) -> None:
    payload = FIXTURE.read_bytes()
    first = convert_harness_v4(payload, "personal")
    second = convert_harness_v4(payload, "personal")
    left, right = tmp_path / "left", tmp_path / "right"
    write_package(first, left)
    write_package(second, right)
    assert {p.name: p.read_bytes() for p in left.iterdir()} == {p.name: p.read_bytes() for p in right.iterdir()}
    reloaded = read_package(left)
    assert reloaded == first
    assert validate_package(reloaded, left).valid


def test_manifest_has_real_file_sha256(tmp_path: Path) -> None:
    import hashlib
    package = convert_harness_v4(FIXTURE.read_bytes(), "personal")
    write_package(package, tmp_path / "package")
    for entry in package.manifest.files:
        content = (tmp_path / "package" / entry.path).read_bytes()
        assert entry.sha256 == "sha256:" + hashlib.sha256(content).hexdigest()
