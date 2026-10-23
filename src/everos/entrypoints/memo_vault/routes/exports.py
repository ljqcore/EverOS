"""Memory Pack and ADP export API contract placeholders."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi import HTTPException, Request

from ..adapter import EverOSHttpAdapter
from ..config import get_settings
from ..contracts import (
    AdpValidateRequest,
    ApiEnvelope,
    PackExportData,
    PackExportRequest,
    PackPreviewData,
    PackPreviewRequest,
)
from ..library import LibraryError, MemoVaultLibraryService
from ..memory_pack import MemoryPackError, MemoryPackService
from ._placeholder import not_implemented

router = APIRouter(tags=["memo-vault-exports"])


def _library_service(request: Request) -> MemoVaultLibraryService:
    settings = get_settings()
    adapter = getattr(request.app.state, "everos_adapter", None) or EverOSHttpAdapter(
        settings.everos_base_url, timeout_seconds=settings.everos_timeout_seconds
    )
    return MemoVaultLibraryService(request.app.state.vault_store, adapter)


def _raise_http(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _load_sources(request: Request, namespaces: list[str]):
    store = request.app.state.vault_store
    # Validate every requested project before the first call to EverOS.
    for project_id in dict.fromkeys(namespaces):
        if not store.has_project(project_id):
            raise _raise_http("PROJECT_NOT_FOUND", "One or more selected projects do not exist.", 404)
    service = _library_service(request)
    sources = []
    for project_id in dict.fromkeys(namespaces):
        sources.extend(await service.list_pack_sources(project_id))
    service.revalidate_pack_sources(namespaces, sources)
    return sources


@router.post("/packs/preview", response_model=ApiEnvelope[PackPreviewData])
async def preview_pack(body: PackPreviewRequest, request: Request) -> ApiEnvelope[PackPreviewData]:
    try:
        sources = await _load_sources(request, body.namespaces)
        data = MemoryPackService().preview(body, sources)
    except HTTPException:
        raise
    except LibraryError as exc:
        raise _raise_http(exc.code, str(exc), exc.status_code) from exc
    except MemoryPackError as exc:
        raise _raise_http(exc.code, str(exc), exc.status_code) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.post("/packs/export", response_model=ApiEnvelope[PackExportData])
async def export_pack(body: PackExportRequest, request: Request) -> ApiEnvelope[PackExportData]:
    try:
        sources = await _load_sources(request, body.namespaces)
        data = MemoryPackService().export(body, sources)
    except HTTPException:
        raise
    except LibraryError as exc:
        if exc.code == "PACK_SOURCE_CHANGED":
            raise _raise_http(
                "PACK_PREVIEW_STALE",
                "The Pack changed while loading. Refresh it before copying or downloading.",
                409,
            ) from exc
        raise _raise_http(exc.code, str(exc), exc.status_code) from exc
    except MemoryPackError as exc:
        raise _raise_http(exc.code, str(exc), exc.status_code) from exc

    request.app.state.vault_store.record_export(
        export_type="memory_pack",
        format=data.format,
        item_revisions=data.included_revisions,
        content_sha256=data.content_sha256,
        created_at=datetime.now(UTC).isoformat(),
        namespace_scope=body.namespaces,
        delivery_action=body.delivery_action,
        confirmed_ask_ids=body.confirmed_ask_ids,
        preview_sha256=data.preview_sha256,
    )
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=data)


@router.get("/adp/traces")
async def list_adp_traces() -> None:
    raise not_implemented("adp.traces")


@router.post("/adp/validate")
async def validate_adp(body: AdpValidateRequest) -> None:
    raise not_implemented(f"adp.validate:{len(body.trace_ids)}-traces")


@router.post("/adp/export")
async def export_adp(body: AdpValidateRequest) -> None:
    raise not_implemented(f"adp.export:{len(body.trace_ids)}-traces")
