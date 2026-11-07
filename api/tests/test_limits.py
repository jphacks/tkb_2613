import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tkb_api.limits import (
    JST,
    AlreadyRunningError,
    BusyError,
    DailyLimitError,
    DiagnoseLimiter,
    PublicWindow,
    availability,
    next_jst_midnight,
)
from tkb_api.routes.diagnose import _release_when_closed


def _jst(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=JST)


# 決定した公開時間帯の一部（docs/aws-migration.md の 6.3）
WINDOWS = [
    PublicWindow(start=_jst(11, 16, 20), end=_jst(11, 16, 22)),
    PublicWindow(start=_jst(11, 17, 20), end=_jst(11, 17, 22)),
]


class FakeTime:
    """時計を進められる偽物。clock は日本時間、monotonic は秒。"""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.seconds = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.seconds += seconds


def _limiter(
    t: FakeTime, *, daily: int = 3, concurrent: int = 2, timeout: float = 900
) -> DiagnoseLimiter:
    return DiagnoseLimiter(
        daily_limit=daily,
        max_concurrent=concurrent,
        slot_timeout_s=timeout,
        clock=t.clock,
        monotonic=t.monotonic,
    )


# --- 公開時間帯 ---


def test_no_windows_means_always_open() -> None:
    assert availability([], _jst(11, 7, 3)).is_open


@pytest.mark.parametrize("now", [_jst(11, 16, 20), _jst(11, 16, 21, 59), _jst(11, 17, 20, 30)])
def test_open_inside_a_window(now: datetime) -> None:
    assert availability(WINDOWS, now).is_open


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_jst(11, 15, 12), _jst(11, 16, 20)),  # 最初の公開の前
        (_jst(11, 16, 22), _jst(11, 17, 20)),  # 終わりの時刻ちょうどは時間外
        (_jst(11, 17, 3), _jst(11, 17, 20)),  # 公開の間
    ],
)
def test_closed_reports_the_next_start(now: datetime, expected: datetime) -> None:
    avail = availability(WINDOWS, now)
    assert not avail.is_open
    assert avail.next_open == expected


def test_closed_after_the_last_window_has_no_next_start() -> None:
    avail = availability(WINDOWS, _jst(11, 18, 0))
    assert not avail.is_open
    assert avail.next_open is None


def test_windows_can_be_written_in_other_time_zones() -> None:
    utc_window = PublicWindow.model_validate(
        {"start": "2026-11-16T11:00:00Z", "end": "2026-11-16T13:00:00Z"}
    )
    assert availability([utc_window], _jst(11, 16, 20, 30)).is_open


@pytest.mark.parametrize(
    "raw",
    [
        {"start": "2026-11-16T20:00:00", "end": "2026-11-16T22:00:00"},  # 時差がない
        {"start": "2026-11-16T22:00:00+09:00", "end": "2026-11-16T20:00:00+09:00"},
        {"start": "2026-11-16T20:00:00+09:00", "end": "2026-11-16T20:00:00+09:00"},
        {"start": "2026-11-16T20:00:00+09:00"},
    ],
)
def test_invalid_windows_are_rejected(raw: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        PublicWindow.model_validate(raw)


def test_next_jst_midnight() -> None:
    assert next_jst_midnight(_jst(11, 16, 23, 59)) == _jst(11, 17, 0)
    # UTC で 11/16 15:30 は日本時間の 11/17 0:30 なので、戻るのは 11/18 0:00
    assert next_jst_midnight(datetime(2026, 11, 16, 15, 30, tzinfo=UTC)) == _jst(11, 18, 0)


# --- 1日の回数 ---


def test_daily_limit_counts_only_started_diagnoses() -> None:
    t = FakeTime(_jst(11, 16, 20))
    limiter = _limiter(t, daily=2)

    for _ in range(2):
        lease = limiter.acquire("s1", "did:plc:alice")
        lease.count()
        lease.release()
    # 枠を取ったが始めなかった（モデルや Bluesky の不調）分は数えない
    limiter.acquire("s1", "did:plc:bob").release()

    with pytest.raises(DailyLimitError):
        limiter.acquire("s2", "did:plc:alice")  # 別のセッションでも同じアカウントなら数える
    assert limiter.used_today("did:plc:bob") == 0


def test_count_is_added_only_once_per_lease() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:alice")
    lease.count()
    lease.count()
    assert limiter.used_today("did:plc:alice") == 1


def test_daily_limit_resets_at_jst_midnight() -> None:
    t = FakeTime(_jst(11, 16, 23, 50))
    limiter = _limiter(t, daily=1)
    lease = limiter.acquire("s1", "did:plc:alice")
    lease.count()
    lease.release()
    with pytest.raises(DailyLimitError):
        limiter.acquire("s1", "did:plc:alice")

    t.advance(10 * 60)  # 日本時間の 0:00

    limiter.acquire("s1", "did:plc:alice").release()


def test_zero_daily_limit_means_unlimited() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)), daily=0)
    for _ in range(10):
        lease = limiter.acquire("s1", "did:plc:alice")
        lease.count()
        lease.release()


