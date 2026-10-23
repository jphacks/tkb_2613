"""500m メッシュ（4次メッシュ）ごとの世帯数と人口。

入力は e-Stat の令和2年国勢調査 地域メッシュ統計「人口及び世帯」（第1次地域区画ごとの zip）。
中身は CP932 の CSV で、1 行目が列のコード、2 行目が列の名前、3 行目からデータ。
秘匿処理（HTKSYORI）のある行でも「人口（総数）」と「世帯総数」は秘匿されず、
そのメッシュ自身の値が入っている（合算されるのは内訳の列だけ）ので、そのまま使う。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import decode, parse_csv, read_zip_member, write_parquet
from tkb_data_prep.mesh import center

MESH_500M = re.compile(r"\d{9}")
KEY_COLUMN = "KEY_CODE"
POPULATION_COLUMN = "人口（総数）"
HOUSEHOLDS_COLUMN = "世帯総数"
# 列の名前の前につく全角スペースなど
NAME_PADDING = " 　"

SCHEMA = pa.schema(
    [
        ("mesh_500m", pa.string()),
        ("mesh_1km", pa.string()),
        ("households", pa.int64()),
        ("population", pa.int64()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
    ]
)


@dataclass(frozen=True)
class Household:
    mesh_500m: str
    households: int
    population: int

    @property
    def mesh_1km(self) -> str:
        return self.mesh_500m[:8]


@dataclass(frozen=True)
class Loaded:
    rows: list[Household]
    # 読み込んだ zip に含まれていた第1次地域区画（4 桁）
    first_meshes: frozenset[str]


def parse(text: str, source: str, allowed_1km: frozenset[str]) -> list[Household]:
    """allowed_1km に含まれる 1km メッシュの中の 500m メッシュだけを返す。"""
    rows = parse_csv(text)
    if len(rows) < 2 or rows[0][0].strip() != KEY_COLUMN:
        raise DataPrepError(f"{source}: 1 行目が {KEY_COLUMN} から始まっていません")
    names = [name.strip(NAME_PADDING) for name in rows[1]]
    population_at = _column(names, POPULATION_COLUMN, source)
    households_at = _column(names, HOUSEHOLDS_COLUMN, source)

    result: list[Household] = []
    for line_no, row in enumerate(rows[2:], start=3):
        key = row[0].strip()
        if not MESH_500M.fullmatch(key):
            raise DataPrepError(f"{source}:{line_no}: メッシュコードが 9 桁ではありません: {key}")
        if key[:8] not in allowed_1km:
            continue
        result.append(
            Household(
                mesh_500m=key,
                households=_count(row[households_at], source, line_no),
                population=_count(row[population_at], source, line_no),
            )
        )
    return result


def _column(names: list[str], wanted: str, source: str) -> int:
    if wanted not in names:
        raise DataPrepError(f"{source}: 2 行目に「{wanted}」の列がありません")
    return names.index(wanted)


def _count(cell: str, source: str, line_no: int) -> int:
    value = cell.strip()
    if not value.isdigit():
        raise DataPrepError(f"{source}:{line_no}: 数値ではない値があります: {value!r}")
    return int(value)


def load(paths: Paths, allowed_1km: frozenset[str]) -> Loaded:
    zips = sorted(paths.estat_dir.glob("*.zip"))
    if not zips:
        raise DataPrepError(
            f"{paths.estat_dir} に e-Stat の zip がありません。"
            "data-prep/README.md の手順で置いてください"
        )
    rows: list[Household] = []
    first_meshes: set[str] = set()
    for path in zips:
        parsed = parse(decode(read_zip_member(path, ".txt"), str(path)), str(path), allowed_1km)
        rows.extend(parsed)
        first_meshes.update(_first_meshes_in(path))
    return Loaded(rows=rows, first_meshes=frozenset(first_meshes))


def _first_meshes_in(path: Path) -> set[str]:
    # ファイル名の末尾が第1次地域区画（例：tblT001101H5339.zip）
    match = re.search(r"(\d{4})$", path.stem)
    return {match.group(1)} if match else set()


def write(rows: list[Household], path: Path) -> None:
    points = [center(r.mesh_500m) for r in rows]
    columns: dict[str, Sequence[object]] = {
        "mesh_500m": [r.mesh_500m for r in rows],
        "mesh_1km": [r.mesh_1km for r in rows],
        "households": [r.households for r in rows],
        "population": [r.population for r in rows],
        "lat": [lat for lat, _ in points],
        "lon": [lon for _, lon in points],
    }
    write_parquet(columns, SCHEMA, path)
