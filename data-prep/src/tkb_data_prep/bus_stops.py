"""バス停留所の一覧（停留所名、事業者名、区市町村、緯度経度、1km メッシュ）。

入力は国土数値情報「バス停留所（P11）」の令和4年度版（P11-22）。都道府県ごとの
P11-22_{11..14}_SHP.zip に入っている GeoJSON（UTF-8、JGD2011 経緯度）を読む。
平成22年度版（非商用）は使わない。

属性は P11_001（バス停名）と P11_002（事業者名。コミュニティバスは自治体名）だけ使う。
区市町村の属性はないので、行政区域（N03）の境界でバス停の点が入る区市町村を引く
（boundaries）。境界のデータがないときや、点がどの区市町村にも入らないとき（海沿いなど）は、
バス停がある 1km メッシュにかかる区市町村をすべて候補として入れる（都区部では2つ以上になる
ことが多い）。推定では、手がかりの事業者名や区市町村名と合わせて1つに絞れたときだけ使う。
1都3県の 1km メッシュにないバス停は落とす。同じメッシュの同じ名前・同じ事業者は1行にまとめる。
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from tkb_data_prep.boundaries import Locator
from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_zip_member, write_parquet
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal

SCHEMA = pa.schema(
    [
        ("name", pa.string()),
        ("operator", pa.string()),
        ("muni_codes", pa.list_(pa.string())),
        ("cities", pa.list_(pa.string())),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("mesh_1km", pa.string()),
    ]
)


@dataclass(frozen=True)
class BusStop:
    name: str
    operator: str
    muni_codes: tuple[str, ...]  # 1km メッシュにかかる区市町村（候補）
    cities: tuple[str, ...]
    lat: float
    lon: float

    @property
    def mesh_1km(self) -> str:
        return code_1km(self.lat, self.lon)


def parse(
    geojson: dict[str, Any],
    munis: list[MuniMesh],
    postals: list[Postal],
    locator: Locator | None = None,
) -> list[BusStop]:
    munis_by_mesh: dict[str, set[str]] = {}
    for m in munis:
        munis_by_mesh.setdefault(m.mesh_1km, set()).add(m.muni_code)
    # 区市町村名は、避難所などほかの表とそろえて郵便番号の表の名前（郡名つき）を使う
    names = {m.muni_code: m.muni_name for m in munis} | {p.muni_code: p.city for p in postals}
    stops: dict[tuple[str, str, str], BusStop] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        lat, lon = _point(feature.get("geometry") or {}, props)
        mesh = code_1km(lat, lon)
        if mesh not in munis_by_mesh:
            continue
        name, operator = str(props.get("P11_001") or "").strip(), str(props.get("P11_002") or "")
        if not name:
            continue
        located = locator.locate(lat, lon) if locator is not None else None
        codes = (located,) if located is not None else tuple(sorted(munis_by_mesh[mesh]))
        stop = BusStop(
            name, operator.strip(), codes, tuple(names.get(c, "") for c in codes), lat, lon
        )
        stops.setdefault((name, stop.operator, mesh), stop)
    return list(stops.values())


def _point(geometry: dict[str, Any], props: dict[str, Any]) -> tuple[float, float]:
    coords = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2:
        raise DataPrepError(f"バス停 {props.get('P11_001')}: 想定外の形状 {geometry.get('type')}")
    return float(coords[1]), float(coords[0])


def load(
    paths: Paths,
    munis: list[MuniMesh],
    postals: list[Postal],
    locator: Locator | None = None,
) -> list[BusStop]:
    """zip がなければ空（fetch.sh で取得する。表がなくても推定は動く）。"""
    rows: list[BusStop] = []
    for pref in PREFECTURES:
        path = paths.ksj_bus_stop_zip(pref)
        if not path.is_file():
            continue
        data = read_zip_member(path, ".geojson")
        rows.extend(parse(json.loads(data.decode("utf-8")), munis, postals, locator))
    return rows


def write(rows: list[BusStop], path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "name": [r.name for r in rows],
        "operator": [r.operator for r in rows],
        "muni_codes": [list(r.muni_codes) for r in rows],
        "cities": [list(r.cities) for r in rows],
        "lat": [r.lat for r in rows],
        "lon": [r.lon for r in rows],
        "mesh_1km": [r.mesh_1km for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
