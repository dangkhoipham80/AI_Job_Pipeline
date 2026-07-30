"""FastAPI dependencies: DB session + local single-user token auth."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from jobpilot.config import get_secrets
from jobpilot.store.db import get_sessionmaker


def get_db() -> Iterator[Session]:
    """Request-scoped SQLAlchemy session."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def require_token(
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    """Reject requests lacking the local API token.

    Accepts either ``X-API-Token: <token>`` or ``Authorization: Bearer <token>``.
    The app binds to localhost only; this guards against stray/cross-origin calls.
    """
    expected = get_secrets().jobpilot_api_token
    token = x_api_token
    if token is None and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not expected or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API token",
        )
