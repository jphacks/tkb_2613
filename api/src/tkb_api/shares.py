"""本人が明示的に作った閲覧リンクの結果を、期限付きで保持する。"""

import json
import os
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ShareStore:
    def __init__(
        self,
        path: Path,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS shares "
            "(token TEXT PRIMARY KEY, owner_did TEXT NOT NULL, "
            "expires_at REAL NOT NULL, payload TEXT NOT NULL)"
        )
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(shares)")}
        if "owner_did" not in columns:
            self._connection.execute(
                "ALTER TABLE shares ADD COLUMN owner_did TEXT NOT NULL DEFAULT ''"
            )
        self._connection.commit()
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def create(self, payload: dict[str, Any], owner_did: str) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 2_000_000:
            raise ValueError("共有する結果が大きすぎます")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._connection.execute(
                "INSERT INTO shares (token, owner_did, expires_at, payload) VALUES (?, ?, ?, ?)",
                (token, owner_did, self._clock() + self._ttl, encoded),
            )
            self._connection.commit()
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge()
            row = self._connection.execute(
                "SELECT payload FROM shares WHERE token = ?", (token,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def revoke(self, token: str, owner_did: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM shares WHERE token = ? AND owner_did = ?", (token, owner_did)
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _purge(self) -> None:
        self._connection.execute("DELETE FROM shares WHERE expires_at <= ?", (self._clock(),))
        self._connection.commit()
