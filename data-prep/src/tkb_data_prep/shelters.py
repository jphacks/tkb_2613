"""指定緊急避難場所・指定避難所の一覧（施設名、区市町村、緯度経度、1km メッシュ）。

入力は国土地理院「指定緊急避難場所・指定避難所データ」の都道府県別 CSV
（data-prep/raw/gsi/{11000..14000}_{1,2}.csv。`_2` が指定緊急避難場所、`_1` が指定避難所）。
1行目が見出しで、見出しの名前で列を探す。

区市町村の列はない。共通ID（14桁）の2〜6桁目は、施設を指定した市区町村のコード。
ただし政令市は市のコード（横浜市 14100 など）で、郵便番号の表は区のコードなので、
区市町村は住所から郵便番号の表の市区町村名で引き、共通IDの市区町村と合う行だけを残す。
隣の県にある施設（「※埼玉県熊谷市指定」の群馬県太田市の施設など）は、住所が合わないので落とす。

住所の番地と緯度経度は推定の画面に出さない（区市町村までにする）。
緯度経度は 1km メッシュのためにだけ持つ。
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_csv, write_parquet
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.postal import Postal

KIND_BY_SUFFIX = {"_2": "指定緊急避難場所", "_1": "指定避難所"}
COLUMNS = {"id": "共通ID", "name": "施設・場所名", "address": "住所", "lat": "緯度", "lon": "経度"}
# 政令市の区のコードは、市のコードの次から始まる（横浜市 14100 → 14101〜14118）
MAX_WARDS = 29

SCHEMA = pa.schema(
    [
        ("name", pa.string()),
        ("kind", pa.string()),
        ("muni_code", pa.string()),
        ("city", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("mesh_1km", pa.string()),
    ]
)


@dataclass(frozen=True)
class Shelter:
    name: str
    kind: str
    muni_code: str
    city: str
    lat: float
    lon: float

    @property
    def mesh_1km(self) -> str:
        return code_1km(self.lat, self.lon)


def parse(files: Iterable[tuple[str, list[list[str]]]], postals: list[Postal]) -> list[Shelter]:
    """files は (ファイル名, CSV の行) の組。同じ区市町村の同じ名前の施設は1行にまとめる。"""
    cities = _city_names(postals)
    merged: dict[tuple[str, str], Shelter] = {}
    for source, rows in files:
        if not rows:
            continue
        header = _header(rows[0], source)
        kind = _kind(source)
        for row in rows[1:]:
            shelter = _shelter(row, header, kind, cities)
            if shelter is None:
                continue
            key = (shelter.name, shelter.muni_code)
            known = merged.get(key)
            if known is None:
                merged[key] = shelter
            elif shelter.kind not in known.kind.split("・"):
                merged[key] = replace(known, kind=f"{known.kind}・{shelter.kind}")
    return list(merged.values())


@dataclass(frozen=True)
class _CityName:
    pref: str
    spelling: str  # 住所に出てくる書き方
    city: str  # 郵便番号の表の市区町村名
    muni_code: str


def _city_names(postals: list[Postal]) -> list[_CityName]:
    """郡や島の名前を書かない住所もあるので、「比企郡ときがわ町」は「ときがわ町」、
    「三宅島三宅村」は「三宅村」でも引けるようにする。長い書き方から順に試す。"""
    names = {
        _CityName(_normalize(p.pref), _normalize(spelling), p.city, p.muni_code)
        for p in postals
        if p.muni_code[:2] in PREFECTURES
        for spelling in (p.city, re.sub(r"^.+?(?:郡|島)(?=.+[町村]$)", "", p.city))
    }
    return sorted(names, key=lambda n: (-len(n.spelling), n.muni_code))


def _header(row: list[str], source: str) -> dict[str, int]:
    names = [cell.strip() for cell in row]
    missing = [label for label in COLUMNS.values() if label not in names]
    if missing:
        raise DataPrepError(f"{source}: 見出しに {'・'.join(missing)} がありません")
    return {key: names.index(label) for key, label in COLUMNS.items()}


def _kind(source: str) -> str:
    stem = Path(source).stem
    for suffix, kind in KIND_BY_SUFFIX.items():
        if stem.endswith(suffix):
            return kind
    raise DataPrepError(f"{source}: ファイル名から種類（_1 か _2）がわかりません")


def _shelter(
    row: list[str],
    header: dict[str, int],
    kind: str,
    cities: list[_CityName],
) -> Shelter | None:
    if len(row) <= max(header.values()):
        return None

    def cell(key: str) -> str:
        return row[header[key]].strip()

    common_id, name, address = cell("id"), cell("name"), _normalize(cell("address"))
    try:
        lat, lon = float(cell("lat")), float(cell("lon"))
    except ValueError:
        return None
    if not name or len(common_id) < 6:
        return None
    designated = common_id[1:6]
    found = _city_of(address, cities)
    if found is None or not _same_muni(designated, found.muni_code):
        return None
    return Shelter(name, kind, found.muni_code, found.city, lat, lon)


def _city_of(address: str, cities: list[_CityName]) -> _CityName | None:
    """住所の先頭の市区町村。1都3県の外なら None。"""
    for name in cities:
        if address.removeprefix(name.pref).startswith(name.spelling):
            return name
    return None


def _normalize(text: str) -> str:
    """互換漢字（戸塚区の「塚」が U+FA10 で書かれているなど）、「ヶ」と「ケ」、空白をそろえる。"""
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", text)).replace("ヶ", "ケ")


def _same_muni(designated: str, found: str) -> bool:
    if designated == found:
        return True
    # 政令市：共通IDは市のコード、住所から引いたのは区のコード
    return designated.endswith("0") and 0 < int(found) - int(designated) <= MAX_WARDS


def load(paths: Paths, postals: list[Postal]) -> list[Shelter]:
    """CSV がなければ空（fetch.sh で取得する。表がなくても推定は動く）。"""
    files = sorted(paths.gsi_dir.glob("*.csv")) if paths.gsi_dir.is_dir() else []
    return parse(((str(f), read_csv(f)) for f in files), postals)


def write(rows: list[Shelter], path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "name": [r.name for r in rows],
        "kind": [r.kind for r in rows],
        "muni_code": [r.muni_code for r in rows],
        "city": [r.city for r in rows],
        "lat": [r.lat for r in rows],
        "lon": [r.lon for r in rows],
        "mesh_1km": [r.mesh_1km for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
