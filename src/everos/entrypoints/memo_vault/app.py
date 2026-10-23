"""Standalone FastAPI app for the local MEMO Vault console."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .imports import ImportService
from .adapter import EverOSHttpAdapter
from .routes import candidates, exports, imports, memories, projects, system
from .storage import VaultStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize Vault-local runtime data when the service starts."""

    settings = get_settings()
    store = VaultStore(settings.data_dir)
    store.initialize()
    app.state.vault_store = store
    app.state.everos_adapter = EverOSHttpAdapter(
        settings.everos_base_url, timeout_seconds=settings.everos_timeout_seconds
    )
    app.state.import_service = ImportService(
        store,
        max_file_bytes=settings.max_import_bytes,
        max_archive_unpacked_bytes=settings.max_archive_unpacked_bytes,
        max_archive_files=settings.max_archive_files,
        max_archive_compression_ratio=settings.max_archive_compression_ratio,
    )
    yield


app = FastAPI(
    title="MEMO Vault Local API",
    version="0.1.0",
    description="Local-first MEMO Vault import and archival API.",
    lifespan=lifespan,
)
for route in (
    system.router,
    projects.router,
    imports.router,
    candidates.router,
    memories.router,
):
    app.include_router(route, prefix="/api/v1")
app.include_router(exports.router, prefix="/api/v1")
