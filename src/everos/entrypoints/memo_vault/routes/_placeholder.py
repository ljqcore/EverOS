"""Explicit response for API routes whose business flow is not implemented yet."""

from fastapi import HTTPException


def not_implemented(feature: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={
            "code": "FEATURE_NOT_IMPLEMENTED",
            "feature": feature,
            "message": "This MEMO Vault workflow has not been implemented yet.",
        },
    )
