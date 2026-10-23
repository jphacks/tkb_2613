"""市外局番と市区町村の対応表。

入力は手作りの manual/area_codes.csv（総務省「市外局番の一覧」から 1都3県を含む行を写したもの）。
対象地域の文章を市区町村に分け、名前を市区町村コードに直す。
名前の照合には muni_mesh の市区町村名と、郡名の付いた郵便番号の表の市区町村名を使う。
- 郡・政令市・「23区」は、その中の町村・区に展開する
- 市区町村の一部だけが対象なら partial を true にし、但し書きを note に入れる
- 1都3県以外の地域は除外する。コードに直せなかったものは problems に入れる
"""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.area_text import CLOSE, OPEN, Item, Scope, parse_items, parse_qualified
from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_csv, write_parquet
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal

HEADER = ["area_code", "section_code", "target_text"]
PREF_CODES = {name: code for code, name in PREFECTURES.items()}
TOKYO_WARDS = "23区"
TOKYO_WARD_CODES = range(13101, 13124)

SCHEMA = pa.schema(
    [
        ("area_code", pa.string()),
        ("section_code", pa.string()),
        ("muni_code", pa.string()),
        ("partial", pa.bool_()),
        ("note", pa.string()),
    ]
)


@dataclass(frozen=True)
class AreaCode:
    area_code: str
    section_code: str
    muni_code: str
    partial: bool
    note: str


@dataclass(frozen=True)
class Problem:
    area_code: str
    section_code: str
    text: str
    reason: str


@dataclass(frozen=True)
class Converted:
    rows: list[AreaCode]
    problems: list[Problem]


@dataclass(frozen=True)
class _Muni:
    code: str
    partial: bool
    note: str


def normalize(name: str) -> str:
    """表記ゆれ（全角数字、「ヶ」と「ケ」）をそろえた照合用の名前。"""
    return unicodedata.normalize("NFKC", name).replace("ヶ", "ケ").replace("ヵ", "カ")


class NameIndex:
    """都道府県コードと名前から市区町村コードを引く。"""

    def __init__(self, names: Iterable[tuple[str, str]]) -> None:
        # (市区町村コード, 名前) の組
        self._names: dict[tuple[str, str], set[str]] = {}
        for code, name in names:
            self._names.setdefault((code[:2], normalize(name)), set()).add(code)

    @classmethod
    def build(cls, munis: Iterable[MuniMesh], postals: Iterable[Postal]) -> "NameIndex":
        pairs = {(m.muni_code, m.muni_name) for m in munis}
        pairs |= {(p.muni_code, p.city) for p in postals}
        return cls(sorted(pairs))

    def exact(self, pref_code: str, name: str) -> list[str]:
        return sorted(self._names.get((pref_code, normalize(name)), set()))

    def members(self, pref_code: str, container: str) -> dict[str, str]:
        """郡・政令市・23区の中の町村・区（短い名前 → コード）。"""
        key = normalize(container)
        found: dict[str, str] = {}
        for (pref, name), codes in self._names.items():
            if pref != pref_code:
                continue
            for code in codes:
                if key == normalize(TOKYO_WARDS) and int(code) in TOKYO_WARD_CODES:
                    found[name] = code
                elif name.startswith(key) and len(name) > len(key):
                    found[name[len(key) :]] = code
        return found

    def longest_prefix(self, pref_code: str, name: str) -> str | None:
        key = normalize(name)
        known = [n for (p, n) in self._names if p == pref_code and key.startswith(n) and n != key]
        return max(known, key=len, default=None)


def resolve(index: NameIndex, pref_code: str, item: Item) -> list[_Muni] | str:
    """市区町村のリストか、直せなかった理由を返す。"""
    codes = index.exact(pref_code, item.name)
    if codes:
        return [_Muni(code, bool(item.qualifier), item.qualifier) for code in codes]
    members = index.members(pref_code, item.name)
    if members:
        return _expand(members, item.qualifier)
    prefix = index.longest_prefix(pref_code, item.name)
    if prefix is not None:
        rest = normalize(item.name)[len(prefix) :]
        note = rest + (f"{OPEN}{item.qualifier}{CLOSE}" if item.qualifier else "")
        return [_Muni(code, True, note) for code in index.exact(pref_code, prefix)]
    return "市区町村名が見つかりません"


def _expand(members: dict[str, str], qualifier: str) -> list[_Muni] | str:
    if not qualifier:
        return [_Muni(code, False, "") for code in members.values()]
    qualified = parse_qualified(qualifier)
    if qualified is None:
        return "郡・市の中の地域の書き方が想定外です"
    listed = {normalize(name): inner for name, inner in qualified.names}
    unknown = sorted(set(listed) - set(members))
    if unknown:
        return f"郡・市の中に見つからない名前があります: {'、'.join(unknown)}"
    if qualified.scope is Scope.LIMIT:
        return [
            _Muni(members[name], bool(inner), inner or qualifier) for name, inner in listed.items()
        ]
    result = [_Muni(code, False, qualifier) for name, code in members.items() if name not in listed]
    for name, inner in listed.items():
        if inner:
            # 「花見川区（柏井に限る。）を除く」のように、区の一部だけが除かれる
            result.append(_Muni(members[name], True, f"{name}{OPEN}{inner}{CLOSE}を除く"))
    return result


def convert(manual_rows: Iterable[list[str]], index: NameIndex) -> Converted:
    rows: dict[tuple[str, str, str], AreaCode] = {}
    problems: list[Problem] = []
    for area_code, section_code, text in _manual(manual_rows):
        for item in parse_items(text):
            pref_code = PREF_CODES.get(item.pref)
            if pref_code is None:
                continue
            resolved = resolve(index, pref_code, item)
            if isinstance(resolved, str):
                problems.append(Problem(area_code, section_code, _show(item), resolved))
                continue
            for muni in resolved:
                key = (area_code, section_code, muni.code)
                rows.setdefault(
                    key, AreaCode(area_code, section_code, muni.code, muni.partial, muni.note)
                )
    return Converted(rows=list(rows.values()), problems=problems)


def _manual(rows: Iterable[list[str]]) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    for line_no, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row]
        if line_no == 1:
            if cells != HEADER:
                raise DataPrepError(f"area_codes.csv の見出しが {HEADER} ではありません")
            continue
        if len(cells) != len(HEADER) or not cells[0].startswith("0"):
            raise DataPrepError(f"area_codes.csv:{line_no}: 形式が想定外です: {row}")
        result.append((cells[0], cells[1], cells[2]))
    return result


def _show(item: Item) -> str:
    qualifier = f"{OPEN}{item.qualifier}{CLOSE}" if item.qualifier else ""
    return f"{item.pref}{item.name}{qualifier}"


def load(paths: Paths, index: NameIndex) -> Converted:
    return convert(read_csv(paths.area_codes_csv), index)


def write(rows: list[AreaCode], path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "area_code": [r.area_code for r in rows],
        "section_code": [r.section_code for r in rows],
        "muni_code": [r.muni_code for r in rows],
        "partial": [r.partial for r in rows],
        "note": [r.note for r in rows],
    }
    write_parquet(columns, SCHEMA, path)
