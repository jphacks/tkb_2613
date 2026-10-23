"""市区町村と 1km メッシュ（3次メッシュ）の対応表。

入力は総務省統計局「市区町村別メッシュ・コード一覧」の CSV（都道府県ごと）。
列は 都道府県市区町村コード, 市区町村名, 基準メッシュ・コード。
1 つのメッシュが複数の市区町村にまたがるときは、それぞれの市区町村に 1 行ずつある。
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_csv, write_parquet

MUNI_CODE = re.compile(r"\d{5}")
MESH_1KM = re.compile(r"\d{8}")

SCHEMA = pa.schema(
    [
        ("muni_code", pa.string()),
        ("muni_name", pa.string()),
        ("pref_code", pa.string()),
        ("mesh_1km", pa.string()),
    ]
)


@dataclass(frozen=True)
class MuniMesh:
    muni_code: str
    muni_name: str
    mesh_1km: str

    @property
    def pref_code(self) -> str:
        return self.muni_code[:2]


def parse(rows: Iterable[list[str]], source: str) -> list[MuniMesh]:
    """見出し行を飛ばし、1都3県の行だけを重複なしで返す。"""
    seen: dict[MuniMesh, None] = {}
    for line_no, row in enumerate(rows, start=1):
        if line_no == 1 and not MUNI_CODE.fullmatch(row[0].strip()):
            continue
        if len(row) < 3:
            raise DataPrepError(f"{source}:{line_no}: 列が足りません: {row}")
        code, name, mesh = (cell.strip() for cell in row[:3])
        if not MUNI_CODE.fullmatch(code) or not MESH_1KM.fullmatch(mesh):
            raise DataPrepError(f"{source}:{line_no}: コードの形式が想定外です: {row}")
        if code[:2] in PREFECTURES:
            seen[MuniMesh(code, name, mesh)] = None
    return list(seen)


def load(paths: Paths) -> list[MuniMesh]:
    rows: list[MuniMesh] = []
    for pref_code in PREFECTURES:
        path = paths.stat_mesh_csv(pref_code)
        rows.extend(parse(read_csv(path), str(path)))
    return rows


def write(rows: list[MuniMesh], path: Path) -> None:
    columns = {
        "muni_code": [r.muni_code for r in rows],
        "muni_name": [r.muni_name for r in rows],
        "pref_code": [r.pref_code for r in rows],
        "mesh_1km": [r.mesh_1km for r in rows],
    }
    write_parquet(columns, SCHEMA, path)


def meshes(rows: Iterable[MuniMesh]) -> frozenset[str]:
    return frozenset(r.mesh_1km for r in rows)
