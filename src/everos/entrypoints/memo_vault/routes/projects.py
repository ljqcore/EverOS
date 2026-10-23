"""Vault-local project space management."""

from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Request

from ..contracts import ApiEnvelope, ProjectCreateRequest

router = APIRouter(prefix="/projects", tags=["memo-vault-projects"])


@router.get("", response_model=ApiEnvelope[dict[str, object]])
async def list_projects(request: Request) -> ApiEnvelope[dict[str, object]]:
    store = request.app.state.vault_store
    return ApiEnvelope(
        request_id=uuid.uuid4().hex,
        data={"projects": store.list_projects()},
    )


@router.post("", status_code=201, response_model=ApiEnvelope[dict[str, object]])
async def create_project(
    body: ProjectCreateRequest, request: Request
) -> ApiEnvelope[dict[str, object]]:
    store = request.app.state.vault_store
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_PROJECT_NAME",
                "message": "Project name is required.",
            },
        )
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_PROJECT_NAME",
                "message": "Project names cannot contain path separators or be '.' / '..'.",
            },
        )
    try:
        project = store.create_project(
            name=name,
            parent_project_id=body.parent_project_id,
            description=body.description.strip(),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PROJECT_PARENT_NOT_FOUND",
                "message": "Choose an existing parent memory space.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_NAME_ALREADY_EXISTS",
                "message": str(exc),
            },
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "PROJECT_ALREADY_EXISTS", "message": "The project space could not be created."},
        ) from exc
    return ApiEnvelope(request_id=uuid.uuid4().hex, data=project)
