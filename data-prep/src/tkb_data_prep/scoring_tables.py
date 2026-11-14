"""住まいの推定（点数の地図）に使う表を作る。

uv run python -m tkb_data_prep.scoring_tables

先に `uv run python -m tkb_data_prep`（駅・バス停・学区の表）を作っておく。
入力の生データ（年齢別人口・小地域境界・OpenStreetMap）がなければ、何も書かずに終わる
（表がなければ、api は住まいの推定を出さずに今までどおり動く）。

書き出す表（data/processed/）：
- scoring_age_500m.parquet   500m メッシュごとの年齢5歳階級別人口（秘匿を割り戻したもの）
- scoring_towns.parquet      町丁目（名前・市区町村・代表の点・人口）
- scoring_cells.parquet      100m マス（人口のある 500m メッシュの中だけ）。メッシュ・町丁目・
                             小学校区の番号と、道のりで一番近い駅とその道のり
- scoring_stations.parquet / scoring_station_walk.parquet  駅と、道のり 800m 以内のマス
- scoring_bus_stops.parquet / scoring_bus_walk.parquet     バス停と、道のり 300m 以内のマス
- scoring_schools.parquet    小学校区の学校（利用条件で取り込めたものだけ）
"""

import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from tkb_data_prep import census_age, mesh100, muni_mesh, roads, towns
from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_zip_member
from tkb_data_prep.walk import Snapped, Walker, WalkTable, nearest_place, walk_table

# 国土交通省「都市構造の評価に関するハンドブック」（2014）の徒歩圏
STATION_WALK_M = 800.0
BUS_STOP_WALK_M = 300.0
# 「最寄り駅まで徒歩N分」で使う、一番近い駅を探す道のりの上限（徒歩30分＝2400m）
NEAREST_STATION_LIMIT_M = 2400.0

PREFIX = "scoring_"


@dataclass(frozen=True)
class Built:
    files: dict[str, Path]
    cells: int
    seconds: float


def inputs_ready(paths: Paths) -> bool:
    return (
        paths.estat_age_dir.is_dir()
        and paths.census_boundary_dir.is_dir()
        and paths.osm_pbf.is_file()
        and (paths.out_dir / "stations.parquet").is_file()
        and (paths.out_dir / "bus_stops.parquet").is_file()
    )


def build(paths: Paths, log: Callable[[str], None]) -> Built:
    started = time.monotonic()
    out = paths.out_dir
    allowed = muni_mesh.meshes(muni_mesh.load(paths))

    ages = census_age.load(paths, allowed)
    log(f"年齢別人口：500m メッシュ {len(ages)} 件")
    town_rows = towns.load(paths)
    log(f"町丁目：{len(town_rows)} 件")

    meshes = [a.mesh_500m for a in ages]
    codes, lat, lon = mesh100.grid(meshes)
    mesh_index = np.repeat(np.arange(len(meshes), dtype=np.int32), mesh100.CELLS_PER_500M)
    points = shapely.points(lon, lat)
    town_of = _containing(points, [t.geometry for t in town_rows])
    log(f"100m マス：{codes.shape[0]} 個（町丁目の中 {int((town_of >= 0).sum())} 個）")

    schools, school_shapes = _school_districts(paths)
    school_of = _containing(points, school_shapes)

    stations = pq.read_table(out / "stations.parquet").to_pylist()
    bus_stops = pq.read_table(out / "bus_stops.parquet").to_pylist()

    graph = roads.load(paths.osm_pbf, paths.road_graph_cache)
    log(f"道路網：点 {graph.size} 個")
    walker = Walker(graph)
    cell_nodes = walker.snap(lat, lon)
    station_nodes = _snap_rows(walker, stations)
    bus_nodes = _snap_rows(walker, bus_stops)
    nearest, nearest_m = nearest_place(walker, station_nodes, cell_nodes, NEAREST_STATION_LIMIT_M)
    log("一番近い駅：計算しました")
    station_walk = walk_table(walker, station_nodes, cell_nodes, STATION_WALK_M)
    log(f"駅の徒歩圏：{station_walk.cell.shape[0]} 行")
    bus_walk = walk_table(walker, bus_nodes, cell_nodes, BUS_STOP_WALK_M)
    log(f"バス停の徒歩圏：{bus_walk.cell.shape[0]} 行")

    files = {
        "age_500m": _write_ages(ages, out),
        "towns": _write(towns.columns(town_rows), towns.SCHEMA, out / f"{PREFIX}towns.parquet"),
        "cells": _write(
            {
                "cell": codes,
                "lat": lat.astype(np.float32),
                "lon": lon.astype(np.float32),
                "mesh": mesh_index,
                "town": town_of,
                "school": school_of,
                "station": nearest,
                "station_m": nearest_m,
            },
            CELLS_SCHEMA,
            out / f"{PREFIX}cells.parquet",
        ),
        "stations": _write_places(
            stations, ["station_name", "line_name", "operator"], out, "stations"
        ),
        "station_walk": _write_walk(station_walk, out / f"{PREFIX}station_walk.parquet"),
        "bus_stops": _write_places(bus_stops, ["name", "operator"], out, "bus_stops"),
        "bus_walk": _write_walk(bus_walk, out / f"{PREFIX}bus_walk.parquet"),
        "schools": _write(
            {k: [s[k] for s in schools] for k in ("school_code", "name", "muni_code", "city")},
            SCHOOLS_SCHEMA,
            out / f"{PREFIX}schools.parquet",
        ),
    }
    return Built(files=files, cells=int(codes.shape[0]), seconds=time.monotonic() - started)


