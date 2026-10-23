import json
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import stations
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.mesh import code_1km


def feature(code: str, name: str, line: str, geometry: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "N02_001": "12",
            "N02_002": "5",
            "N02_003": line,
            "N02_004": "京王電鉄",
            "N02_005": name,
            "N02_005c": code,
            "N02_005g": code,
        },
        "geometry": geometry,
    }


def line(*points: tuple[float, float]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": [list(p) for p in points]}


SHINJUKU_1KM = code_1km(35.6896, 139.7006)
ALLOWED = frozenset({SHINJUKU_1KM})


def test_parse_merges_split_lines_and_weights_by_length() -> None:
    geojson = {
        "features": [
            # 同じ駅コード・同じ路線が 2 本に分かれている。長い方に中心が寄る
            feature("003700", "新宿", "京王線", line((139.6990, 35.6896), (139.7010, 35.6896))),
            feature("003700", "新宿", "京王線", line((139.7010, 35.6896), (139.7020, 35.6896))),
            # 1都3県の外
            feature("009999", "甲府", "中央線", line((138.5, 35.66), (138.51, 35.66))),
        ]
    }

    [shinjuku] = stations.parse(geojson, ALLOWED)

    assert (shinjuku.station_name, shinjuku.line_name, shinjuku.operator) == (
        "新宿",
        "京王線",
        "京王電鉄",
    )
    assert shinjuku.lon == pytest.approx(139.7005)
    assert shinjuku.lat == pytest.approx(35.6896)
    assert shinjuku.mesh_1km == SHINJUKU_1KM


def test_parse_handles_multilinestring_and_zero_length() -> None:
    multi = {
        "type": "MultiLineString",
        "coordinates": [[[139.700, 35.689], [139.701, 35.689]], [[139.702, 35.689]]],
    }
    point_like = line((139.7006, 35.6896), (139.7006, 35.6896))
    geojson = {
        "features": [
            feature("1", "A", "X線", multi),
            feature("2", "B", "X線", point_like),
        ]
    }

    a, b = stations.parse(geojson, ALLOWED)

    assert a.lon == pytest.approx(139.7005)
    assert (b.lat, b.lon) == pytest.approx((35.6896, 139.7006))


@pytest.mark.parametrize(
    "bad",
    [
        {"properties": {"N02_005": "新宿"}, "geometry": line((0, 0), (1, 1))},
        feature("1", "A", "X線", {"type": "Point", "coordinates": [139.7, 35.69]}),
        feature("1", "A", "X線", {"type": "LineString", "coordinates": []}),
    ],
)
def test_parse_rejects_unexpected_features(bad: dict[str, Any]) -> None:
    with pytest.raises(DataPrepError):
        stations.parse({"features": [bad]}, ALLOWED)


def test_load_reads_utf8_geojson_from_zip(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    paths.stations_zip.parent.mkdir(parents=True)
    shinjuku = feature("1", "新宿", "京王線", line((139.70, 35.6896), (139.701, 35.6896)))
    geojson = {"features": [shinjuku]}
    with zipfile.ZipFile(paths.stations_zip, "w") as archive:
        archive.writestr("Shift-JIS/N02-24_Station.shp", b"")
        archive.writestr(stations.GEOJSON_SUFFIX, json.dumps(geojson, ensure_ascii=False))

    rows = stations.load(paths, ALLOWED)
    stations.write(rows, tmp_path / "s.parquet")

    table = pq.read_table(tmp_path / "s.parquet").to_pydict()
    assert table["station_name"] == ["新宿"]
    assert table["mesh_1km"] == [SHINJUKU_1KM]
