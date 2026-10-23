from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import muni_mesh
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

HEADER = ["都道府県市区町村コード", "市区町村名", "基準メッシュ・コード"]


def test_parse_skips_header_and_duplicates() -> None:
    rows = [
        HEADER,
        ["13101", "千代田区", "53394509"],
        ["13101", "千代田区", "53394509"],
        ["13102", "中央区", "53394509"],
    ]

    result = muni_mesh.parse(rows, "13.csv")

    assert [(r.muni_code, r.mesh_1km) for r in result] == [
        ("13101", "53394509"),
        ("13102", "53394509"),
    ]
    assert result[0].pref_code == "13"
    assert muni_mesh.meshes(result) == {"53394509"}


def test_parse_drops_other_prefectures() -> None:
    rows = [["19201", "甲府市", "53383500"], ["11101", "さいたま市西区", "53396444"]]

    assert [r.muni_code for r in muni_mesh.parse(rows, "x")] == ["11101"]


@pytest.mark.parametrize(
    "row",
    [["13101", "千代田区"], ["13101", "千代田区", "5339450"], ["1310A", "千代田区", "53394509"]],
)
def test_parse_rejects_malformed_rows(row: list[str]) -> None:
    with pytest.raises(DataPrepError):
        muni_mesh.parse([HEADER, row], "13.csv")


def test_load_reads_every_prefecture_and_writes_parquet(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    for code, name, mesh in [
        ("11101", "さいたま市西区", "53396444"),
        ("12101", "千葉市中央区", "53401000"),
        ("13101", "千代田区", "53394509"),
        ("14101", "横浜市鶴見区", "53392600"),
    ]:
        path = paths.stat_mesh_csv(code[:2])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{','.join(HEADER)}\r\n{code},{name},{mesh}\r\n".encode("cp932"))

    rows = muni_mesh.load(paths)
    muni_mesh.write(rows, tmp_path / "muni_mesh.parquet")

    table = pq.read_table(tmp_path / "muni_mesh.parquet").to_pydict()
    assert table["pref_code"] == ["11", "12", "13", "14"]
    assert table["muni_name"][2] == "千代田区"
