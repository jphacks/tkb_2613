"""ファイルの読み書き（文字コードの判定、zip の展開、Parquet の書き出し）。"""

import csv
import io
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_data_prep.errors import DataPrepError

# 公開データで使われる文字コード。先に UTF-8 を試し、だめなら Shift_JIS（CP932）とみなす
ENCODINGS = ("utf-8-sig", "cp932")


def decode(data: bytes, source: str) -> str:
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DataPrepError(f"{source}: 文字コードを判定できません（UTF-8 でも CP932 でもない）")


def parse_csv(text: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text)) if row]


def read_csv(path: Path) -> list[list[str]]:
    return parse_csv(decode(require_file(path).read_bytes(), str(path)))


def read_zip_member(path: Path, suffix: str) -> bytes:
    """zip の中で名前が suffix で終わるファイルを 1 つだけ読む。"""
    with zipfile.ZipFile(require_file(path)) as archive:
        names = [name for name in archive.namelist() if name.endswith(suffix)]
        if len(names) != 1:
            raise DataPrepError(f"{path}: {suffix} で終わるファイルが 1 つではありません: {names}")
        return archive.read(names[0])


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise DataPrepError(f"{path} がありません。先に make data で取得してください")
    return path


def write_parquet(columns: dict[str, Sequence[object]], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({name: list(values) for name, values in columns.items()}, schema=schema)
    pq.write_table(table, path)
