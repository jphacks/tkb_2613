"""駅の一覧（中心点の緯度経度と 1km メッシュ）。

入力は国土数値情報「鉄道データ（N02）」の駅（N02-24_Station.geojson、UTF-8、JGD2011 経緯度）。
駅は路線ごとのホームの線データで入っている。同じ駅コード・同じ路線が複数の線に
分かれていることがあるので、まとめてから線の長さで重み付けした中心点を求める。
"""

import itertools
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_zip_member, write_parquet
from tkb_data_prep.mesh import code_1km

GEOJSON_SUFFIX = "UTF-8/N02-24_Station.geojson"

SCHEMA = pa.schema(
    [
        ("station_name", pa.string()),
        ("line_name", pa.string()),
        ("operator", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("mesh_1km", pa.string()),
    ]
)

Point = tuple[float, float]  # （経度, 緯度）。GeoJSON の並び


@dataclass(frozen=True)
class Station:
    station_name: str
    line_name: str
    operator: str
    lat: float
    lon: float

    @property
    def mesh_1km(self) -> str:
        return code_1km(self.lat, self.lon)


@dataclass(frozen=True)
class _Key:
    station_code: str
    station_name: str
    line_name: str
    operator: str


def parse(geojson: dict[str, Any], allowed_1km: frozenset[str]) -> list[Station]:
    """中心点の 1km メッシュが allowed_1km に含まれる駅だけを返す。"""
    lines_by_station: dict[_Key, list[list[Point]]] = {}
    for feature in geojson.get("features", []):
        key = _key(feature.get("properties") or {})
        lines_by_station.setdefault(key, []).extend(_lines(feature.get("geometry") or {}, key))

    stations = [
        Station(key.station_name, key.line_name, key.operator, *_center(lines))
        for key, lines in lines_by_station.items()
    ]
    return [s for s in stations if s.mesh_1km in allowed_1km]


def _key(props: dict[str, Any]) -> _Key:
    try:
        return _Key(
            station_code=str(props["N02_005c"]),
            station_name=str(props["N02_005"]),
            line_name=str(props["N02_003"]),
            operator=str(props["N02_004"]),
        )
    except KeyError as e:
        raise DataPrepError(f"駅の属性 {e} がありません: {props}") from e


def _lines(geometry: dict[str, Any], key: _Key) -> list[list[Point]]:
    kind = geometry.get("type")
    coords: Any = geometry.get("coordinates") or []
    if kind == "LineString" and coords:
        return [_points(coords)]
    if kind == "MultiLineString" and coords:
        return [_points(line) for line in coords]
    raise DataPrepError(f"{key.station_name}（{key.line_name}）: 想定外の形状 {kind}")


def _points(coords: Sequence[Sequence[float]]) -> list[Point]:
    return [(float(c[0]), float(c[1])) for c in coords]


def _center(lines: list[list[Point]]) -> tuple[float, float]:
    """線分の中点を長さで重み付けした平均の（緯度, 経度）。長さが 0 なら頂点の平均。"""
    points = [p for line in lines for p in line]
    # 経度 1 度の長さは緯度によって縮むので、重みの計算だけ補正する
    lat_mean = sum(lat for _, lat in points) / len(points)
    shrink = math.cos(math.radians(lat_mean))
    total = lon_sum = lat_sum = 0.0
    for line in lines:
        for (lon1, lat1), (lon2, lat2) in itertools.pairwise(line):
            length = math.hypot((lon2 - lon1) * shrink, lat2 - lat1)
            total += length
            lon_sum += length * (lon1 + lon2) / 2
            lat_sum += length * (lat1 + lat2) / 2
    if total == 0:
        return lat_mean, sum(lon for lon, _ in points) / len(points)
    return lat_sum / total, lon_sum / total


def load(paths: Paths, allowed_1km: frozenset[str]) -> list[Station]:
    data = read_zip_member(paths.stations_zip, GEOJSON_SUFFIX)
    return parse(json.loads(data.decode("utf-8")), allowed_1km)


def write(rows: Iterable[Station], path: Path) -> None:
    stations = list(rows)
    columns: dict[str, Sequence[object]] = {
        "station_name": [s.station_name for s in stations],
        "line_name": [s.line_name for s in stations],
        "operator": [s.operator for s in stations],
        "lat": [s.lat for s in stations],
        "lon": [s.lon for s in stations],
        "mesh_1km": [s.mesh_1km for s in stations],
    }
    write_parquet(columns, SCHEMA, path)
