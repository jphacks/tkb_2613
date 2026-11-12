"""小学校区・中学校区の一覧（学校名、区市町村、学区にかかる 1km メッシュ、自治体ごとの利用条件）。

入力は国土数値情報「小学校区（A27）」「中学校区（A32）」の令和3年度版（A27-21・A32-21）。
都道府県ごとの zip に入っている GeoJSON（JGD2011 経緯度）を読む。属性は
A27_001（行政区域コード）, A27_003（学校コード）, A27_004（学校名）。A32 も同じ。

利用条件は自治体ごとに違い、国土数値情報の「R3_Terms_of_use_municipality_data.xlsx」に
書かれている。表の列（terms、note）に残し、次の自治体の行は取り込まない。
- 公開条件が「01.公開」でない
- 利用条件が「再配布・再利用不可」（1都3県では所沢市・東松山市）
- 利用条件の表に行がない
「条件公開」（白岡市・川島町）は、条件の原文（地図データは参考情報とする）を note に残して取り込む。
「商用利用不可」も取り込み、terms に残す。

ページの注記どおり、境界には推定による線や重なりがあり、公式な資料としては扱えない。
xlsx は標準ライブラリ（zipfile と XML）で読む。
"""

import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pyarrow as pa
from shapely.geometry import box, shape

from tkb_data_prep.boundaries import Locator
from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.io import read_zip_member, require_file, write_parquet
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.postal import Postal

KINDS = {"A27": "小学校", "A32": "中学校"}
# 政令市の区のコードは、市のコードの次から始まる（横浜市 14100 → 14101〜14118）
MAX_WARDS = 29
PUBLIC = "01.公開"
NOT_REUSABLE = "再配布・再利用不可"
# 1km メッシュ（3次メッシュ）の大きさ：緯度 30 秒、経度 45 秒
MESH_LAT = 1 / 120
MESH_LON = 1 / 80
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("school_code", pa.string()),
        ("name", pa.string()),
        ("muni_code", pa.string()),
        ("city", pa.string()),
        ("meshes", pa.list_(pa.string())),
        ("terms", pa.string()),
        ("note", pa.string()),
    ]
)


@dataclass(frozen=True)
class Terms:
    elementary_public: str
    elementary: str
    elementary_note: str
    junior_public: str
    junior: str
    junior_note: str

    def of(self, kind: str) -> tuple[str, str, str]:
        """(公開条件, 利用条件, 特記条件の原文)。"""
        if kind == "小学校":
            return self.elementary_public, self.elementary, self.elementary_note
        return self.junior_public, self.junior, self.junior_note


@dataclass(frozen=True)
class District:
    kind: str
    school_code: str
    name: str
    muni_code: str
    city: str
    meshes: tuple[str, ...]
    terms: str
    note: str


def parse_terms(xlsx: bytes) -> dict[str, Terms]:
    """行政区域コード → 利用条件。1行目は見出し。読み仮名（rPh）は落とす。"""
    rows = _sheet_rows(xlsx)
    terms: dict[str, Terms] = {}
    for row in rows[1:]:
        cells = [*row, *[""] * (11 - len(row))]
        code = cells[1].strip()
        if not re.fullmatch(r"\d{5}", code):
            continue
        note_e = cells[6].strip() if cells[5].startswith("01") else ""
        note_j = cells[10].strip() if cells[9].startswith("01") else ""
        terms[code] = Terms(
            cells[3].strip(), cells[4].strip(), note_e, cells[7].strip(), cells[8].strip(), note_j
        )
    return terms


