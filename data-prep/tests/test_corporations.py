import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from tkb_data_prep import corporations
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError


def _row(
    number: str,
    name: str,
    *,
    pref_code: str = "13",
    closed: str = "",
    latest: str = "1",
    hidden: str = "0",
    furigana: str = "",
    process: str = "01",
) -> list[str]:
    """法人番号公表サイトの全件データの1行（30列、見出しなし）。"""
    row = [""] * 30
    row[0], row[1], row[2] = "1", number, process
    row[6], row[8] = name, "301"
    row[9], row[13] = "東京都", pref_code
    row[18], row[23], row[28], row[29] = closed, latest, furigana, hidden
    return row


def _zip(path: Path, member: str, rows: list[list[str]]) -> None:
    text = "".join(",".join(f'"{c}"' for c in r) + "\r\n" for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, text.encode("cp932"))


def test_parse_keeps_only_open_latest_searchable_rows_in_the_target_prefectures() -> None:
    rows = [
        _row("1000000000001", "株式会社青空商事", furigana="アオゾラショウジ"),
        _row("1000000000002", "閉じた商事株式会社", closed="2024-03-31", process="21"),
        _row("1000000000003", "古い名前株式会社", latest="0"),
        _row("1000000000004", "除外株式会社", hidden="1"),
        _row("1000000000005", "大阪商事株式会社", pref_code="27"),
        _row("1000000000006", "株式会社"),
        ["短い行"],
    ]

    found = list(corporations.parse(rows))

    assert [(c.corporate_number, c.name, c.normalized_name, c.furigana) for c in found] == [
        ("1000000000001", "株式会社青空商事", "青空商事", "アオゾラショウジ")
    ]


def test_load_and_write_streams_every_zip_into_sqlite(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path / "raw")
    _zip(
        paths.houjin_dir / "13_tokyo_all_20261030_01.zip",
        "13_tokyo_all_20261030_01.csv",
        [
            _row("1000000000001", "株式会社青空商事"),
        ],
    )
    _zip(
        paths.houjin_dir / "13_tokyo_all_20261030_02.zip",
        "13_tokyo_all_20261030_02.csv",
        [
            _row("1000000000002", "(株)青空商事"),
            _row("1000000000003", "夕焼け工業株式会社"),
        ],
    )
    out = tmp_path / "corporations.sqlite"

    result = corporations.build(paths, out)

    assert result.rows == 3
    assert result.as_of == "2026-10-30"
    with closing(sqlite3.connect(out)) as db:
        rows = db.execute(
            "SELECT corporate_number, name FROM corporations WHERE normalized_name = ?",
            ("青空商事",),
        ).fetchall()
        meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    assert sorted(rows) == [
        ("1000000000001", "株式会社青空商事"),
        ("1000000000002", "(株)青空商事"),
    ]
    assert meta["as_of"] == "2026-10-30"


def test_build_skips_when_nothing_is_placed(tmp_path: Path) -> None:
    out = tmp_path / "corporations.sqlite"
    result = corporations.build(Paths(raw_dir=tmp_path), out)
    assert result.rows == 0
    assert not out.exists()


def test_build_rejects_a_zip_without_a_csv(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    paths.houjin_dir.mkdir()
    with zipfile.ZipFile(paths.houjin_dir / "13_tokyo_all_20261030.zip", "w") as archive:
        archive.writestr("readme.txt", "x")
    with pytest.raises(DataPrepError):
        corporations.build(paths, tmp_path / "corporations.sqlite")
