"""住まいの推定の表（data-prep の scoring_*.parquet）を読む。

表は `make data` で data/processed/ に作る（コミットしない）。1つでも欠けていれば None を返し、
api は住まいの推定を出さずに今までどおり動く。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

AGE_CLASSES = 20
FILES = (
    "age_500m",
    "towns",
    "cells",
    "stations",
    "station_walk",
    "bus_stops",
    "bus_walk",
    "schools",
)

FloatArray = npt.NDArray[np.float32]
IntArray = npt.NDArray[np.int32]


@dataclass(frozen=True)
class Walk:
    """駅・バス停ごとの徒歩圏のマス。place ごとに cell[indptr[p]:indptr[p+1]]。"""

    indptr: npt.NDArray[np.int64]
    cell: IntArray
    distance: FloatArray

    def of(self, place: int) -> tuple[IntArray, FloatArray]:
        start, end = int(self.indptr[place]), int(self.indptr[place + 1])
        return self.cell[start:end], self.distance[start:end]


@dataclass(frozen=True)
class Places:
    name: list[str]
    group: list[str]  # 駅は路線名、バス停は事業者名
    lat: npt.NDArray[np.float64]
    lon: npt.NDArray[np.float64]


@dataclass(frozen=True)
class Towns:
    key_code: list[str]
    muni_code: list[str]
    city: list[str]
    name: list[str]
    lat: npt.NDArray[np.float64]
    lon: npt.NDArray[np.float64]


@dataclass(frozen=True)
class ScoringTables:
    # 500m メッシュごと
    age: FloatArray  # (メッシュ, 20) 5歳階級別人口
    total: FloatArray  # 人口（総数、年齢不詳を含む）
    # 100m マスごと
    cell: npt.NDArray[np.int64]
    lat: FloatArray
    lon: FloatArray
    mesh: IntArray
    town: IntArray
    school: IntArray
    station: IntArray
    station_m: FloatArray
    towns: Towns
    stations: Places
    station_walk: Walk
    bus_stops: Places
    bus_walk: Walk
    school_name: list[str]
    school_city: list[str]

    @property
    def size(self) -> int:
        return int(self.cell.shape[0])

    def index_of(self, cell_code: int) -> int | None:
        found = np.flatnonzero(self.cell == cell_code)
        return int(found[0]) if found.shape[0] else None

    def cell_of(self, lat: float, lon: float) -> int | None:
        """その点を含む 100m マスの番号（表にない＝人口のないマスなら None）。"""
        return self.index_of(cell_code(lat, lon))


def cell_code(lat: float, lon: float) -> int:
    """緯度経度を含む 100m マス（3次メッシュの 1/10 細分）のコード（10桁）。"""
    p = int(lat * 1.5)
    rem_lat = lat * 1.5 - p
    u = int(lon - 100)
    rem_lon = lon - 100 - u
    q = int(rem_lat * 8)
    v = int(rem_lon * 8)
    rem_lat = rem_lat * 8 - q
    rem_lon = rem_lon * 8 - v
    r = int(rem_lat * 10)
    w = int(rem_lon * 10)
    rem_lat = rem_lat * 10 - r
    rem_lon = rem_lon * 10 - w
    row = int(rem_lat * 10)
    col = int(rem_lon * 10)
    return int(f"{p:02d}{u:02d}{q}{v}{r}{w}{row}{col}")


def load(data_dir: Path) -> ScoringTables | None:
    paths = {name: data_dir / f"scoring_{name}.parquet" for name in FILES}
    missing = [p.name for p in paths.values() if not p.is_file()]
    if missing:
        logger.info(
            "住まいの推定の表がないので、住まいの推定は出しません（%d 個ない）", len(missing)
        )
        return None
    try:
        tables = _load(paths)
    except (OSError, ValueError, KeyError, pa.ArrowException) as e:
        logger.warning("住まいの推定の表を読めませんでした（%s）", type(e).__name__)
        return None
    pa.default_memory_pool().release_unused()
    return tables


def _load(paths: dict[str, Path]) -> ScoringTables:
    ages = pq.read_table(paths["age_500m"])
    age = np.column_stack([_floats(ages, f"age_{5 * i:02d}") for i in range(AGE_CLASSES)]).astype(
        np.float32
    )
    cells = pq.read_table(paths["cells"])
    schools = pq.read_table(paths["schools"])
    return ScoringTables(
        age=age,
        total=_floats(ages, "total"),
        cell=cells.column("cell").to_numpy().astype(np.int64),
        lat=_floats(cells, "lat"),
        lon=_floats(cells, "lon"),
        mesh=_ints(cells, "mesh"),
        town=_ints(cells, "town"),
        school=_ints(cells, "school"),
        station=_ints(cells, "station"),
        station_m=_floats(cells, "station_m"),
        towns=_towns(pq.read_table(paths["towns"])),
        stations=_places(pq.read_table(paths["stations"]), "line_name"),
        station_walk=_walk(pq.read_table(paths["station_walk"]), _rows(paths["stations"])),
        bus_stops=_places(pq.read_table(paths["bus_stops"]), "operator"),
        bus_walk=_walk(pq.read_table(paths["bus_walk"]), _rows(paths["bus_stops"])),
        school_name=[str(v) for v in schools.column("name").to_pylist()],
        school_city=[str(v) for v in schools.column("city").to_pylist()],
    )


def _rows(path: Path) -> int:
    return int(pq.read_metadata(path).num_rows)


def _floats(table: pa.Table, name: str) -> FloatArray:
    return np.asarray(table.column(name).to_numpy(), dtype=np.float32)


def _ints(table: pa.Table, name: str) -> IntArray:
    return np.asarray(table.column(name).to_numpy(), dtype=np.int32)


def _strings(table: pa.Table, name: str) -> list[str]:
    return [str(v) for v in table.column(name).to_pylist()]


def _towns(table: pa.Table) -> Towns:
    return Towns(
        key_code=_strings(table, "key_code"),
        muni_code=_strings(table, "muni_code"),
        city=_strings(table, "city"),
        name=_strings(table, "name"),
        lat=table.column("lat").to_numpy().astype(np.float64),
        lon=table.column("lon").to_numpy().astype(np.float64),
    )


def _places(table: pa.Table, group: str) -> Places:
    return Places(
        name=_strings(table, "name"),
        group=_strings(table, group),
        lat=table.column("lat").to_numpy().astype(np.float64),
        lon=table.column("lon").to_numpy().astype(np.float64),
    )


def _walk(table: pa.Table, places: int) -> Walk:
    place = _ints(table, "place")
    order = np.argsort(place, kind="stable")
    counts = np.bincount(place, minlength=places)
    indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return Walk(
        indptr=indptr,
        cell=_ints(table, "cell")[order],
        distance=_floats(table, "distance")[order],
    )
