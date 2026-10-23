import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import households
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

# e-Stat の形式を縮めた見本（列は KEY_CODE, 秘匿処理, 秘匿先, 合算, 人口総数, 男, 世帯総数）
SAMPLE = (
    "KEY_CODE,HTKSYORI,HTKSAKI,GASSAN,T001101001,T001101002,T001101034\r\n"
    ",,,,　人口（総数）,　人口（総数）　男,　世帯総数\r\n"
    "533945091,0,,,120,60,55\r\n"
    "533945092,2,533945093,,3,*,2\r\n"
    "533945093,1,,533945092,34,14,15\r\n"
    "533800001,0,,,9,4,4\r\n"
)
ALLOWED = frozenset({"53394509"})


def test_parse_keeps_allowed_meshes_and_suppressed_rows() -> None:
    rows = households.parse(SAMPLE, "x", ALLOWED)

    assert [(r.mesh_500m, r.households, r.population) for r in rows] == [
        ("533945091", 55, 120),
        ("533945092", 2, 3),
        ("533945093", 15, 34),
    ]
    assert rows[0].mesh_1km == "53394509"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("A,B\r\n,,\r\n", "KEY_CODE"),
        ("KEY_CODE,X\r\n,人口（総数）\r\n", "世帯総数"),
        ("KEY_CODE,P,H\r\n,人口（総数）,世帯総数\r\n53394509,1,1\r\n", "9 桁"),
        ("KEY_CODE,P,H\r\n,人口（総数）,世帯総数\r\n533945091,*,1\r\n", "数値ではない"),
    ],
)
def test_parse_rejects_unexpected_format(text: str, message: str) -> None:
    with pytest.raises(DataPrepError, match=message):
        households.parse(text, "x", ALLOWED)


def test_load_reads_zips_and_reports_first_meshes(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    paths.estat_dir.mkdir()
    with zipfile.ZipFile(paths.estat_dir / "tblT001101H5339.zip", "w") as archive:
        archive.writestr("tblT001101H5339.txt", SAMPLE.encode("cp932"))

    loaded = households.load(paths, ALLOWED)
    households.write(loaded.rows, tmp_path / "h.parquet")

    assert loaded.first_meshes == {"5339"}
    table = pq.read_table(tmp_path / "h.parquet").to_pydict()
    assert table["mesh_1km"] == ["53394509"] * 3
    assert table["households"] == [55, 2, 15]


def test_load_explains_where_to_put_files(tmp_path: Path) -> None:
    with pytest.raises(DataPrepError, match="README"):
        households.load(Paths(raw_dir=tmp_path), ALLOWED)
