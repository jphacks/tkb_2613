"""Bluesky 本人認証の内部アダプタ。公開 API の形式はここで決めない。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast


class LoginProfile(Protocol):
    @property
    def did(self) -> str: ...

    @property
    def handle(self) -> str: ...


class LoginClient(Protocol):
    async def login(self, identifier: str, password: str) -> LoginProfile: ...


@dataclass(frozen=True, slots=True, repr=False)
class AuthenticatedAccount:
    """SDK クライアントをサーバーのメモリ内でだけ保持する。"""

    did: str
    handle: str
    client: LoginClient = field(repr=False, compare=False)


class AuthenticationError(Exception):
    """認証失敗。SDK の例外や資格情報を呼び出し側へ渡さない。"""


def _new_client() -> LoginClient:
    from atproto import AsyncClient

    return cast(LoginClient, AsyncClient())


class BlueskyAuthenticator:
    def __init__(self, client_factory: Callable[[], LoginClient] = _new_client) -> None:
        self._client_factory = client_factory

    async def authenticate(self, handle: str, app_password: str) -> AuthenticatedAccount:
        """アプリパスワードを SDK へ一度渡し、本人 DID と接続済みクライアントを返す。"""
        if not handle or not app_password:
            raise AuthenticationError("Bluesky の認証情報を入力してください")

        try:
            client = self._client_factory()
            profile = await client.login(handle, app_password)
            did = profile.did
            verified_handle = profile.handle
        except Exception:
            raise AuthenticationError("Bluesky にログインできませんでした") from None

        if not isinstance(did, str) or not did.startswith("did:"):
            raise AuthenticationError("Bluesky の認証結果を確認できませんでした")
        if not isinstance(verified_handle, str) or not verified_handle:
            raise AuthenticationError("Bluesky の認証結果を確認できませんでした")

        return AuthenticatedAccount(did=did, handle=verified_handle, client=client)
