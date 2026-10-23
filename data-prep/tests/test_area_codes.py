from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tkb_data_prep import area_codes
from tkb_data_prep.area_codes import AreaCode, NameIndex, Problem
from tkb_data_prep.area_text import Item
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal

MUNIS = [
    MuniMesh("11201", "川越市", "53394500"),
    MuniMesh("11235", "富士見市", "53394500"),
    MuniMesh("11241", "鶴ヶ島市", "53394500"),
    MuniMesh("11346", "川島町", "53394500"),
    MuniMesh("11348", "鳩山町", "53394500"),
    MuniMesh("11349", "ときがわ町", "53394500"),
    MuniMesh("12101", "千葉市中央区", "53394500"),
    MuniMesh("12102", "千葉市花見川区", "53394500"),
    MuniMesh("12224", "鎌ケ谷市", "53394500"),
    MuniMesh("13101", "千代田区", "53394500"),
    MuniMesh("13102", "中央区", "53394500"),
    MuniMesh("13204", "三鷹市", "53394500"),
]
POSTALS = [
    Postal("3500100", "11346", "埼玉県", "比企郡川島町", "以下に掲載がない場合"),
    Postal("3500300", "11348", "埼玉県", "比企郡鳩山町", "以下に掲載がない場合"),
    Postal("3550300", "11349", "埼玉県", "比企郡ときがわ町", "以下に掲載がない場合"),
]
INDEX = NameIndex.build(MUNIS, POSTALS)
HEADER = ["area_code", "section_code", "target_text"]


def munis(*items: str) -> list[tuple[str, bool, str]]:
    result = area_codes.convert([HEADER, ["049", "259", "、".join(items)]], INDEX)
    assert result.problems == []
    return [(r.muni_code, r.partial, r.note) for r in result.rows]


def test_whole_and_partial_municipalities() -> None:
    assert munis("埼玉県川越市", "富士見市（水谷東二丁目及び三丁目を除く。）") == [
        ("11201", False, ""),
        ("11235", True, "水谷東二丁目及び三丁目を除く"),
    ]


def test_name_with_town_suffix_is_partial() -> None:
    assert munis("東京都三鷹市中原一丁目") == [("13204", True, "中原一丁目")]


def test_spelling_variants_match() -> None:
    assert munis("埼玉県鶴ヶ島市", "千葉県鎌ヶ谷市") == [("11241", False, ""), ("12224", False, "")]


def test_county_is_expanded_with_limit() -> None:
    assert munis("埼玉県比企郡（川島町及び鳩山町に限る。）") == [
        ("11346", False, "川島町及び鳩山町に限る"),
        ("11348", False, "川島町及び鳩山町に限る"),
    ]


def test_county_is_expanded_with_exclusion() -> None:
    assert munis("埼玉県比企郡（川島町を除く。）") == [
        ("11348", False, "川島町を除く"),
        ("11349", False, "川島町を除く"),
    ]


def test_part_of_a_ward_is_excluded() -> None:
    rows = munis("千葉県千葉市（花見川区（柏井に限る。）を除く。）")

    assert rows == [
        ("12101", False, "花見川区（柏井に限る。）を除く"),
        ("12102", True, "花見川区（柏井に限る）を除く"),
    ]


def test_tokyo_wards() -> None:
    assert [code for code, _, _ in munis("東京都23区")] == ["13101", "13102"]


def test_other_prefectures_are_skipped_and_rows_deduplicated() -> None:
    result = area_codes.convert(
        [HEADER, ["0274", "188", "群馬県藤岡市、埼玉県川越市、川越市"]], INDEX
    )

    assert result.rows == [AreaCode("0274", "188", "11201", False, "")]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("埼玉県所沢市", "見つかりません"),
        ("埼玉県比企郡（滑川町に限る。）", "見つからない名前"),
        ("埼玉県比企郡（一部）", "想定外"),
    ],
)
def test_unresolved_items_are_reported(text: str, reason: str) -> None:
    result = area_codes.convert([HEADER, ["04", "227", text]], INDEX)

    assert result.rows == []
    [problem] = result.problems
    assert problem.section_code == "227"
    assert reason in problem.reason


def test_problem_shows_the_original_item() -> None:
    result = area_codes.convert([HEADER, ["04", "227", "埼玉県比企郡（一部）"]], INDEX)

    assert result.problems == [
        Problem("04", "227", "埼玉県比企郡（一部）", "郡・市の中の地域の書き方が想定外です")
    ]


@pytest.mark.parametrize(
    "rows",
    [
        [["code", "section", "text"]],
        [HEADER, ["49", "259", "埼玉県川越市"]],
        [HEADER, ["049", "259"]],
    ],
)
def test_malformed_manual_csv_is_rejected(rows: list[list[str]]) -> None:
    with pytest.raises(DataPrepError):
        area_codes.convert(rows, INDEX)


def test_resolve_returns_reason_for_unknown_name() -> None:
    assert area_codes.resolve(INDEX, "11", Item("埼玉県", "所沢市", "")) == (
        "市区町村名が見つかりません"
    )


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(manual_dir=tmp_path)
    paths.area_codes_csv.write_text(
        "area_code,section_code,target_text\n049,259,埼玉県川越市\n", encoding="utf-8"
    )

    converted = area_codes.load(paths, INDEX)
    area_codes.write(converted.rows, tmp_path / "a.parquet")

    assert pq.read_table(tmp_path / "a.parquet").to_pydict() == {
        "area_code": ["049"],
        "section_code": ["259"],
        "muni_code": ["11201"],
        "partial": [False],
        "note": [""],
    }
