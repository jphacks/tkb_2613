import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq

from tkb_data_prep import ridership
from tkb_data_prep.config import Paths


def _feature(
    code: str, name: str, operator: str, values: dict[int, tuple[int, int, int]]
) -> dict[str, object]:
    """values は 年度 → (重複コード, データ有無コード, 乗降客数)。"""
    props: dict[str, object] = {
        "S12_001": name,
        "S12_001c": code,
        "S12_002": operator,
        "S12_003": "線",
    }
    for year, (dup, has, passengers) in values.items():
        base = 6 + (year - 2011) * 4
        props[f"S12_{base:03d}"] = dup
        props[f"S12_{base + 1:03d}"] = has
        props[f"S12_{base + 2:03d}"] = None
        props[f"S12_{base + 3:03d}"] = passengers
    return {"type": "Feature", "properties": props, "geometry": None}


def test_parse_uses_the_latest_year_and_skips_duplicates_and_missing_data() -> None:
    geojson = {
        "features": [
            _feature("003483", "根津", "東京地下鉄", {2023: (1, 1, 26589), 2024: (1, 1, 27937)}),
            # 重複（別の行に含まれる）とデータなしは数えない
            _feature("003701", "新宿", "東日本旅客鉄道", {2024: (2, 1, 0)}),
            _feature("003999", "無人", "東日本旅客鉄道", {2024: (1, 2, 0)}),
            # 1都3県の駅の表にない駅は落とす
            _feature("009999", "甲府", "東日本旅客鉄道", {2024: (1, 1, 30000)}),
        ]
    }

    year, rows = ridership.parse(geojson, {"003483", "003701", "003999"})

    assert year == 2024
    assert [(r.station_code, r.station_name, r.passengers) for r in rows] == [
        ("003483", "根津", 27937)
    ]


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    assert ridership.load(paths, {"003483"}) == (0, [])
    paths.ridership_zip.parent.mkdir(parents=True)
    geojson = {"features": [_feature("003483", "根津", "東京地下鉄", {2024: (1, 1, 27937)})]}
    with zipfile.ZipFile(paths.ridership_zip, "w") as archive:
        archive.writestr("S12-25_GML/Shift-JIS/S12-25_NumberOfPassengers.geojson", b"")
        archive.writestr(ridership.GEOJSON_SUFFIX, json.dumps(geojson, ensure_ascii=False))

    year, rows = ridership.load(paths, {"003483"})
    ridership.write(rows, year, tmp_path / "ridership.parquet")

    table = pq.read_table(tmp_path / "ridership.parquet").to_pydict()
    assert table == {
        "station_code": ["003483"],
        "station_name": ["根津"],
        "operator": ["東京地下鉄"],
        "passengers": [27937],
        "year": [2024],
    }
