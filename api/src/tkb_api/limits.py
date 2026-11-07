"""診断の乱用対策と公開時間帯（docs/aws-migration.md の 5章）。

- 公開時間帯（PUBLIC_WINDOWS）：設定が空なら制限しない（ローカル開発用）
- 1アカウント（DID）1日（日本時間）の診断回数（DIAGNOSE_DAILY_LIMIT）
- 同時に診断できる数（MAX_CONCURRENT_DIAGNOSES）。空きがなければ待たずに断る
- 同じアカウント（DID）での同時診断は1つまで（セッションが違っても）

どれもメモリだけに持ち、再起動で消えてよい。DID は、プロセスごとのランダムな鍵で HMAC にして持ち、
DID そのものは残さない（鍵はメモリだけにあるので、公開されている DID から逆算できない）。
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

JST = timezone(timedelta(hours=9), "JST")


class PublicWindow(BaseModel):
    """公開する時間帯。時刻は時差つき（例 2026-11-16T20:00:00+09:00）で書く。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> "PublicWindow":
        if self.end <= self.start:
            raise ValueError("公開時間帯の end は start より後にしてください")
        return self


@dataclass(frozen=True)
class Availability:
    """いま診断できるか。できないときは次の公開の開始時刻（なければ None＝公開は終わった）。"""

    is_open: bool
    next_open: datetime | None = None


def availability(windows: Sequence[PublicWindow], now: datetime) -> Availability:
    if not windows:
        return Availability(is_open=True)
    if any(w.start <= now < w.end for w in windows):
        return Availability(is_open=True)
    upcoming = sorted(w.start for w in windows if w.start > now)
    return Availability(is_open=False, next_open=upcoming[0] if upcoming else None)


def next_jst_midnight(now: datetime) -> datetime:
    """1日の回数が戻る時刻（日本時間の次の 0:00）。"""
    today = now.astimezone(JST).date()
    return datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=JST)


class DiagnoseRefusedError(Exception):
    """診断を始められない理由。"""


class AlreadyRunningError(DiagnoseRefusedError):
    """同じセッションか、同じアカウント（DID）で診断中。"""


class DailyLimitError(DiagnoseRefusedError):
    """今日の診断回数の上限に達した。"""


class BusyError(DiagnoseRefusedError):
    """同時に診断できる数の上限に達した。"""


@dataclass(frozen=True)
class _Usage:
    day: date
    count: int


@dataclass(eq=False)
class Lease:
    """同時実行の枠1つ。release は何度呼んでもよい。"""

    _limiter: "DiagnoseLimiter"
    session_id: str
    did_key: str
    # 枠を取った日（日本時間）。回数はこの日に数える（日付の境目で翌日に数えないように）
    day: date
    # 最後に動きがあった時刻（monotonic）。slot_timeout はここから数える
    last_active: float
    released: bool = field(default=False)
    counted: bool = field(default=False)

    def count(self) -> None:
        """診断を本当に始めたときに、枠を取った日の回数に1を足す（1回だけ）。"""
        self._limiter._count(self)

    def touch(self) -> None:
        """診断がまだ動いている（SSE を送った）ことを伝え、枠の期限を延ばす。"""
        self._limiter._touch(self)

    def release(self) -> None:
        self._limiter._release(self)


class DiagnoseLimiter:
    """同時実行の枠と1日の回数。値が 0 の上限は「制限しない」。

    枠を返し損ねても（途中で接続が切れて後始末が走らないなど）、最後の動き（touch）から
    slot_timeout 秒たてば枠は空いたものとして扱う。
    """

    def __init__(
        self,
        *,
        daily_limit: int,
        max_concurrent: int,
        slot_timeout_s: float,
        clock: Callable[[], datetime] = lambda: datetime.now(JST),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._daily_limit = daily_limit
        self._max_concurrent = max_concurrent
        self._slot_timeout_s = slot_timeout_s
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._leases: list[Lease] = []
        self._usage: dict[str, _Usage] = {}
        self._key = secrets.token_bytes(32)

    def _did_key(self, did: str) -> str:
        return hmac.new(self._key, did.encode("utf-8"), hashlib.sha256).hexdigest()

    def acquire(self, session_id: str, did: str) -> Lease:
        """枠を取る。取れなければ理由の例外を出す（待たない）。回数はまだ数えない。"""
        key = self._did_key(did)
        with self._lock:
            self._drop_expired()
            # 同じアカウントは1つずつ。別々にログインして枠を独り占めしたり、回数を数える前に
            # 2つ同時に始めて1日の上限を超えたりできないようにする
            if any(
                lease.session_id == session_id or lease.did_key == key for lease in self._leases
            ):
                raise AlreadyRunningError
            if self._daily_limit and self._used_today(key) >= self._daily_limit:
                raise DailyLimitError
            if self._max_concurrent and len(self._leases) >= self._max_concurrent:
                raise BusyError
            lease = Lease(self, session_id, key, self._today(), self._monotonic())
            self._leases.append(lease)
            return lease

    def used_today(self, did: str) -> int:
        with self._lock:
            return self._used_today(self._did_key(did))

    @property
    def active(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._leases)

    def _count(self, lease: Lease) -> None:
        with self._lock:
            if lease.counted:
                return
            lease.counted = True
            day = lease.day
            prev = self._usage.get(lease.did_key)
            used = prev.count if prev is not None and prev.day == day else 0
            today = self._today()
            self._usage = {
                k: u for k, u in self._usage.items() if u.day in (day, today) and k != lease.did_key
            }
            self._usage[lease.did_key] = _Usage(day, used + 1)

    def _touch(self, lease: Lease) -> None:
        with self._lock:
            if not lease.released:
                lease.last_active = self._monotonic()

    def _release(self, lease: Lease) -> None:
        with self._lock:
            if lease.released:
                return
            lease.released = True
            self._leases = [held for held in self._leases if held is not lease]

    def _today(self) -> date:
        return self._clock().astimezone(JST).date()

    def _used_today(self, key: str) -> int:
        usage = self._usage.get(key)
        return usage.count if usage is not None and usage.day == self._today() else 0

    def _drop_expired(self) -> None:
        deadline = self._monotonic() - self._slot_timeout_s
        for lease in self._leases:
            if lease.last_active <= deadline:
                lease.released = True
        self._leases = [lease for lease in self._leases if not lease.released]
