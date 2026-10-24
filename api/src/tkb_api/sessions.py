"""プロセス内だけで保持する、期限付きの本人セッション。"""

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Timer
from typing import Protocol

from tkb_api.bluesky_auth import AuthenticatedAccount

SESSION_TTL_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True, repr=False)
class _Entry:
    account: AuthenticatedAccount
    expires_at: float


def _new_session_id() -> str:
    return secrets.token_urlsafe(32)


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


def _start_timer(delay: float, callback: Callable[[], None]) -> TimerHandle:
    timer = Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class SessionStore:
    """有効期限とログアウトで SDK クライアントごとセッションを破棄する。"""

    def __init__(
        self,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        session_id_factory: Callable[[], str] = _new_session_id,
        schedule: Callable[[float, Callable[[], None]], TimerHandle] = _start_timer,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("セッションの有効期限は正の値が必要です")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._schedule = schedule
        self._entries: dict[str, _Entry] = {}
        self._lock = Lock()
        self._timer: TimerHandle | None = None
        self._timer_generation = 0
        self._closed = False

    def create(self, account: AuthenticatedAccount) -> str:
        """Cookie に格納する推測不能な ID を発行する。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("セッションストアは終了しています")
            now = self._clock()
            self._remove_expired(now)
            session_id = self._session_id_factory()
            if not session_id or session_id in self._entries:
                raise RuntimeError("セッション ID を発行できませんでした")
            self._entries[session_id] = _Entry(account=account, expires_at=now + self._ttl_seconds)
            self._reschedule_locked(now)
        return session_id

    def get(self, session_id: str) -> AuthenticatedAccount | None:
        """有効なセッションだけを返し、期限切れなら直ちに破棄する。"""
        if not session_id:
            return None
        with self._lock:
            if self._closed:
                return None
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= self._clock():
                del self._entries[session_id]
                self._reschedule_locked(self._clock())
                return None
            return entry.account

    def revoke(self, session_id: str) -> bool:
        """ログアウト時に ID と SDK クライアントへの参照を無効化する。"""
        with self._lock:
            removed = self._entries.pop(session_id, None) is not None
            if removed:
                self._reschedule_locked(self._clock())
            return removed

    def close(self) -> None:
        """アプリ終了時に全セッションと期限タイマーを破棄する。"""
        with self._lock:
            self._closed = True
            self._entries.clear()
            self._cancel_timer_locked()

    def _on_timer(self, generation: int) -> None:
        with self._lock:
            if self._closed or generation != self._timer_generation:
                return
            now = self._clock()
            self._remove_expired(now)
            self._reschedule_locked(now)

    def _reschedule_locked(self, now: float) -> None:
        self._cancel_timer_locked()
        if not self._entries:
            return
        earliest = min(entry.expires_at for entry in self._entries.values())
        generation = self._timer_generation
        self._timer = self._schedule(max(0.0, earliest - now), lambda: self._on_timer(generation))

    def _cancel_timer_locked(self) -> None:
        self._timer_generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _remove_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
