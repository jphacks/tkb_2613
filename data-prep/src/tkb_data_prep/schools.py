"""学校の一覧（大学・短期大学・高等専門学校・高等学校・中等教育学校）。

入力は文部科学省「学校コード」の CSV（data-prep/raw/mext/*.csv）。1行目が見出しで、
見出しの名前で列を探す（見出しのセルに改行が入っていることがある）。見出しのないファイル
（同じ表の続き）は、前のファイルの見出しを使う。廃止された学校と、1都3県の外の学校は落とす。
所在地の市区町村は、郵便番号の表（postal）で引く。引けなければ所在地の文字から探す。

大学は本部の所在地だけが載っていて、ほかのキャンパスは載っていない。
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_csv, write_parquet
from tkb_data_prep.postal import Postal

KINDS = frozenset({"大学", "短期大学", "高等専門学校", "高等学校", "中等教育学校"})
COLUMNS = {
    "code": "学校コード",
    "kind": "学校種",
    "pref": "都道府県番号",
    "name": "学校名",
    "address": "学校所在地",
    "postal": "郵便番号",
    "closed": "属性情報廃止年月日",
}

SCHEMA = pa.schema(
    [
        ("school_code", pa.string()),
        ("kind", pa.string()),
        ("name", pa.string()),
        ("address", pa.string()),
        ("postal_code", pa.string()),
        ("muni_code", pa.string()),
        ("city", pa.string()),
    ]
)


@dataclass(frozen=True)
class School:
    school_code: str
    kind: str
    name: str
    address: str
    postal_code: str
    muni_code: str
    city: str


def parse(files: Iterable[tuple[str, list[list[str]]]], postals: list[Postal]) -> list[School]:
    """files は (名前, CSV の行) の組。"""
    by_postal = {p.postal_code: p for p in postals}
    cities = sorted({(p.city, p.muni_code) for p in postals}, key=lambda c: -len(c[0]))
    header: dict[str, int] | None = None
    schools: dict[str, School] = {}
    for source, rows in files:
        for line_no, row in enumerate(rows, start=1):
            if line_no == 1 and _is_header(row):
                header = _header(row, source)
                continue
            if header is None:
                raise DataPrepError(f"{source}: 見出しの行がありません")
            school = _school(row, header, by_postal, cities)
            if school is not None:
                schools[school.school_code] = school
    return list(schools.values())


def _is_header(row: list[str]) -> bool:
    return any(_clean(cell) == COLUMNS["code"] for cell in row)


def _header(row: list[str], source: str) -> dict[str, int]:
    names = [_clean(cell) for cell in row]
    missing = [label for label in COLUMNS.values() if label not in names]
    if missing:
        raise DataPrepError(f"{source}: 見出しに {'・'.join(missing)} がありません")
    return {key: names.index(label) for key, label in COLUMNS.items()}


def _school(
    row: list[str],
    header: dict[str, int],
    by_postal: dict[str, Postal],
    cities: list[tuple[str, str]],
) -> School | None:
    if len(row) <= max(header.values()):
        return None

    def cell(key: str) -> str:
        return row[header[key]].strip()

    kind = _inside_parens(cell("kind"))
    pref = cell("pref")[:2]
    if kind not in KINDS or pref not in PREFECTURES or cell("closed"):
        return None
    address = cell("address")
    postal_code = re.sub(r"\D", "", cell("postal"))
    found = by_postal.get(postal_code)
    if found is not None:
        city, muni = found.city, found.muni_code
    else:
        rest = address.removeprefix(PREFECTURES[pref])
        city, muni = next(((c, m) for c, m in cities if rest.startswith(c)), ("", ""))
    return School(cell("code"), kind, cell("name"), address, postal_code, muni, city)


def _clean(cell: str) -> str:
    return re.sub(r"\s", "", cell)


def _inside_parens(value: str) -> str:
    m = re.search(r"[（(](.+?)[)）]", value)
    return m[1] if m else value


def load(paths: Paths, postals: list[Postal]) -> list[School]:
    files = sorted(paths.mext_dir.glob("*.csv"))
    if not files:
        raise DataPrepError(
            f"{paths.mext_dir} に学校コードの CSV がありません。make data で取得します"
        )
    return parse(((str(f), read_csv(f)) for f in files), postals)


def write(rows: list[School], path: Path) -> None:
    columns = {
        "school_code": [r.school_code for r in rows],
        "kind": [r.kind for r in rows],
        "name": [r.name for r in rows],
        "address": [r.address for r in rows],
        "postal_code": [r.postal_code for r in rows],
        "muni_code": [r.muni_code for r in rows],
        "city": [r.city for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
