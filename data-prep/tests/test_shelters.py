from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import shelters
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.postal import Postal

PLACE_HEADER = [
    "NO",
    "共通ID",
    "施設・場所名",
    "住所",
    "洪水",
    "崖崩れ、土石流及び地滑り",
    "高潮",
    "地震",
    "津波",
    "大規模な火事",
    "内水氾濫",
    "火山現象",
    "指定避難所との住所同一",
    "緯度",
    "経度",
    "備考",
]
SHELTER_HEADER = [
    "NO",
    "共通ID",
    "施設・場所名",
    "住所",
    "指定緊急避難場所との住所同一",
    "その他市町村長が必要と認める事項",
    "受入対象者（指定福祉避難所のみ）",
    "緯度",
    "経度",
    "備考",
]
POSTALS = [
    Postal("1130031", "13105", "東京都", "文京区", "根津"),
    Postal("3600001", "11202", "埼玉県", "熊谷市", "曙町"),
    Postal("2310001", "14104", "神奈川県", "横浜市中区", "新港"),
    Postal("3550301", "11349", "埼玉県", "比企郡ときがわ町", "大野"),
    Postal("1001101", "13381", "東京都", "三宅島三宅村", "伊豆"),
    Postal("2440001", "14110", "神奈川県", "横浜市戸塚区", "鳥が丘"),
    Postal("2730101", "12224", "千葉県", "鎌ケ谷市", "富岡"),
]


def _place(
    muni: str, name: str, address: str, lat: str = "35.72", lon: str = "139.76"
) -> list[str]:
    return [
        "1",
        f"E{muni}00001001",
        name,
        address,
        "",
        "",
        "",
        "1",
        "",
        "",
        "",
        "",
        "",
        lat,
        lon,
        "",
    ]


def _shelter(muni: str, name: str, address: str) -> list[str]:
    return ["1", f"E{muni}00002001", name, address, "", "", "", "35.72", "139.76", ""]


def test_parse_finds_the_city_from_the_address_and_checks_the_common_id() -> None:
    places = [
        PLACE_HEADER,
        _place("13105", "根津小学校", "東京都文京区根津2-1"),
        # 政令市の共通IDは市のコード（14100）、郵便番号の表は区のコード
        _place("14100", "新港公園", "神奈川県横浜市中区新港1"),
        # 郡の名前を書かない住所
        _place("11349", "大野小学校", "埼玉県ときがわ町大字大野1"),
        # 島の名前を書かない住所
        _place("13381", "伊豆小学校", "東京都三宅村伊豆1"),
        # 互換漢字の「塚」（U+FA10）で書かれた住所
        _place("14100", "鳥が丘公園", "神奈川県横浜市戸\ufa10区鳥が丘1"),
        # 「ヶ」で書かれた住所
        _place("12224", "富岡公園", "千葉県鎌ヶ谷市富岡1"),
        # 隣の県にある施設（熊谷市が指定）は落とす
        _place("11202", "高林公民館", "群馬県太田市高林西町88"),
        # 住所の市区町村が共通IDと合わないものは落とす
        _place("13105", "どこかの広場", "埼玉県熊谷市曙町1"),
        # 緯度経度のないものは落とす
        _place("13105", "位置なし", "東京都文京区根津1", lat="", lon=""),
    ]
    rows = shelters.parse([("13000_2.csv", places)], POSTALS)

    assert [(r.name, r.muni_code, r.city, r.kind) for r in rows] == [
        ("根津小学校", "13105", "文京区", "指定緊急避難場所"),
        ("新港公園", "14104", "横浜市中区", "指定緊急避難場所"),
        ("大野小学校", "11349", "比企郡ときがわ町", "指定緊急避難場所"),
        ("伊豆小学校", "13381", "三宅島三宅村", "指定緊急避難場所"),
        ("鳥が丘公園", "14110", "横浜市戸塚区", "指定緊急避難場所"),
        ("富岡公園", "12224", "鎌ケ谷市", "指定緊急避難場所"),
    ]
    assert rows[0].mesh_1km == code_1km(35.72, 139.76)


def test_parse_reads_both_kinds_and_merges_the_same_place() -> None:
    files = [
        ("13000_2.csv", [PLACE_HEADER, _place("13105", "根津小学校", "東京都文京区根津2-1")]),
        ("13000_1.csv", [SHELTER_HEADER, _shelter("13105", "根津小学校", "東京都文京区根津2-1")]),
    ]

    rows = shelters.parse(files, POSTALS)

    assert [(r.name, r.kind) for r in rows] == [("根津小学校", "指定緊急避難場所・指定避難所")]


def test_parse_needs_the_columns() -> None:
    with pytest.raises(DataPrepError):
        shelters.parse([("a.csv", [["NO", "施設・場所名"]])], POSTALS)


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    assert shelters.load(paths, POSTALS) == []
    paths.gsi_dir.mkdir()
    lines = [",".join(PLACE_HEADER), ",".join(_place("13105", "根津小学校", "東京都文京区根津2-1"))]
    (paths.gsi_dir / "13000_2.csv").write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")

    rows = shelters.load(paths, POSTALS)
    shelters.write(rows, tmp_path / "shelters.parquet")

    table = pq.read_table(tmp_path / "shelters.parquet").to_pydict()
    assert table["name"] == ["根津小学校"]
    assert table["city"] == ["文京区"]
    assert set(table) == {"name", "kind", "muni_code", "city", "lat", "lon", "mesh_1km"}
