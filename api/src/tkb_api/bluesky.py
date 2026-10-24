"""Bluesky へのログインと、ログイン中のセッション。

パスワードはログインに使うだけで、保存もログ出力もしない。
セッションはメモリ上だけに置き、ブラウザにはランダムなセッション番号だけを渡す。
"""

import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from atproto import AsyncClient
from atproto_client.exceptions import AtProtocolError, BadRequestError, UnauthorizedError


class LoginFailedError(Exception):
    """ハンドル名かパスワードが違う。"""


class BlueskyUnavailableError(Exception):
    """Bluesky に接続できない、または想定外の応答。"""


@dataclass(frozen=True)
class LoginResult:
    handle: str
    did: str
    # モックのときは None（外部に一切接続しない）
    client: AsyncClient | None


LoginFn = Callable[[str, str], Awaitable[LoginResult]]


async def login(handle: str, password: str, service: str = "https://bsky.social") -> LoginResult:
    client = AsyncClient(base_url=f"{service.rstrip('/')}/xrpc")
    try:
        me = await client.login(handle, password)
    except (UnauthorizedError, BadRequestError) as e:
        raise LoginFailedError from e
    except (AtProtocolError, Exception) as e:
        raise BlueskyUnavailableError from e

    if me is None:
        raise BlueskyUnavailableError
    if not isinstance(me.did, str) or not me.did.startswith("did:"):
        raise BlueskyUnavailableError
    if not isinstance(me.handle, str) or not me.handle.strip():
        raise BlueskyUnavailableError

    return LoginResult(handle=me.handle, did=me.did, client=client)


@dataclass(frozen=True)
class BlueskySession:
    handle: str
    did: str
    client: AsyncClient | None
    expires_at: float


class SessionStore:
    """セッション番号 → ログイン中のセッション。メモリ上だけに置き、期限が来たら捨てる。"""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._sessions: dict[str, BlueskySession] = {}
        self._lock = threading.Lock()
        self._closed = False

    def create(self, result: LoginResult) -> str:
        with self._lock:
            if self._closed:
                raise RuntimeError("セッションストアは終了しています")
            self._purge_expired()
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = BlueskySession(
                handle=result.handle,
                did=result.did,
                client=result.client,
                expires_at=self._clock() + self._ttl,
            )
            return session_id

    def get(self, session_id: str) -> BlueskySession | None:
        with self._lock:
            if self._closed:
                return None
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.expires_at <= self._clock():
                del self._sessions[session_id]
                return None
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _purge_expired(self) -> None:
        now = self._clock()
        for session_id in [k for k, v in self._sessions.items() if v.expires_at <= now]:
            del self._sessions[session_id]
