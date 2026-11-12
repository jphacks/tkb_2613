import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import boundaries, bus_stops
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal

NEZU = (35.7176, 139.7652)
BORDER = (35.70, 139.70)
OUTSIDE = (36.5, 138.5)
MUNIS = [
    MuniMesh("13105", "文京区", code_1km(*NEZU)),
    MuniMesh("13104", "新宿区", code_1km(*BORDER)),
    MuniMesh("13113", "渋谷区", code_1km(*BORDER)),
]
POSTALS = [Postal("1130031", "13105", "東京都", "文京区", "根津")]


def _feature(name: str, operator: str, point: tuple[float, float]) -> dict[str, object]:
    lat, lon = point
    return {
        "type": "Feature",
        "properties": {"P11_001": name, "P11_002": operator, "P11_003_01": "系統"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def test_parse_lists_every_municipality_the_mesh_touches() -> None:
    geojson = {
        "features": [
            _feature("根津一丁目", "東京都", NEZU),
            _feature("境目", "京王バス（株）", BORDER),
            _feature("遠く", "どこかバス", OUTSIDE),
        ]
    }

    rows = bus_stops.parse(geojson, MUNIS, POSTALS)

    assert [(r.name, r.operator, r.muni_codes, r.cities) for r in rows] == [
        ("根津一丁目", "東京都", ("13105",), ("文京区",)),
        ("境目", "京王バス（株）", ("13104", "13113"), ("新宿区", "渋谷区")),
    ]
    assert rows[0].mesh_1km == code_1km(*NEZU)


def test_parse_uses_the_boundary_when_it_has_one() -> None:
    locator = boundaries.Locator.from_geojson(
        [
            {
                "features": [
                    {
                        "properties": {"N03_007": "13113"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [139.69, 35.69],
                                    [139.71, 35.69],
                                    [139.71, 35.71],
                                    [139.69, 35.71],
                                    [139.69, 35.69],
                                ]
                            ],
                        },
                    }
                ]
            }
        ]
    )
    geojson = {
        "features": [_feature("境目", "京王バス（株）", BORDER), _feature("根津", "東京都", NEZU)]
    }

    rows = bus_stops.parse(geojson, MUNIS, POSTALS, locator)

    # 境界に入れば1つに決まる。入らなければメッシュの候補のまま
    assert [(r.name, r.cities) for r in rows] == [("境目", ("渋谷区",)), ("根津", ("文京区",))]


def test_parse_merges_the_same_stop_and_operator_in_one_mesh() -> None:
    geojson = {
        "features": [
            _feature("根津一丁目", "東京都", NEZU),
            _feature("根津一丁目", "東京都", (NEZU[0] + 0.0001, NEZU[1])),
        ]
    }
    assert len(bus_stops.parse(geojson, MUNIS, POSTALS)) == 1


def test_parse_rejects_unexpected_shapes() -> None:
    bad = {"features": [{"properties": {"P11_001": "x", "P11_002": "y"}, "geometry": {}}]}
    with pytest.raises(DataPrepError):
        bus_stops.parse(bad, MUNIS, POSTALS)


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    assert bus_stops.load(paths, MUNIS, POSTALS) == []
    zip_path = paths.ksj_bus_stop_zip("13")
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "P11-22_13_SHP/P11-22_13.geojson",
            json.dumps({"features": [_feature("根津一丁目", "東京都", NEZU)]}),
        )

    rows = bus_stops.load(paths, MUNIS, POSTALS)
    bus_stops.write(rows, tmp_path / "bus_stops.parquet")

    table = pq.read_table(tmp_path / "bus_stops.parquet").to_pydict()
    assert table["name"] == ["根津一丁目"]
    assert table["cities"] == [["文京区"]]
    assert set(table) == {"name", "operator", "muni_codes", "cities", "lat", "lon", "mesh_1km"}
