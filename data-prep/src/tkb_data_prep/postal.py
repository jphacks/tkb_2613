"""郵便番号と市区町村の対応表。

入力は日本郵便の「住所の郵便番号（1レコード1行、UTF-8形式）」（utf_ken_all.zip）。
ヘッダーなしの CSV で、1 列目が全国地方公共団体コード（5 桁）、3 列目が郵便番号（7 桁）、
7〜9 列目が都道府県名・市区町村名・町域名（漢字）。
町域名は「以下に掲載がない場合」なども含めてそのまま残す。
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import decode, parse_csv, read_zip_member, write_parquet

MUNI_CODE = re.compile(r"\d{5}")
POSTAL_CODE = re.compile(r"\d{7}")
MIN_COLUMNS = 9

SCHEMA = pa.schema(
    [
        ("postal_code", pa.string()),
        ("muni_code", pa.string()),
        ("pref", pa.string()),
        ("city", pa.string()),
        ("town", pa.string()),
    ]
)


@dataclass(frozen=True)
class Postal:
    postal_code: str
    muni_code: str
    pref: str
    city: str
    town: str


def parse(rows: Iterable[list[str]], source: str) -> list[Postal]:
    """1 列目が 11〜14 で始まる行だけを重複なしで返す。"""
    seen: dict[Postal, None] = {}
    for line_no, row in enumerate(rows, start=1):
        if len(row) < MIN_COLUMNS:
            raise DataPrepError(f"{source}:{line_no}: 列が足りません")
        muni_code, postal_code = row[0].strip(), row[2].strip()
        if not MUNI_CODE.fullmatch(muni_code) or not POSTAL_CODE.fullmatch(postal_code):
            raise DataPrepError(f"{source}:{line_no}: コードの形式が想定外です")
        if muni_code[:2] not in PREFECTURES:
            continue
        pref, city, town = (cell.strip() for cell in row[6:9])
        seen[Postal(postal_code, muni_code, pref, city, town)] = None
    return list(seen)


def load(paths: Paths) -> list[Postal]:
    path = paths.postal_zip
    text = decode(read_zip_member(path, ".csv"), str(path))
    return parse(parse_csv(text), str(path))


def write(rows: list[Postal], path: Path) -> None:
    columns = {
        "postal_code": [r.postal_code for r in rows],
        "muni_code": [r.muni_code for r in rows],
        "pref": [r.pref for r in rows],
        "city": [r.city for r in rows],
        "town": [r.town for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
