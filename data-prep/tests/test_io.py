import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import decode, parse_csv, read_csv, read_zip_member, write_parquet


def test_decode_reads_utf8_and_cp932() -> None:
    assert decode("新宿".encode(), "x") == "新宿"
    assert decode("﻿新宿".encode(), "x") == "新宿"
    assert decode("新宿".encode("cp932"), "x") == "新宿"


def test_decode_rejects_unknown_encoding() -> None:
    with pytest.raises(DataPrepError, match="文字コード"):
        decode(b"\x81\xff\xfe", "broken.csv")


def test_parse_csv_skips_blank_lines() -> None:
    assert parse_csv('a,"b,c"\n\n1,2\n') == [["a", "b,c"], ["1", "2"]]


def test_read_csv_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DataPrepError, match="make data"):
        read_csv(tmp_path / "none.csv")


def test_read_zip_member_requires_exactly_one_match(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dir/a.txt", "A")
        archive.writestr("b.csv", "B1")
        archive.writestr("c.csv", "B2")

    assert read_zip_member(path, "a.txt") == b"A"
    with pytest.raises(DataPrepError, match="1 つではありません"):
        read_zip_member(path, ".csv")


def test_write_parquet_keeps_schema(tmp_path: Path) -> None:
    schema = pa.schema([("code", pa.string()), ("n", pa.int64())])
    path = tmp_path / "out" / "t.parquet"

    write_parquet({"code": ("01",), "n": [3]}, schema, path)

    table = pq.read_table(path)
    assert table.schema.equals(schema)
    assert table.to_pydict() == {"code": ["01"], "n": [3]}
