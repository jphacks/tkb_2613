import io
import zipfile
from pathlib import Path

import jismesh.utils as ju
import numpy as np
import osmium
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapefile
from shapely.geometry import box

from tkb_data_prep import census_age, mesh100, roads, scoring_tables, towns, walk
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

# 東西にのびる1本の道（緯度 35.7130、経度 139.7600〜139.7700）。点は約 300m おき
ROAD_LAT = 35.7130
ROAD_LONS = (139.7600, 139.7633, 139.7666, 139.7700)


def write_pbf(path: Path, ways: list[tuple[list[tuple[float, float]], dict[str, str]]]) -> None:
    """ways：（[(緯度, 経度), …], タグ）の並び。点の ID は通し番号。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    writer = osmium.SimpleWriter(str(path))
    node_id = 1
    refs: list[list[int]] = []
    try:
        for points, _ in ways:
            ids: list[int] = []
            for lat, lon in points:
                writer.add_node(osmium.osm.mutable.Node(id=node_id, location=(lon, lat)))
                ids.append(node_id)
                node_id += 1
            refs.append(ids)
        for way_id, ((_, tags), ids) in enumerate(zip(ways, refs, strict=True), start=1):
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=ids, tags=tags))
    finally:
        writer.close()


def write_boundary(
    path: Path, pref: str, towns: list[tuple[str, str, list[tuple[float, float]]]]
) -> None:
    """towns：（KEY_CODE, 町丁目の名前, 外周の [(経度, 緯度), …]）。"""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(
        shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="cp932"
    )
    for name, kind, size in (
        ("KEY_CODE", "C", 11),
        ("PREF", "C", 2),
        ("CITY", "C", 3),
        ("CITY_NAME", "C", 16),
        ("S_NAME", "C", 96),
        ("HCODE", "N", 4),
        ("JINKO", "N", 10),
    ):
        writer.field(name, kind, size=size)
    for key, name, ring in towns:
        writer.poly([ring])
        writer.record(key, pref, key[2:5], "文京区", name, 8101, 100)
    writer.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"r2ka{pref}.shp", shp.getvalue())
        archive.writestr(f"r2ka{pref}.shx", shx.getvalue())
        archive.writestr(f"r2ka{pref}.dbf", dbf.getvalue())


def age_csv(rows: list[tuple[str, int, int]]) -> str:
    """rows：（500m メッシュ, 総数, 20〜24歳）。"""
    codes = ",".join(f"T001192{i:03d}" for i in range(1, 22))
    names = ",".join(
        ["　人口（総数）"]
        + [f"　{5 * i}～{5 * i + 4}歳人口　総数" for i in range(19)]
        + ["　９５歳以上人口　総数"]
    )
    lines = [f"KEY_CODE,HTKSYORI,HTKSAKI,GASSAN,{codes}", f",,,,{names}"]
    for mesh, total, young in rows:
        classes = [str(young if i == 4 else 0) for i in range(20)]
        lines.append(",".join([mesh, "0", "", "", str(total), *classes]))
    return "\r\n".join(lines) + "\r\n"


def write_age_zips(paths: Paths, rows: list[tuple[str, int, int]]) -> None:
    paths.estat_age_dir.mkdir(parents=True, exist_ok=True)
    for code in census_age.FIRST_MESHES:
        body = age_csv([r for r in rows if r[0].startswith(code)])
        with zipfile.ZipFile(paths.estat_age_dir / f"tblT001192H{code}.zip", "w") as archive:
            archive.writestr(f"tblT001192H{code}.txt", body.encode("cp932"))


# 根津駅のあたりの 500m メッシュ（5339465 + 1km メッシュ内の位置 1, 南西）
MESH_500M = "533946511"


def test_cells_of_500m_match_jismesh_centers() -> None:
    cells = mesh100.cells_of_500m(MESH_500M)

    assert len(cells) == 25
    lat_500, lon_500 = ju.to_meshpoint(MESH_500M, 0.5, 0.5)
    assert np.mean([c[1] for c in cells]) == pytest.approx(float(lat_500))
    assert np.mean([c[2] for c in cells]) == pytest.approx(float(lon_500))
    # 北東の 500m メッシュ（末尾 4）は、1km メッシュの中の南北・東西とも 5〜9 番
    assert {str(c[0])[8:] for c in mesh100.cells_of_500m("533946514")} >= {"55", "99"}


def test_cells_of_500m_rejects_other_codes() -> None:
    with pytest.raises(ValueError, match="500m"):
        mesh100.cells_of_500m("53394651")


def test_grid_orders_cells_by_mesh() -> None:
    codes, lat, lon = mesh100.grid([MESH_500M, "533946512"])
    assert codes.shape == (50,)
    assert str(codes[0]).startswith("53394651") and lat.shape == lon.shape == (50,)


def straight_road(tmp_path: Path) -> roads.RoadGraph:
    pbf = tmp_path / "osm" / "t.osm.pbf"
    write_pbf(
        pbf,
        [
            ([(ROAD_LAT, lon) for lon in ROAD_LONS], {"highway": "residential"}),
            # 高速道路と、歩行者が通れない道は使わない
            ([(ROAD_LAT + 0.001, 139.76), (ROAD_LAT + 0.001, 139.77)], {"highway": "motorway"}),
            (
                [(ROAD_LAT + 0.002, 139.76), (ROAD_LAT + 0.002, 139.77)],
                {"highway": "footway", "foot": "no"},
            ),
            # 範囲の外の道は捨てる
            ([(40.0, 141.0), (40.001, 141.0)], {"highway": "residential"}),
        ],
    )
    return roads.load(pbf, tmp_path / "osm" / "graph.npz")


def test_road_graph_keeps_walkable_ways_and_splits_long_segments(tmp_path: Path) -> None:
    graph = straight_road(tmp_path)

    # 約 900m の道を 40m 以下に分けるので、点は 23 個以上
    assert graph.size >= 23
    assert graph.lat.max() == pytest.approx(ROAD_LAT)
    longest = float(graph.graph.data.max())
    assert longest <= roads.SEGMENT_MAX_M + 1e-6
    total = float(graph.graph.data.sum()) / 2
    expected = roads.haversine_array(
        np.array([ROAD_LAT]),
        np.array([ROAD_LONS[0]]),
        np.array([ROAD_LAT]),
        np.array([ROAD_LONS[-1]]),
    )[0]
    assert total == pytest.approx(expected, rel=1e-6)


def test_road_graph_is_cached_until_pbf_changes(tmp_path: Path) -> None:
    first = straight_road(tmp_path)
    cache = tmp_path / "osm" / "graph.npz"
    assert cache.is_file()
    again = roads.load(tmp_path / "osm" / "t.osm.pbf", cache)
    assert again.size == first.size


def test_road_graph_requires_pbf(tmp_path: Path) -> None:
    with pytest.raises(DataPrepError, match="ありません"):
        roads.load(tmp_path / "none.pbf", tmp_path / "g.npz")


def test_walk_table_measures_distance_along_the_road(tmp_path: Path) -> None:
    graph = straight_road(tmp_path)
    walker = walk.Walker(graph)
    # 駅は道の西の端、マスは道に沿って 0m・約300m・約600m・約900m と、道から遠いマス
    station = walker.snap(np.array([ROAD_LAT]), np.array([ROAD_LONS[0]]))
    cells = walker.snap(
        np.array([ROAD_LAT + 0.0001] * 4 + [ROAD_LAT + 0.01]),
        np.array([*ROAD_LONS, ROAD_LONS[0]]),
    )
    assert cells.node[-1] == -1  # 道から 1km 以上離れたマスは道につながらない

    table = walk.walk_table(walker, station, cells, 650.0)
    by_cell = dict(zip(table.cell.tolist(), table.distance.tolist(), strict=True))
    assert sorted(by_cell) == [0, 1, 2]
    assert by_cell[0] == pytest.approx(0.0, abs=1e-3)
    assert by_cell[1] == pytest.approx(298, abs=5)
    assert by_cell[2] == pytest.approx(597, abs=5)

    nearest, nearest_m = walk.nearest_place(walker, station, cells, 1000.0)
    assert nearest.tolist() == [0, 0, 0, 0, -1]
    assert nearest_m[3] == pytest.approx(900, abs=10)
    assert np.isnan(nearest_m[4])


def town_ring(west: float, south: float, east: float, north: float) -> list[tuple[float, float]]:
    return list(box(west, south, east, north).exterior.coords)


def test_towns_merge_pieces_by_key_code(tmp_path: Path) -> None:
    path = tmp_path / "A002005212020DDSWC13-JGD2011.zip"
    write_boundary(
        path,
        "13",
        [
            ("13105025002", "弥生二丁目", town_ring(139.760, 35.712, 139.765, 35.716)),
            ("13105025002", "弥生二丁目", town_ring(139.770, 35.712, 139.771, 35.713)),
            ("13105025001", "弥生一丁目", town_ring(139.755, 35.712, 139.760, 35.716)),
        ],
    )
    loaded = {t.name: t for t in towns.read_zip(path)}

    assert set(loaded) == {"弥生二丁目", "弥生一丁目"}
    yayoi = loaded["弥生二丁目"]
    assert yayoi.muni_code == "13105"
    assert yayoi.geometry.geom_type == "MultiPolygon"
    lat, lon = yayoi.point
    assert yayoi.geometry.contains(box(lon, lat, lon, lat).centroid)


def build_paths(tmp_path: Path) -> Paths:
    paths = Paths(
        raw_dir=tmp_path / "raw", manual_dir=tmp_path / "manual", out_dir=tmp_path / "out"
    )
    for pref in ("11", "12", "13", "14"):
        towns_in = (
            [("13105025002", "弥生二丁目", town_ring(139.755, 35.70, 139.775, 35.72))]
            if pref == "13"
            else []
        )
        write_boundary(
            paths.census_boundary_dir / f"A002005212020DDSWC{pref}-JGD2011.zip", pref, towns_in
        )
    write_age_zips(paths, [(MESH_500M, 100, 10)])
    write_pbf(paths.osm_pbf, [([(ROAD_LAT, lon) for lon in ROAD_LONS], {"highway": "residential"})])
    stat_mesh = "都道府県市区町村コード,市区町村名,基準メッシュ・コード\r\n"
    for pref in ("11", "12", "13", "14"):
        csv = paths.stat_mesh_csv(pref)
        csv.parent.mkdir(parents=True, exist_ok=True)
        body = "13105,文京区,53394651\r\n" if pref == "13" else ""
        csv.write_bytes((stat_mesh + body).encode("cp932"))
    paths.out_dir.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "station_name": ["根津"],
                "line_name": ["9号線千代田線"],
                "operator": ["東京地下鉄"],
                "lat": [ROAD_LAT],
                "lon": [ROAD_LONS[1]],
            }
        ),
        paths.out_dir / "stations.parquet",
    )
    pq.write_table(
        pa.table(
            {"name": ["根津駅前"], "operator": ["東京都"], "lat": [ROAD_LAT], "lon": [ROAD_LONS[2]]}
        ),
        paths.out_dir / "bus_stops.parquet",
    )
    return paths


def test_build_writes_all_scoring_tables(tmp_path: Path) -> None:
    paths = build_paths(tmp_path)
    assert scoring_tables.inputs_ready(paths)

    built = scoring_tables.build(paths, lambda _message: None)

    assert built.cells == 25
    cells = pq.read_table(built.files["cells"]).to_pydict()
    assert len(cells["cell"]) == 25
    assert set(cells["town"]) == {0}
    assert set(cells["school"]) == {-1}
    station_walk = pq.read_table(built.files["station_walk"]).to_pydict()
    assert station_walk["cell"] and max(station_walk["distance"]) <= scoring_tables.STATION_WALK_M
    bus_walk = pq.read_table(built.files["bus_walk"]).to_pydict()
    assert max(bus_walk["distance"]) <= scoring_tables.BUS_STOP_WALK_M
    ages = pq.read_table(built.files["age_500m"]).to_pydict()
    assert ages["age_20"] == [10.0]


def test_main_skips_when_raw_data_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(scoring_tables, "Paths", lambda: Paths(raw_dir=tmp_path, out_dir=tmp_path))

    assert scoring_tables.main() == 0
    assert "作りません" in capsys.readouterr().err


def test_main_builds_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = build_paths(tmp_path)
    monkeypatch.setattr(scoring_tables, "Paths", lambda: paths)

    assert scoring_tables.main() == 0
    assert "100m マス 25 個" in capsys.readouterr().err


def test_main_reports_data_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = build_paths(tmp_path)
    (paths.estat_age_dir / "tblT001192H5238.zip").unlink()
    monkeypatch.setattr(scoring_tables, "Paths", lambda: paths)

    assert scoring_tables.main() == 1
    assert "5238" in capsys.readouterr().err
