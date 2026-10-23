"""Project-scoped reads for confirmed EverOS memories."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..adapter import EverOSHttpAdapter
from ..config import get_settings
from ..contracts import (
    ApiEnvelope,
    LibraryMemoryDetail,
    MemoryLibraryListData,
    MemoryLibrarySummaryData,
)
from ..library import LibraryError, MemoVaultLibraryService

router = APIRouter(prefix="/memories", tags=["memo-vault-memories"])


class MemoryCorrectionRequest(BaseModel):
    revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=4000)
    external_use: Literal["allow", "ask", "deny"]
    note: str | None = Field(default=None, max_length=500)


class MemoryActionRequest(BaseModel):
    revision: int = Field(ge=1)


def _service(request: Request) -> MemoVaultLibraryService:
    settings = get_settings()
    adapter = getattr(request.app.state, "everos_adapter", None) or EverOSHttpAdapter(
        settings.everos_base_url, timeout_seconds=settings.everos_timeout_seconds
    )
    return MemoVaultLibraryService(request.app.state.vault_store, adapter)


def _raise_http(exc: LibraryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/summary", response_model=ApiEnvelope[MemoryLibrarySummaryData])
async def memory_library_summary(request: Request) -> ApiEnvelope[MemoryLibrarySummaryData]:
    """Count canonical visible and still-syncing confirmed memories per project."""
    try:
        data = await _service(request).summary()
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.get("", response_model=ApiEnvelope[MemoryLibraryListData])
async def search_memories(
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
    q: str = Query(default="", max_length=500),
    status: Literal["valid", "expired", "all"] = "valid",
) -> ApiEnvelope[MemoryLibraryListData]:
    """List confirmed canonical memories from one existing project space."""
    try:
        data = await _service(request).list_memories(
            project_id=project_id, query=q, status=status
        )
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.get("/{vault_memory_id}", response_model=ApiEnvelope[LibraryMemoryDetail])
async def get_memory(
    vault_memory_id: str,
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
) -> ApiEnvelope[LibraryMemoryDetail]:
    """Read full canonical content only after a confirmed registry match."""
    try:
        data = await _service(request).get_memory(
            project_id=project_id, memory_id=vault_memory_id
        )
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.patch("/{vault_memory_id}", response_model=ApiEnvelope[LibraryMemoryDetail])
async def correct_memory(
    vault_memory_id: str,
    body: MemoryCorrectionRequest,
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
) -> ApiEnvelope[LibraryMemoryDetail]:
    try:
        data = await _service(request).apply_lifecycle(
            project_id=project_id,
            memory_id=vault_memory_id,
            action="correct",
            expected_revision=body.revision,
            content=body.content,
            external_use=body.external_use,
            note=body.note.strip() if body.note and body.note.strip() else None,
        )
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.post("/{vault_memory_id}/withdraw", response_model=ApiEnvelope[LibraryMemoryDetail])
async def withdraw_memory(
    vault_memory_id: str,
    body: MemoryActionRequest,
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
) -> ApiEnvelope[LibraryMemoryDetail]:
    try:
        data = await _service(request).apply_lifecycle(
            project_id=project_id,
            memory_id=vault_memory_id,
            action="withdraw",
            expected_revision=body.revision,
        )
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.delete("/{vault_memory_id}", response_model=ApiEnvelope[LibraryMemoryDetail])
async def delete_memory(
    vault_memory_id: str,
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
    revision: int = Query(ge=1),
) -> ApiEnvelope[LibraryMemoryDetail]:
    try:
        data = await _service(request).apply_lifecycle(
            project_id=project_id,
            memory_id=vault_memory_id,
            action="delete",
            expected_revision=revision,
        )
    except LibraryError as exc:
        raise _raise_http(exc) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)