def _sheet_rows(xlsx: bytes) -> list[list[str]]:
    with zipfile.ZipFile(BytesIO(xlsx)) as archive:
        shared = [
            "".join(t.text or "" for t in si.iterfind("m:t", NS))
            + "".join(t.text or "" for r in si.iterfind("m:r", NS) for t in r.iterfind("m:t", NS))
            for si in _xml(archive.read("xl/sharedStrings.xml")).iterfind("m:si", NS)
        ]
        sheet = _xml(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iterfind(".//m:sheetData/m:row", NS):
        values: dict[int, str] = {}
        for cell in row.iterfind("m:c", NS):
            value = cell.findtext("m:v", default="", namespaces=NS)
            if cell.get("t") == "s" and value:
                value = shared[int(value)]
            values[_column(cell.get("r") or "")] = value
        rows.append([values.get(i, "") for i in range(max(values, default=-1) + 1)])
    return rows


def _xml(data: bytes) -> ElementTree.Element:
    """名前空間がない xlsx（テストの見本）も読めるように、名前空間をそろえる。"""
    text = data.decode("utf-8")
    if "spreadsheetml" not in text:
        text = re.sub(r"<(sst|worksheet)>", rf'<\1 xmlns="{NS["m"]}">', text, count=1)
    return ElementTree.fromstring(text)  # noqa: S314  国土数値情報の xlsx（取得元は固定）


def _column(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    index = 0
    for ch in letters.group(0) if letters else "A":
        index = index * 26 + ord(ch) - ord("A") + 1
    return index - 1


def parse(
    geojson: dict[str, Any],
    kind: str,
    terms: dict[str, Terms],
    postals: list[Postal],
    locator: Locator | None = None,
) -> list[District]:
    """政令市の行政区域コードは市のコード（横浜市 14100 など）なので、区は境界（N03）で
    学区の代表点が入る区から引く。区市町村名が引けない学区は取り込まない。"""
    cities = {p.muni_code: p.city for p in postals}
    prefix = next(p for p, k in KINDS.items() if k == kind)
    rows = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        muni = str(props.get(f"{prefix}_001") or "")
        found = terms.get(muni)
        if found is None or muni[:2] not in PREFECTURES:
            continue
        public, usage, note = found.of(kind)
        if public != PUBLIC or usage == NOT_REUSABLE:
            continue
        geometry = feature.get("geometry") or {}
        code = muni if muni in cities else _ward(geometry, muni, locator)
        name = str(props.get(f"{prefix}_004") or "").strip()
        if code is None or code not in cities or not name:
            continue
        rows.append(
            District(
                kind,
                str(props.get(f"{prefix}_003") or ""),
                name,
                code,
                cities[code],
                _meshes(geometry),
                usage,
                note,
            )
        )
    return rows


def _ward(geometry: dict[str, Any], city_code: str, locator: Locator | None) -> str | None:
    """政令市の学区の区。代表点が入る区のコードが、その市の区の範囲にあるときだけ。"""
    if locator is None or not geometry:
        return None
    point = shape(geometry).representative_point()
    ward = locator.locate(point.y, point.x)
    if ward is None or not 0 < int(ward) - int(city_code) <= MAX_WARDS:
        return None
    return ward


def _meshes(geometry: dict[str, Any]) -> tuple[str, ...]:
    """多角形にかかる 1km メッシュ。"""
    polygon = shape(geometry)
    min_lon, min_lat, max_lon, max_lat = polygon.bounds
    found = set()
    lat = int(min_lat / MESH_LAT) * MESH_LAT
    while lat < max_lat:
        lon = int(min_lon / MESH_LON) * MESH_LON
        while lon < max_lon:
            if polygon.intersects(box(lon, lat, lon + MESH_LON, lat + MESH_LAT)):
                found.add(code_1km(lat + MESH_LAT / 2, lon + MESH_LON / 2))
            lon += MESH_LON
        lat += MESH_LAT
    return tuple(sorted(found))


def load(paths: Paths, postals: list[Postal], locator: Locator | None = None) -> list[District]:
    """利用条件の xlsx がなければ空（条件がわからない学区は取り込まない）。"""
    if not paths.ksj_school_terms_xlsx.is_file():
        return []
    terms = parse_terms(require_file(paths.ksj_school_terms_xlsx).read_bytes())
    rows: list[District] = []
    for prefix, kind in KINDS.items():
        for pref in PREFECTURES:
            path = paths.ksj_school_district_zip(prefix, pref)
            if path.is_file():
                data = json.loads(read_zip_member(path, ".geojson").decode("utf-8"))
                rows.extend(parse(data, kind, terms, postals, locator))
    return rows


def write(rows: list[District], path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "kind": [r.kind for r in rows],
        "school_code": [r.school_code for r in rows],
        "name": [r.name for r in rows],
        "muni_code": [r.muni_code for r in rows],
        "city": [r.city for r in rows],
        "meshes": [list(r.meshes) for r in rows],
        "terms": [r.terms for r in rows],
        "note": [r.note for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
