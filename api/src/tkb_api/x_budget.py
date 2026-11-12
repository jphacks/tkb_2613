"""X API の1日の取得件数（課金対象のリソース数）の上限。

X は返されたリソース数で課金する。呼ぶ前に「読む可能性のある最大数」を予約し、
上限を超えるなら X を呼ばずに断る。実際に読んだ数が少なくても返金せず、保守的に数える。
カウンタはプロセスのメモリだけに置くので、再起動で 0 に戻る。最終的な歯止めは
X Developer Console の支出上限（spending limit）にする。
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from threading import Lock

from tkb_api.x_poc import MIN_PAGE_SIZE

# 本人確認（GET /2/users/me）は User Read 1 リソース
USER_READ_RESOURCES = 1


def posts_read_cost(max_posts: int) -> int:
    """投稿一覧の取得で読む可能性のある最大リソース数（API の max_results は最低 5）。"""
    return max(MIN_PAGE_SIZE, max_posts)


def one_check_cost(max_posts: int) -> int:
    """OAuth 後の本人確認と、1回の投稿取得を合わせた最大リソース数。"""
    return USER_READ_RESOURCES + posts_read_cost(max_posts)


def _utc_today() -> date:
    return datetime.now(UTC).date()


class DailyResourceBudget:
    """UTC の日付ごとに、予約したリソース数を数える。"""

    def __init__(self, limit: int, today: Callable[[], date] = _utc_today) -> None:
        self.limit = limit
        self._today = today
        self._day = today()
        self._used = 0
        self._lock = Lock()

    def _roll(self) -> None:
        day = self._today()
        if day != self._day:
            self._day = day
            self._used = 0

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.limit - self._used)

    def can_afford(self, amount: int) -> bool:
        return amount <= self.remaining()

    def reserve(self, amount: int) -> bool:
        """amount を予約できれば True。足りなければ何も数えずに False。"""
        if amount < 0:
            raise ValueError("amount は 0 以上にしてください")
        with self._lock:
            self._roll()
            if self._used + amount > self.limit:
                return False
            self._used += amount
            return True
