"""法人の一覧（法人番号、商号、正規化した商号、フリガナ、都道府県）を SQLite にする。

入力は国税庁「法人番号公表サイト」の基本3情報の全件データ（CSV 形式・Shift-JIS の zip）。
ブラウザで取得して data-prep/raw/houjin/ に置く（fetch.sh では取得しない）。置かれていなければ
表を作らずに先へ進む（表がなくても推定は動く）。

CSV は見出しなしの 30 列（リソース定義書 4.0版）。使うのは次の列だけ。
最新履歴で、閉鎖されておらず、検索対象除外でない行を、1都3県の分だけ残す。
本店所在地は入れない（勤務地の推定に使わないため）。

全件で約 226 万行あるので、行をメモリに溜めずに読みながら SQLite に書き、
正規化した商号に索引を付ける。
api は推定のときにだけ、このファイルを読み取り専用で開いて索引を引く。
"""

import csv
import io
import re
import sqlite3
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from tkb_common.corporate_name import normalize_corporate_name
from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError

COL_NUMBER = 1
COL_NAME = 6
COL_PREF_CODE = 13
COL_CLOSED = 18
COL_LATEST = 23
COL_FURIGANA = 28
COL_HIDDEN = 29
MIN_COLUMNS = COL_HIDDEN + 1
ENCODING = "cp932"
AS_OF = re.compile(r"_(\d{4})(\d{2})(\d{2})(?:_\d+)?\.zip$")
BATCH = 10_000


@dataclass(frozen=True)
class Corporation:
    corporate_number: str
    name: str
    normalized_name: str
    furigana: str
    pref_code: str


@dataclass(frozen=True)
class BuildResult:
    rows: int
    as_of: str  # データの時点（ファイル名の日付。置かれていなければ空）


def parse(rows: Iterable[list[str]]) -> Iterator[Corporation]:
    for row in rows:
        if len(row) < MIN_COLUMNS:
            continue
        pref = row[COL_PREF_CODE].strip()
        if (
            row[COL_LATEST].strip() != "1"
            or row[COL_CLOSED].strip()
            or row[COL_HIDDEN].strip() != "0"
            or pref not in PREFECTURES
        ):
            continue
        name = row[COL_NAME].strip()
        normalized = normalize_corporate_name(name)
        if not normalized:
            continue
        yield Corporation(
            row[COL_NUMBER].strip(), name, normalized, row[COL_FURIGANA].strip(), pref
        )


def build(paths: Paths, out: Path) -> BuildResult:
    """zip がなければ何も作らない。作り直すときは一時ファイルに書いてから置き換える。"""
    zips = sorted(paths.houjin_dir.glob("*.zip")) if paths.houjin_dir.is_dir() else []
    if not zips:
        return BuildResult(0, "")
    as_of = _as_of(zips)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".sqlite.part")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as db:
        db.executescript(
            """
            CREATE TABLE corporations (
              corporate_number TEXT NOT NULL,
              name TEXT NOT NULL,
              normalized_name TEXT NOT NULL,
              furigana TEXT NOT NULL,
              pref_code TEXT NOT NULL
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        count = 0
        for path in zips:
            count += _insert(db, parse(_read_rows(path)))
        db.execute("CREATE INDEX corporations_normalized_name ON corporations (normalized_name)")
        db.execute("INSERT INTO meta VALUES ('as_of', ?)", (as_of,))
        db.commit()
    tmp.replace(out)
    return BuildResult(count, as_of)


def _insert(db: sqlite3.Connection, rows: Iterable[Corporation]) -> int:
    count = 0
    batch: list[tuple[str, str, str, str, str]] = []
    for c in rows:
        batch.append((c.corporate_number, c.name, c.normalized_name, c.furigana, c.pref_code))
        if len(batch) >= BATCH:
            db.executemany("INSERT INTO corporations VALUES (?, ?, ?, ?, ?)", batch)
            count += len(batch)
            batch = []
    db.executemany("INSERT INTO corporations VALUES (?, ?, ?, ?, ?)", batch)
    return count + len(batch)


def _read_rows(path: Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise DataPrepError(f"{path}: CSV が 1 つではありません: {names}")
        with archive.open(names[0]) as raw:
            yield from csv.reader(io.TextIOWrapper(raw, encoding=ENCODING, newline=""))


def _as_of(zips: list[Path]) -> str:
    dates = {f"{m[1]}-{m[2]}-{m[3]}" for p in zips if (m := AS_OF.search(p.name))}
    if len(dates) > 1:
        raise DataPrepError(f"{zips[0].parent}: 時点の違う zip が混ざっています: {sorted(dates)}")
    return next(iter(dates), "")
