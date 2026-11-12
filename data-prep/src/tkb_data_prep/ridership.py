"""駅ごとの1日の乗降客数（最新年度）。

入力は国土数値情報「駅別乗降客数（S12）」2025年度整備版（S12-25_GML.zip の UTF-8 の GeoJSON）。
全国1ファイルで都道府県の属性がないので、駅コード（S12_001c）を駅の表（stations、鉄道データ N02 の
N02_005c）とつないで 1都3県の駅だけにする。

年度ごとに4つの属性（重複コード、データ有無コード、備考、乗降客数）が並ぶ。2011年度が
S12_006〜009 で、1年ごとに 4 つずつ進む。いちばん新しい年度を使い、重複コードが 1（重複なし）で
データ有無コードが 1（あり）の行だけを数える（重複の行は、同じ駅の別の行に含まれている）。

乗降客数は推定の結果を変えない。常用駅の候補が複数残ったときに、説明へ参考として添えるだけ。
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from tkb_data_prep.config import Paths
from tkb_data_prep.io import read_zip_member, write_parquet

GEOJSON_SUFFIX = "UTF-8/S12-25_NumberOfPassengers.geojson"
FIRST_YEAR = 2011
FIRST_ATTRIBUTE = 6
NO_DUPLICATE = 1
HAS_DATA = 1

SCHEMA = pa.schema(
    [
        ("station_code", pa.string()),
        ("station_name", pa.string()),
        ("operator", pa.string()),
        ("passengers", pa.int64()),
        ("year", pa.int64()),
    ]
)


@dataclass(frozen=True)
class Ridership:
    station_code: str
    station_name: str
    operator: str
    passengers: int  # 1日の乗降客数（人/日）


def _attribute(year: int, offset: int) -> str:
    return f"S12_{FIRST_ATTRIBUTE + (year - FIRST_YEAR) * 4 + offset:03d}"


def latest_year(features: Sequence[dict[str, Any]]) -> int:
    keys = {k for f in features for k in (f.get("properties") or {})}
    years = [y for y in range(FIRST_YEAR, FIRST_YEAR + 50) if _attribute(y, 3) in keys]
    return max(years, default=0)


def parse(geojson: dict[str, Any], station_codes: set[str]) -> tuple[int, list[Ridership]]:
    """(年度, 駅コードごとの乗降客数)。"""
    features = geojson.get("features", [])
    year = latest_year(features)
    if not year:
        return 0, []
    totals: dict[str, Ridership] = {}
    for feature in features:
        props = feature.get("properties") or {}
        code = str(props.get("S12_001c") or "")
        if (
            code not in station_codes
            or props.get(_attribute(year, 0)) != NO_DUPLICATE
            or props.get(_attribute(year, 1)) != HAS_DATA
        ):
            continue
        passengers = int(props.get(_attribute(year, 3)) or 0)
        known = totals.get(code)
        totals[code] = Ridership(
            code,
            str(props.get("S12_001") or ""),
            str(props.get("S12_002") or ""),
            passengers + (known.passengers if known else 0),
        )
    return year, list(totals.values())


def load(paths: Paths, station_codes: set[str]) -> tuple[int, list[Ridership]]:
    """zip がなければ (0, [])（fetch.sh で取得する。表がなくても推定は動く）。"""
    if not paths.ridership_zip.is_file():
        return 0, []
    data = read_zip_member(paths.ridership_zip, GEOJSON_SUFFIX)
    return parse(json.loads(data.decode("utf-8")), station_codes)


def write(rows: list[Ridership], year: int, path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "station_code": [r.station_code for r in rows],
        "station_name": [r.station_name for r in rows],
        "operator": [r.operator for r in rows],
        "passengers": [r.passengers for r in rows],
        "year": [year for _ in rows],
    }
    write_parquet(columns, SCHEMA, path)
