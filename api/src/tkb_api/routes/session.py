"""Bluesky アカウントによるセッション管理エンドポイント。

Cookie に署名なしの推測不能トークンを保存し、サーバー側のメモリ内セッションストアで
SDK クライアントと本人 DID を保持する。パスワードや DID をレスポンス本文に含めない。
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from tkb_api.bluesky_auth import (
    AuthenticatedAccount,
    AuthenticationError,
    BlueskyAuthenticator,
    LoginClient,
    LoginProfile,
)
from tkb_api.config import Settings, get_settings
from tkb_api.sessions import SESSION_TTL_SECONDS, SessionStore

SESSION_COOKIE_NAME = "tkb_session"

router = APIRouter(prefix="/api")


class SessionLoginRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str
    app_password: SecretStr

    @field_validator("handle")
    @classmethod
    def _strip_handle(cls, value: str) -> str:
        return value.strip()


class SessionStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authenticated: bool
    handle: str | None = None


class _MockLoginProfile:
    def __init__(self, did: str, handle: str) -> None:
        self._did = did
        self._handle = handle

    @property
    def did(self) -> str:
        return self._did

    @property
    def handle(self) -> str:
        return self._handle


class _MockLoginClient:
    """モックモード用の軽量クライアント。外部通信は一切行わない。"""

    def __init__(self, did: str, handle: str) -> None:
        self._did = did
        self._handle = handle

    @property
    def did(self) -> str:
        return self._did

    @property
    def handle(self) -> str:
        return self._handle

    async def login(self, identifier: str, password: str) -> LoginProfile:
        return _MockLoginProfile(did=self._did, handle=self._handle)


def _normalize_handle(handle: str) -> str:
    cleaned = handle.strip().lstrip("@")
    if "." not in cleaned:
        return f"{cleaned}.bsky.social"
    return cleaned


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    state_settings = getattr(request.app.state, "settings", None)
    if isinstance(state_settings, Settings):
        return state_settings
    return fallback


def get_current_account(request: Request) -> AuthenticatedAccount:
    """現在のリクエストから本人認証済みアカウントを取り出す依存ヘルパー。"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ログインが必要です",
        )

    session_store = cast(SessionStore, request.app.state.session_store)
    account = session_store.get(session_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ログインが必要です",
        )
    return account


@router.post("/session")
async def login(
    body: SessionLoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionStatusResponse:
    """Bluesky アカウントでログインし、HttpOnly Cookie を発行する。"""
    active_settings = _resolve_settings(request, settings)
    handle = body.handle.strip()
    app_password_raw = body.app_password.get_secret_value()

    if not handle or not app_password_raw.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bluesky の認証情報を入力してください",
        )

    if active_settings.mock_mode:
        normalized_handle = _normalize_handle(handle)
        mock_client = cast(
            LoginClient,
            _MockLoginClient(did="did:plc:mock-user", handle=normalized_handle),
        )
        account = AuthenticatedAccount(
            did="did:plc:mock-user",
            handle=normalized_handle,
            client=mock_client,
        )
    else:
        authenticator = cast(BlueskyAuthenticator, request.app.state.authenticator)
        try:
            account = await authenticator.authenticate(handle, app_password_raw)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

    session_store = cast(SessionStore, request.app.state.session_store)
    existing_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if existing_session_id:
        session_store.revoke(existing_session_id)

    session_id = session_store.create(account)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=active_settings.session_cookie_secure,
        path="/",
    )
    return SessionStatusResponse(authenticated=True, handle=account.handle)


@router.get("/session")
def get_session(request: Request) -> SessionStatusResponse:
    """セッションの有効状態とハンドル名を返す。未認証でも 200 で返す。"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return SessionStatusResponse(authenticated=False, handle=None)

    session_store = cast(SessionStore, request.app.state.session_store)
    account = session_store.get(session_id)
    if account is None:
        return SessionStatusResponse(authenticated=False, handle=None)

    return SessionStatusResponse(authenticated=True, handle=account.handle)


@router.delete("/session")
def delete_session(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionStatusResponse:
    """ログアウトし、サーバー側セッションの破棄と Cookie の削除を行う。"""
    active_settings = _resolve_settings(request, settings)
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_store = cast(SessionStore, request.app.state.session_store)
        session_store.revoke(session_id)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=active_settings.session_cookie_secure,
    )
    return SessionStatusResponse(authenticated=False, handle=None)
