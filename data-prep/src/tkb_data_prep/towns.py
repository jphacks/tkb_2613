"""町丁目（国勢調査の小地域、町丁・字等）の区域。

入力は e-Stat の令和2年国勢調査 小地域境界データ（世界測地系緯度経度・Shapefile、JGD2011）。
都県ごとの zip（raw/census_boundary/A002005212020DDSWC{11..14}-JGD2011.zip）に
r2ka{11..14}.shp・.dbf・.shx が入っている。文字コードは CP932。

1つの町丁目が複数の形（飛び地）に分かれていることがあるので、KEY_CODE ごとにまとめる。
HCODE が 8101（町丁・字等）の形だけを使い、8154（水面調査区）は使わない。
"""

import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import shapefile
from shapely import union_all
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError

FILE_NAME = re.compile(r"A002005212020DDSWC(\d{2})-JGD2011\.zip")
TOWN_HCODE = 8101

SCHEMA = pa.schema(
    [
        ("key_code", pa.string()),
        ("muni_code", pa.string()),
        ("city", pa.string()),
        ("name", pa.string()),
        ("population", pa.int64()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
    ]
)


@dataclass(frozen=True)
class Town:
    key_code: str
    muni_code: str
    city: str
    name: str
    population: int
    geometry: BaseGeometry

    @property
    def point(self) -> tuple[float, float]:
        """区域の中にある代表の点（緯度, 経度）。"""
        p = self.geometry.representative_point()
        return float(p.y), float(p.x)


def zip_paths(directory: Path) -> list[Path]:
    found = {m.group(1): p for p in directory.glob("*.zip") if (m := FILE_NAME.fullmatch(p.name))}
    missing = [code for code in PREFECTURES if code not in found]
    if missing:
        raise DataPrepError(
            f"{directory} に小地域境界の zip が足りません（{', '.join(missing)}）。"
            "data-prep/README.md の手順で置いてください"
        )
    return [found[code] for code in PREFECTURES]


def read_zip(path: Path) -> list[Town]:
    with zipfile.ZipFile(path) as archive:
        members = {Path(n).suffix.lower(): n for n in archive.namelist()}
        if not {".shp", ".dbf", ".shx"} <= members.keys():
            raise DataPrepError(f"{path}: .shp・.dbf・.shx がそろっていません")
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(members[".shp"])),
            dbf=io.BytesIO(archive.read(members[".dbf"])),
            shx=io.BytesIO(archive.read(members[".shx"])),
            encoding="cp932",
        )
        return merge(
            (record.as_dict(), shape(geometry.__geo_interface__))
            for record, geometry in zip(reader.iterRecords(), reader.iterShapes(), strict=True)
        )


def merge(pieces: Any) -> list[Town]:
    """KEY_CODE ごとに形をまとめる。名前のない区域と水面調査区は使わない。"""
    geometries: dict[str, list[BaseGeometry]] = defaultdict(list)
    attributes: dict[str, dict[str, Any]] = {}
    for record, geometry in pieces:
        if int(record["HCODE"]) != TOWN_HCODE or not str(record["S_NAME"]).strip():
            continue
        key = str(record["KEY_CODE"])
        geometries[key].append(geometry)
        attributes.setdefault(key, record)
    towns: list[Town] = []
    for key, parts in geometries.items():
        record = attributes[key]
        towns.append(
            Town(
                key_code=key,
                muni_code=f"{record['PREF']}{record['CITY']}",
                city=str(record["CITY_NAME"]),
                name=str(record["S_NAME"]).strip(),
                population=int(record["JINKO"] or 0),
                geometry=parts[0] if len(parts) == 1 else union_all(parts),
            )
        )
    return towns


def load(paths: Paths) -> list[Town]:
    towns: list[Town] = []
    for path in zip_paths(paths.census_boundary_dir):
        towns.extend(read_zip(path))
    return towns


def columns(towns: Sequence[Town]) -> dict[str, Sequence[object]]:
    points = [t.point for t in towns]
    return {
        "key_code": [t.key_code for t in towns],
        "muni_code": [t.muni_code for t in towns],
        "city": [t.city for t in towns],
        "name": [t.name for t in towns],
        "population": [t.population for t in towns],
        "lat": [lat for lat, _ in points],
        "lon": [lon for _, lon in points],
    }