def test_did_itself_is_not_kept() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:alice")
    lease.count()
    assert "did:plc:alice" not in repr(vars(limiter))


# --- 同時実行の枠 ---


def test_busy_when_all_slots_are_taken_and_free_after_release() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)), concurrent=2)
    first = limiter.acquire("s1", "did:plc:a")
    limiter.acquire("s2", "did:plc:b")

    with pytest.raises(BusyError):
        limiter.acquire("s3", "did:plc:c")

    first.release()
    limiter.acquire("s3", "did:plc:c")
    assert limiter.active == 2


def test_release_is_idempotent() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)), concurrent=2)
    lease = limiter.acquire("s1", "did:plc:a")
    other = limiter.acquire("s2", "did:plc:b")
    lease.release()
    lease.release()
    assert limiter.active == 1
    other.release()
    assert limiter.active == 0


def test_same_session_cannot_run_two_diagnoses() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)), concurrent=5)
    lease = limiter.acquire("s1", "did:plc:a")
    with pytest.raises(AlreadyRunningError):
        limiter.acquire("s1", "did:plc:a")
    lease.release()
    limiter.acquire("s1", "did:plc:a")


def test_leaked_slot_frees_itself_after_the_timeout() -> None:
    t = FakeTime(_jst(11, 16, 20))
    limiter = _limiter(t, concurrent=1, timeout=900)
    limiter.acquire("s1", "did:plc:a")  # 返し損ねた枠

    t.advance(899)
    with pytest.raises(BusyError):
        limiter.acquire("s2", "did:plc:b")

    t.advance(1)
    limiter.acquire("s2", "did:plc:b")


def test_zero_concurrency_means_unlimited() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)), concurrent=0)
    for i in range(10):
        limiter.acquire(f"s{i}", f"did:plc:{i}")


# --- SSE の generator を閉じたら枠を返す ---


async def _chunks(n: int, gate: asyncio.Event | None = None) -> AsyncIterator[str]:
    for i in range(n):
        if gate is not None and i == 1:
            await gate.wait()
        yield f"chunk{i}"


@pytest.mark.anyio
async def test_slot_is_released_when_the_stream_finishes() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:a")

    chunks = [c async for c in _release_when_closed(_chunks(3), lease)]

    assert chunks == ["chunk0", "chunk1", "chunk2"]
    assert limiter.active == 0


@pytest.mark.anyio
async def test_slot_is_released_when_the_page_is_closed_midway() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:a")
    stream = _release_when_closed(_chunks(3), lease)

    assert await anext(stream) == "chunk0"
    await stream.aclose()  # 接続が切れると、サーバーは generator を閉じる

    assert limiter.active == 0


@pytest.mark.anyio
async def test_slot_is_released_when_the_stream_is_cancelled() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:a")
    gate = asyncio.Event()  # 2 件目で止めておく（モデルの応答待ちのつもり）

    async def consume() -> None:
        async for _ in _release_when_closed(_chunks(3, gate), lease):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert limiter.active == 0


@pytest.mark.anyio
async def test_slot_is_released_when_the_stream_fails() -> None:
    limiter = _limiter(FakeTime(_jst(11, 16, 20)))
    lease = limiter.acquire("s1", "did:plc:a")

    async def broken() -> AsyncIterator[str]:
        yield "chunk0"
        raise RuntimeError("推理の途中で失敗")

    with pytest.raises(RuntimeError):
        async for _ in _release_when_closed(broken(), lease):
            pass

    assert limiter.active == 0
