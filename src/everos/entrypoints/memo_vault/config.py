"""Runtime settings for the local MEMO Vault service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    everos_base_url: str
    everos_timeout_seconds: float
    data_dir: Path
    max_import_bytes: int
    max_archive_unpacked_bytes: int
    max_archive_files: int
    max_archive_compression_ratio: int


def get_settings() -> Settings:
    """Read Vault settings without creating runtime directories."""

    return Settings(
        everos_base_url=os.environ.get(
            "MEMO_VAULT_EVEROS_URL", "http://127.0.0.1:8000"
        ).rstrip("/"),
        everos_timeout_seconds=max(
            1.0, float(os.environ.get("MEMO_VAULT_EVEROS_TIMEOUT_SECONDS", "600"))
        ),
        data_dir=Path(
            os.environ.get("MEMO_VAULT_DATA_DIR", "~/.memo-vault")
        ).expanduser(),
        max_import_bytes=max(
            1,
            int(os.environ.get("MEMO_VAULT_MAX_IMPORT_BYTES", str(100 * 1024 * 1024))),
        ),
        max_archive_unpacked_bytes=max(
            1,
            int(
                os.environ.get(
                    "MEMO_VAULT_MAX_ARCHIVE_UNPACKED_BYTES", str(50 * 1024 * 1024)
                )
            ),
        ),
        max_archive_files=max(
            1, int(os.environ.get("MEMO_VAULT_MAX_ARCHIVE_FILES", "100"))
        ),
        max_archive_compression_ratio=max(
            1, int(os.environ.get("MEMO_VAULT_MAX_ARCHIVE_COMPRESSION_RATIO", "200"))
        ),
    )
