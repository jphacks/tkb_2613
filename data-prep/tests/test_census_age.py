import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import census_age
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

CLASS_NAMES = [f"　{5 * i}～{5 * i + 4}歳人口　総数" for i in range(19)] + [
    "　９５歳以上人口　総数"
]


def sample(rows: list[str]) -> str:
    codes = ",".join(f"T001192{i:03d}" for i in range(1, 22))
    names = ",".join(["　人口（総数）", *CLASS_NAMES])
    return f"KEY_CODE,HTKSYORI,HTKSAKI,GASSAN,{codes}\r\n,,,,{names}\r\n" + "".join(
        f"{r}\r\n" for r in rows
    )


def row(key: str, secret: str, receiver: str, total: int, classes: list[int] | None) -> str:
    values = ["*"] * 20 if classes is None else [str(c) for c in classes]
    return ",".join([key, secret, receiver, "", str(total), *values])


def classes_with(index: int, value: int) -> list[int]:
    return [value if i == index else 0 for i in range(20)]


# 533945093 が合算先。内訳の 20〜24 歳 40 人は、自分（総数30）と 533945092（総数10）の合計
SAMPLE = sample(
    [
        row("533945091", "0", "", 100, classes_with(4, 7)),
        row("533945092", "2", "533945093", 10, None),
        row("533945093", "1", "", 30, classes_with(4, 40)),
        row("533800001", "0", "", 5, classes_with(4, 1)),
    ]
)


def test_redistribute_splits_merged_breakdown_by_total_population() -> None:
    rows = census_age.redistribute(census_age.parse(SAMPLE, "x"))
    by_key = {r.mesh_500m: r for r in rows}

    assert by_key["533945093"].classes[4] == pytest.approx(30.0)
    assert by_key["533945092"].classes[4] == pytest.approx(10.0)
    assert by_key["533945091"].classes[4] == pytest.approx(7.0)
    # 合計は公表値（合算先の内訳を含む、秘匿されていない行の和）と一致する
    assert sum(r.classes[4] for r in rows) == pytest.approx(7 + 40 + 1)


def test_redistribute_gives_everything_to_receiver_when_totals_are_zero() -> None:
    rows = census_age.redistribute(
        census_age.parse(
            sample(
                [
                    row("533945092", "2", "533945093", 0, None),
                    row("533945093", "1", "", 0, classes_with(0, 2)),
                ]
            ),
            "x",
        )
    )
    assert {r.mesh_500m: r.classes[0] for r in rows} == {"533945093": 2.0, "533945092": 0.0}


def test_redistribute_rejects_missing_receiver() -> None:
    parsed = census_age.parse(sample([row("533945092", "2", "533945099", 3, None)]), "x")
    with pytest.raises(DataPrepError, match="合算先"):
        census_age.redistribute(parsed)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("A,B\r\n,,\r\n", "KEY_CODE"),
        ("KEY_CODE,X\r\n,人口\r\n", "人口（総数）"),
        ("KEY_CODE,P\r\n,人口（総数）\r\n", "5歳階級"),
        (sample([row("53394509", "0", "", 1, classes_with(0, 1))]), "9 桁"),
        (sample([row("533945091", "7", "", 1, classes_with(0, 1))]), "秘匿処理"),
        (sample([row("533945091", "0", "", 1, None)]), "数値ではない"),
    ],
)
def test_parse_rejects_unexpected_format(text: str, message: str) -> None:
    with pytest.raises(DataPrepError, match=message):
        census_age.parse(text, "x")


def write_zips(directory: Path, codes: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for code in codes:
        with zipfile.ZipFile(directory / f"tblT001192H{code}.zip", "w") as archive:
            body = SAMPLE if code == "5339" else sample([])
            archive.writestr(f"tblT001192H{code}.txt", body.encode("cp932"))


def test_load_requires_all_eight_first_meshes(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    write_zips(paths.estat_age_dir, ("5339",))
    with pytest.raises(DataPrepError, match="5238"):
        census_age.load(paths, frozenset({"53394509"}))


def test_load_and_write_keeps_allowed_meshes(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    write_zips(paths.estat_age_dir, census_age.FIRST_MESHES)

    rows = census_age.load(paths, frozenset({"53394509"}))
    census_age.write(rows, tmp_path / "a.parquet")

    table = pq.read_table(tmp_path / "a.parquet").to_pydict()
    assert sorted(table["mesh_500m"]) == ["533945091", "533945092", "533945093"]
    assert sum(table["age_20"]) == pytest.approx(47.0)
    assert census_age.CLASS_LABELS[4] == "20-24"
    assert census_age.CLASS_LABELS[-1] == "95-"
