"""Shared FastAPI dependencies: operator authorisation and request validation helpers.

Operator access model (MVP)
- One shared operator secret, ``MEL_OPERATOR_TOKEN`` (>= 16 chars), presented in
  the ``X-Operator-Token`` header. Compared in constant time.
- Every route except ``/healthz`` and the OpenAPI documents requires it:
  workflow triggers, paid inference and all record-level reads.
- If no token is configured, protected routes answer 503 (fail closed); nothing
  is exposed anonymously by default.
- Production limitation: this is a single shared credential with no identity,
  roles, rotation or audit of *who* called. It is adequate for a sandbox MVP
  behind a trusted network, not for a public deployment, where an identity
  provider (OIDC/IAM) and per-operator roles must replace it.
"""

from __future__ import annotations

import hmac
import re
from typing import Annotated, Any

from fastapi import Header, HTTPException, Query, Request

from mel_agent.pipeline import Pipeline
from mel_agent.store import MAX_PAGE_SIZE, Store, StoreError
from mel_agent.time_utils import TimeFormatError, parse_ist

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")
_LANG = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")

LimitQ = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description=f"Page size, at most {MAX_PAGE_SIZE}")]
OffsetQ = Annotated[int, Query(ge=0, le=10_000_000)]


def require_operator(request: Request, x_operator_token: Annotated[str | None, Header()] = None) -> None:
    settings = getattr(request.app.state, "settings", None)
    configured = settings.operator_token.get_secret_value() if settings and settings.operator_token else None
    if not configured:
        raise HTTPException(503, "operator access is not configured (set MEL_OPERATOR_TOKEN)")
    presented = x_operator_token or ""
    if not hmac.compare_digest(presented.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(401, "operator token missing or invalid", headers={"WWW-Authenticate": "X-Operator-Token"})


def get_store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(503, "store not initialised")
    return store


def get_pipeline(request: Request) -> Pipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(503, "pipeline not initialised")
    return pipeline


def valid_id(value: str, what: str = "id") -> str:
    if not _ID.match(value or ""):
        raise HTTPException(422, f"invalid {what}")
    return value


def valid_language(value: str | None) -> str | None:
    if value is None:
        return None
    if not _LANG.match(value):
        raise HTTPException(422, "language must be a BCP 47 tag such as hi-IN")
    return value


def valid_ist(value: str | None, what: str) -> str | None:
    """A real IST timestamp (format AND calendar validity), or 422."""
    if value is None:
        return None
    try:
        parse_ist(value)
    except TimeFormatError:
        raise HTTPException(422, f"{what} must be a valid date-time like 2026-12-04T09:12:00+05:30") from None
    return value


def page_or_422(fn, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(**kwargs).to_dict()
    except StoreError as exc:
        raise HTTPException(422, str(exc)) from None


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")
