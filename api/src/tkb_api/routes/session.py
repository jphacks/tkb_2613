"""Bluesky へのログインとログアウト。

診断できるのはログインした本人のアカウントだけにするため、以降の API は
current_session で得たセッションの DID の投稿だけを扱う。
リクエスト本文（アプリパスワードを含む）はログに出さない。
"""

from functools import partial
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


def get_login(settings: Annotated[Settings, Depends(get_settings)]) -> LoginFn:
    return partial(bluesky.login, service=settings.bsky_service)


def current_session_id(
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> str:
    """ログイン中のセッション番号。期限切れやログアウト済みなら 401。"""
    if not session_id or store.get(session_id) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインしてください")
    return session_id


def current_session(
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
) -> BlueskySession:
    session = store.get(session_id)
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
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
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

    if session_id:
        store.delete(session_id)

    new_session_id = store.create(result)
    response.set_cookie(
        SESSION_COOKIE,
        new_session_id,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return SessionResponse(handle=result.handle, did=result.did)


@router.get("/session")
def read_session(session: Annotated[BlueskySession, Depends(current_session)]) -> SessionResponse:
    """今ログインしているのは誰か。画面を開き直したときに、ログイン状態を戻すのに使う。"""
    return SessionResponse(handle=session.handle, did=session.did)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if session_id:
        store.delete(session_id)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
