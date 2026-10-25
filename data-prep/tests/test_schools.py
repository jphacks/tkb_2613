from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import schools
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.postal import Postal

HEADER = [
    "学校コード",
    "学校種",
    "都道府県番号",
    "設置\n区分",
    "本分校",
    "学校名",
    "学校所在地",
    "郵便番号",
    "属性情報\n設定年月日",
    "属性情報\n廃止年月日",
    "旧学校\n調査番号",
    "移行後の学校コード",
]
POSTALS = [
    Postal("1920393", "13201", "東京都", "八王子市", "東中野"),
    Postal("1900012", "13202", "東京都", "立川市", "曙町"),
]


def _row(
    code: str, kind: str, pref: str, name: str, address: str, postal: str, closed: str = ""
) -> list[str]:
    return [code, kind, pref, "3(私)", "1(本)", name, address, postal, "2021-01-20", closed, "", ""]


def test_parse_keeps_target_kinds_and_prefectures_and_finds_the_city() -> None:
    first = [
        HEADER,
        _row("F1", "F1(大学)", "13(東京)", "中央大学", "東京都八王子市東中野７４２－１", "1920393"),
        _row("B1", "B1(小学校)", "13(東京)", "どこかの小学校", "東京都八王子市東中野１", "1920393"),
        _row("F2", "F1(大学)", "01(北海道)", "北海道大学", "北海道札幌市北区", "0600808"),
        _row(
            "D9",
            "D1(高等学校)",
            "13(東京)",
            "閉じた高校",
            "東京都立川市曙町１",
            "1900012",
            "2024-03-31",
        ),
    ]
    # 見出しのない続きのファイル。郵便番号が表にないときは所在地の文字で市を探す
    rest = [
        _row(
            "D1",
            "D1(高等学校)",
            "13(東京)",
            "東京都立立川高等学校",
            "東京都立川市錦町２",
            "1909999",
        )
    ]

    rows = schools.parse([("a.csv", first), ("b.csv", rest)], POSTALS)

    assert [(r.name, r.kind, r.city, r.muni_code) for r in rows] == [
        ("中央大学", "大学", "八王子市", "13201"),
        ("東京都立立川高等学校", "高等学校", "立川市", "13202"),
    ]


def test_parse_needs_a_header() -> None:
    with pytest.raises(DataPrepError):
        schools.parse([("a.csv", [_row("F1", "F1(大学)", "13(東京)", "x", "y", "z")])], POSTALS)
    with pytest.raises(DataPrepError):
        schools.parse([("a.csv", [["学校コード", "学校名"]])], POSTALS)


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    with pytest.raises(DataPrepError):
        schools.load(paths, POSTALS)
    paths.mext_dir.mkdir()
    lines = [",".join(f'"{c}"' for c in HEADER)]
    lines.append(
        ",".join(_row("F1", "F1(大学)", "13(東京)", "中央大学", "東京都八王子市", "1920393"))
    )
    (paths.mext_dir / "u.csv").write_text("\ufeff" + "\n".join(lines) + "\n", encoding="utf-8")

    rows = schools.load(paths, POSTALS)
    schools.write(rows, tmp_path / "schools.parquet")

    table = pq.read_table(tmp_path / "schools.parquet").to_pydict()
    assert table["name"] == ["中央大学"]
    assert table["city"] == ["八王子市"]
