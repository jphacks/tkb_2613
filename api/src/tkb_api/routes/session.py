"""Bluesky へのログインとログアウト。

診断できるのはログインした本人のアカウントだけにするため、以降の API は
current_session で得たセッションの DID の投稿だけを扱う。
リクエスト本文（アプリパスワードを含む）はログに出さない。
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, LoginFn, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.schemas import SessionRequest, SessionResponse

router = APIRouter(prefix="/api")

SESSION_COOKIE = "tkb_session"
MOCK_DID = "did:plc:mockdemoaccount"


def get_session_store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


def get_login() -> LoginFn:
    return bluesky.login


def current_session(
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> BlueskySession:
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインしてください")
    return session


@router.post("/session")
async def create_session(
    body: SessionRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    login: Annotated[LoginFn, Depends(get_login)],
) -> SessionResponse:
    if settings.mock_mode:
        result = LoginResult(handle=body.handle, did=MOCK_DID, client=None)
    else:
        try:
            result = await login(body.handle, body.password.get_secret_value())
        except bluesky.LoginFailedError:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "ハンドル名かパスワードが違います"
            ) from None
        except bluesky.BlueskyUnavailableError:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Bluesky に接続できませんでした"
            ) from None

    response.set_cookie(
        SESSION_COOKIE,
        store.create(result),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return SessionResponse(handle=result.handle, did=result.did)


@router.get("/session")
def read_session(session: Annotated[BlueskySession, Depends(current_session)]) -> SessionResponse:
    """今ログインしているのは誰か。画面を開き直したときに、ログイン状態を戻すのに使う。"""
    return SessionResponse(handle=session.handle, did=session.did)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    response: Response,
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if session_id:
        store.delete(session_id)
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")
