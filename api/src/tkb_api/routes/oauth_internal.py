"""Docker ネットワーク内の OAuth セッション確定。共有秘密と DID の検証が必須。"""

import hmac
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel

from tkb_api.bluesky import LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.routes.session import SESSION_COOKIE, get_session_store

router = APIRouter(prefix="/__internal/oauth")
_DID = re.compile(r"^did:(plc|web):[A-Za-z0-9._:%-]+$")
_HANDLE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


class Completion(BaseModel):
    did: str
    handle: str


def check_internal_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    provided: Annotated[str | None, Header(alias="X-Internal-Auth")] = None,
) -> None:
    expected = settings.internal_auth_secret.get_secret_value()
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


@router.post("/complete")
def complete(
    body: Completion,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    _: Annotated[None, Depends(check_internal_auth)],
) -> dict[str, str]:
    if (
        settings.auth_mode != "oauth"
        or not _DID.fullmatch(body.did)
        or not _HANDLE.fullmatch(body.handle)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    session_id = store.create(LoginResult(body.handle, body.did, None, "oauth"))
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return {"did": body.did, "handle": body.handle}
