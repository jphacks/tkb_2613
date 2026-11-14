"""500m メッシュ（4次メッシュ）ごとの、年齢5歳階級別人口。

入力は e-Stat の令和2年国勢調査 地域メッシュ統計「男女，年齢（5歳階級）別人口」
（統計表 T001192、JGD2011、第1次地域区画ごとの zip。raw/estat_age/tblT001192H{1次メッシュ}.zip）。
中身は CP932 の CSV で、1 行目が列のコード、2 行目が列の名前、3 行目からデータ。

秘匿の扱い（HTKSYORI）：
- 0：秘匿なし。その行の値をそのまま使う
- 2：秘匿される側。内訳の列は「*」で、HTKSAKI に書かれたメッシュに合算されている。
  「人口（総数）」だけはそのメッシュ自身の値が入っている
- 1：合算先。内訳の列は、自分と、自分に合算された（2 の）メッシュの合計
合算された内訳は、合算先と秘匿メッシュの「人口（総数）」の比で割り戻す。
こうすると、年齢階級ごとの合計は公表値（合算先の内訳）と一致したままになる。
「人口（総数）」には年齢不詳を含むので、階級の和は総数より小さいことがある。
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import decode, parse_csv, read_zip_member, write_parquet

MESH_500M = re.compile(r"\d{9}")
FILE_NAME = re.compile(r"tblT001192H(\d{4})\.zip")
# 1都3県の本土にかかる第1次地域区画（島しょ部は使わない）
FIRST_MESHES = ("5238", "5239", "5240", "5338", "5339", "5340", "5438", "5439")
KEY_COLUMN = "KEY_CODE"
TOTAL_COLUMN = "人口(総数)"
# 5歳階級の列の名前（NFKC で正規化したあと）。最後は「95歳以上」
CLASS_COLUMN = re.compile(r"(\d+)[~～](\d+)歳人口 総数|(\d+)歳以上人口 総数")
CLASS_COUNT = 20
SECRET_NONE, SECRET_RECEIVER, SECRET_HIDDEN = "0", "1", "2"

CLASS_LABELS = (*(f"{5 * i}-{5 * i + 4}" for i in range(CLASS_COUNT - 1)), "95-")


def class_column(index: int) -> str:
    return f"age_{5 * index:02d}"


SCHEMA = pa.schema(
    [("mesh_500m", pa.string()), ("total", pa.float64())]
    + [(class_column(i), pa.float64()) for i in range(CLASS_COUNT)]
)


@dataclass(frozen=True)
class RawRow:
    mesh_500m: str
    secret: str
    receiver: str
    total: int
    # 秘匿される側（secret == "2"）は None
    classes: tuple[int, ...] | None


@dataclass(frozen=True)
class AgeRow:
    mesh_500m: str
    total: float
    classes: tuple[float, ...]


def _normalized(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip()


def parse(text: str, source: str) -> list[RawRow]:
    rows = parse_csv(text)
    if len(rows) < 2 or rows[0][0].strip() != KEY_COLUMN:
        raise DataPrepError(f"{source}: 1 行目が {KEY_COLUMN} から始まっていません")
    names = [_normalized(n) for n in rows[1]]
    if TOTAL_COLUMN not in names:
        raise DataPrepError(f"{source}: 2 行目に「人口（総数）」の列がありません")
    total_at = names.index(TOTAL_COLUMN)
    class_at = [i for i, n in enumerate(names) if CLASS_COLUMN.fullmatch(n)]
    if len(class_at) != CLASS_COUNT:
        raise DataPrepError(
            f"{source}: 5歳階級の列が {CLASS_COUNT} 個ではありません（{len(class_at)} 個）"
        )
    result: list[RawRow] = []
    for line_no, row in enumerate(rows[2:], start=3):
        key = row[0].strip()
        if not MESH_500M.fullmatch(key):
            raise DataPrepError(f"{source}:{line_no}: メッシュコードが 9 桁ではありません: {key}")
        secret = row[1].strip() or SECRET_NONE
        if secret not in (SECRET_NONE, SECRET_RECEIVER, SECRET_HIDDEN):
            raise DataPrepError(f"{source}:{line_no}: 秘匿処理の値が想定外です: {secret!r}")
        classes = (
            None
            if secret == SECRET_HIDDEN
            else tuple(_count(row[i], source, line_no) for i in class_at)
        )
        result.append(
            RawRow(
                mesh_500m=key,
                secret=secret,
                receiver=row[2].strip(),
                total=_count(row[total_at], source, line_no),
                classes=classes,
            )
        )
    return result


def _count(cell: str, source: str, line_no: int) -> int:
    value = cell.strip()
    if not value.isdigit():
        raise DataPrepError(f"{source}:{line_no}: 数値ではない値があります: {value!r}")
    return int(value)


def redistribute(rows: Sequence[RawRow]) -> list[AgeRow]:
    """合算された内訳を、合算先と秘匿メッシュの総数の比で割り戻す。"""
    by_key = {r.mesh_500m: r for r in rows}
    members: dict[str, list[RawRow]] = defaultdict(list)
    for r in rows:
        if r.secret == SECRET_HIDDEN:
            members[_receiver_of(r, by_key)].append(r)
    result: list[AgeRow] = []
    for r in rows:
        if r.secret == SECRET_HIDDEN:
            continue
        if r.classes is None:
            raise DataPrepError(f"{r.mesh_500m} の内訳がありません")
        group = [r, *members.get(r.mesh_500m, [])]
        group_total = sum(m.total for m in group)
        for m in group:
            share = m.total / group_total if group_total else (1.0 if m is r else 0.0)
            result.append(
                AgeRow(
                    mesh_500m=m.mesh_500m,
                    total=float(m.total),
                    classes=tuple(c * share for c in r.classes),
                )
            )
    return result


def _receiver_of(row: RawRow, by_key: dict[str, RawRow]) -> str:
    """秘匿メッシュの内訳が入っている合算先。合算先がまた秘匿されていればたどる。"""
    seen = {row.mesh_500m}
    current = row
    while current.secret == SECRET_HIDDEN:
        nxt = by_key.get(current.receiver)
        if nxt is None or nxt.mesh_500m in seen:
            raise DataPrepError(
                f"秘匿メッシュ {row.mesh_500m} の合算先 {current.receiver} が表にありません"
            )
        seen.add(nxt.mesh_500m)
        current = nxt
    return current.mesh_500m


def zip_paths(directory: Path) -> list[Path]:
    """8つの第1次地域区画の zip がそろっているかを確かめて返す。"""
    found = {m.group(1): p for p in directory.glob("*.zip") if (m := FILE_NAME.fullmatch(p.name))}
    missing = [code for code in FIRST_MESHES if code not in found]
    if missing:
        raise DataPrepError(
            f"{directory} に年齢別人口の zip が足りません（{', '.join(missing)}）。"
            "data-prep/README.md の手順で置いてください"
        )
    return [found[code] for code in FIRST_MESHES]


def load(paths: Paths, allowed_1km: frozenset[str]) -> list[AgeRow]:
    raw: list[RawRow] = []
    for path in zip_paths(paths.estat_age_dir):
        raw.extend(parse(decode(read_zip_member(path, ".txt"), str(path)), str(path)))
    return [r for r in redistribute(raw) if r.mesh_500m[:8] in allowed_1km and r.total > 0]


def write(rows: Sequence[AgeRow], path: Path) -> None:
    columns: dict[str, Sequence[object]] = {
        "mesh_500m": [r.mesh_500m for r in rows],
        "total": [r.total for r in rows],
    }
    for i in range(CLASS_COUNT):
        columns[class_column(i)] = [r.classes[i] for r in rows]
    write_parquet(columns, SCHEMA, path)
