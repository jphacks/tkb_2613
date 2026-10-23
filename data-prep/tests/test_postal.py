import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import postal
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

SAMPLE = (
    '01101,"060  ","0600000","ホッカイドウ","サッポロシ","イカ","北海道","札幌市中央区",'
    '"以下に掲載がない場合",0,0,0,0,0,0\n'
    '11341,"355  ","3550806","サイタマケン","ヒキグン","イコ","埼玉県","比企郡滑川町",'
    '"伊古",0,0,0,0,0,0\n'
    '13101,"100  ","1000005","トウキョウト","チヨダク","マル","東京都","千代田区",'
    '"丸の内",0,0,1,0,0,0\n'
    '13101,"100  ","1000005","トウキョウト","チヨダク","マル","東京都","千代田区",'
    '"丸の内",0,0,1,0,0,0\n'
)


def test_load_keeps_target_prefectures_without_duplicates(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    paths.postal_zip.parent.mkdir(parents=True)
    with zipfile.ZipFile(paths.postal_zip, "w") as archive:
        archive.writestr("utf_ken_all.csv", SAMPLE)

    rows = postal.load(paths)
    postal.write(rows, tmp_path / "postal.parquet")

    table = pq.read_table(tmp_path / "postal.parquet").to_pydict()
    assert table == {
        "postal_code": ["3550806", "1000005"],
        "muni_code": ["11341", "13101"],
        "pref": ["埼玉県", "東京都"],
        "city": ["比企郡滑川町", "千代田区"],
        "town": ["伊古", "丸の内"],
    }


@pytest.mark.parametrize(
    "row",
    [
        ["13101", "100", "1000005"],
        ["13101", "100", "100-0005", "", "", "", "東京都", "千代田区", "丸の内"],
    ],
)
def test_parse_rejects_malformed_rows(row: list[str]) -> None:
    with pytest.raises(DataPrepError):
        postal.parse([row], "x")