class Log:
    def __call__(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)


CELLS_SCHEMA = pa.schema(
    [
        ("cell", pa.int64()),
        ("lat", pa.float32()),
        ("lon", pa.float32()),
        ("mesh", pa.int32()),
        ("town", pa.int32()),
        ("school", pa.int32()),
        ("station", pa.int32()),
        ("station_m", pa.float32()),
    ]
)
WALK_SCHEMA = pa.schema([("place", pa.int32()), ("cell", pa.int32()), ("distance", pa.float32())])
SCHOOLS_SCHEMA = pa.schema(
    [
        ("school_code", pa.string()),
        ("name", pa.string()),
        ("muni_code", pa.string()),
        ("city", pa.string()),
    ]
)


def _containing(
    points: npt.NDArray[np.object_], shapes: Sequence[BaseGeometry]
) -> npt.NDArray[np.int32]:
    """点ごとに、それを含む形の番号（なければ -1。重なっていれば番号の小さいほう）。"""
    result = np.full(points.shape[0], -1, dtype=np.int32)
    if not shapes:
        return result
    tree = shapely.STRtree(list(shapes))
    point_index, shape_index = tree.query(points, predicate="within")
    order = np.lexsort((shape_index, point_index))
    point_index, shape_index = point_index[order], shape_index[order]
    first = np.ones(point_index.shape[0], dtype=bool)
    first[1:] = point_index[1:] != point_index[:-1]
    result[point_index[first]] = shape_index[first]
    return result


def _school_districts(paths: Paths) -> tuple[list[dict[str, str]], list[BaseGeometry]]:
    """小学校区の形。利用条件で取り込めた学校（school_districts.parquet にある学校）だけ。"""
    table = paths.out_dir / "school_districts.parquet"
    if not table.is_file():
        return [], []
    allowed = {
        r["school_code"]: r for r in pq.read_table(table).to_pylist() if r["kind"] == "小学校"
    }
    schools: list[dict[str, str]] = []
    shapes: list[BaseGeometry] = []
    for pref in PREFECTURES:
        path = paths.ksj_school_district_zip("A27", pref)
        if not path.is_file():
            continue
        doc = json.loads(read_zip_member(path, ".geojson").decode("utf-8"))
        for feature in doc["features"]:
            code = feature["properties"].get("A27_003")
            if code not in allowed or not feature.get("geometry"):
                continue
            row = allowed[code]
            schools.append(
                {
                    "school_code": code,
                    "name": str(row["name"]),
                    "muni_code": str(row["muni_code"]),
                    "city": str(row["city"]),
                }
            )
            shapes.append(shape(feature["geometry"]))
    return schools, shapes


def _snap_rows(walker: Walker, rows: Sequence[dict[str, object]]) -> Snapped:
    lat = np.asarray([float(r["lat"]) for r in rows], dtype=np.float64)  # type: ignore[arg-type]
    lon = np.asarray([float(r["lon"]) for r in rows], dtype=np.float64)  # type: ignore[arg-type]
    return walker.snap(lat, lon)


def _write(columns: Mapping[str, object], schema: pa.Schema, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns, schema=schema), path)
    return path


def _write_ages(ages: Sequence[census_age.AgeRow], out: Path) -> Path:
    path = out / f"{PREFIX}age_500m.parquet"
    census_age.write(ages, path)
    return path


def _write_places(
    rows: Sequence[dict[str, object]], names: list[str], out: Path, kind: str
) -> Path:
    columns: dict[str, object] = {"name": [str(r[names[0]]) for r in rows]}
    fields = [("name", pa.string())]
    for extra in names[1:]:
        columns[extra] = [str(r[extra]) for r in rows]
        fields.append((extra, pa.string()))
    columns["lat"] = [float(r["lat"]) for r in rows]  # type: ignore[arg-type]
    columns["lon"] = [float(r["lon"]) for r in rows]  # type: ignore[arg-type]
    fields += [("lat", pa.float64()), ("lon", pa.float64())]
    return _write(columns, pa.schema(fields), out / f"{PREFIX}{kind}.parquet")


def _write_walk(table: WalkTable, path: Path) -> Path:
    return _write(
        {"place": table.place, "cell": table.cell, "distance": table.distance},
        WALK_SCHEMA,
        path,
    )


def main() -> int:
    paths = Paths()
    log = Log()
    if not inputs_ready(paths):
        log(
            "住まいの推定の生データ（raw/estat_age・raw/census_boundary・raw/osm）か、"
            "駅・バス停の表がないので、住まいの推定の表は作りません"
        )
        return 0
    try:
        built = build(paths, log)
    except DataPrepError as e:
        log(f"エラー: {e}")
        return 1
    for name, path in built.files.items():
        log(f"  {path.name}: {path.stat().st_size / 1e6:.1f} MB（{name}）")
    log(f"住まいの推定の表を作りました（100m マス {built.cells} 個、{built.seconds:.0f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
