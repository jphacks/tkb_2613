import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pyarrow.parquet as pq

from tkb_data_prep import boundaries, school_districts
from tkb_data_prep.config import Paths
from tkb_data_prep.mesh import code_1km
from tkb_data_prep.postal import Postal

HEADER = [
    "都道府県",
    "行政CD",
    "自治体",
    "R3小学校区\n公開条件",
    "R3小学校区\n利用条件",
    "R3小学校区\n特記条件",
    "R3小学校区\n特記条件詳細",
    "R3中学校区\n公開条件",
    "R3中学校区\n利用条件",
    "R3中学校区\n特記条件",
    "R3中学校区\n特記条件詳細",
]
NOTE = "地図データは参考情報とし、教育指導課へお問い合わせください。"
OPEN = "オープンデータ公開"


def terms_row(
    pref: str, code: str, name: str, elementary: str, junior: str = OPEN, note: str = ""
) -> list[str]:
    """利用条件の一覧の1行（小学校区と中学校区で、公開条件・利用条件・特記条件・その詳細）。"""
    special = ["01.あり", note] if note else ["02.なし", "-"]
    return [pref, code, name, "01.公開", elementary, *special, "01.公開", junior, *special]


TERMS = [
    HEADER,
    terms_row("13東京都", "13105", "文京区", OPEN),
    terms_row("13東京都", "13104", "新宿区", "商用利用不可"),
    terms_row(
        "11埼玉県", "11208", "所沢市", "再配布・再利用不可", "再配布・再利用不可", "有償頒布"
    ),
    terms_row("11埼玉県", "11246", "白岡市", "条件公開", "条件公開", NOTE),
]
POSTALS = [
    Postal("1130031", "13105", "東京都", "文京区", "根津"),
    Postal("1600022", "13104", "東京都", "新宿区", "新宿"),
    Postal("3490217", "11246", "埼玉県", "白岡市", "小久喜"),
]


def make_xlsx(rows: list[list[str]]) -> bytes:
    """共有文字列と1枚のシートだけの、最小の xlsx。"""
    strings: list[str] = []
    cells = []
    for r, row in enumerate(rows, start=1):
        refs = []
        for c, value in enumerate(row):
            strings.append(value)
            col = chr(ord("A") + c)
            refs.append(f'<c r="{col}{r}" t="s"><v>{len(strings) - 1}</v></c>')
        cells.append(f'<row r="{r}">{"".join(refs)}</row>')
    shared = "".join(
        f"<si><t>{escape(s)}</t><rPh><t>フリガナ</t></rPh></si>"
        if "不可" in s
        else f"<si><t>{escape(s)}</t></si>"
        for s in strings
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f"<sst>{shared}</sst>")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet><sheetData>{''.join(cells)}</sheetData></worksheet>",
        )
    return buf.getvalue()


def _district(prefix: str, muni: str, name: str, lon: float, lat: float) -> dict[str, object]:
    ring = [[lon, lat], [lon + 0.02, lat], [lon + 0.02, lat + 0.01], [lon, lat + 0.01], [lon, lat]]
    return {
        "type": "Feature",
        "properties": {
            f"{prefix}_001": muni,
            f"{prefix}_002": "区立",
            f"{prefix}_003": "B1",
            f"{prefix}_004": name,
            f"{prefix}_005": "住所",
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def test_parse_terms_reads_each_municipality_and_drops_the_reading_aids() -> None:
    terms = school_districts.parse_terms(make_xlsx(TERMS))

    assert terms["13105"].elementary == "オープンデータ公開"
    assert terms["13104"].elementary == "商用利用不可"
    assert terms["11208"].junior == "再配布・再利用不可"
    assert terms["11246"].elementary_note == NOTE


def test_parse_keeps_usable_municipalities_with_their_terms_and_meshes() -> None:
    terms = school_districts.parse_terms(make_xlsx(TERMS))
    geojson = {
        "features": [
            _district("A27", "13105", "根津小学校", 139.76, 35.71),
            _district("A27", "13104", "新宿小学校", 139.70, 35.69),
            _district("A27", "11208", "所沢小学校", 139.46, 35.79),
            _district("A27", "11246", "白岡小学校", 139.67, 36.01),
            _district("A27", "99999", "表にない町の小学校", 139.0, 35.0),
        ]
    }

    rows = school_districts.parse(geojson, "小学校", terms, POSTALS)

    assert [(r.name, r.city, r.terms, r.note) for r in rows] == [
        ("根津小学校", "文京区", "オープンデータ公開", ""),
        ("新宿小学校", "新宿区", "商用利用不可", ""),
        ("白岡小学校", "白岡市", "条件公開", NOTE),
    ]
    # 多角形（経度 0.02 度 × 緯度 0.01 度）にかかる 1km メッシュ
    assert code_1km(35.715, 139.77) in rows[0].meshes
    assert len(rows[0].meshes) >= 4


def test_parse_finds_the_ward_of_a_designated_city_from_the_boundary() -> None:
    rows_terms = [*TERMS, terms_row("14神奈川県", "14100", "横浜市", OPEN)]
    terms = school_districts.parse_terms(make_xlsx(rows_terms))
    ward = {
        "properties": {"N03_007": "14104"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[139.6, 35.4], [139.7, 35.4], [139.7, 35.5], [139.6, 35.5], [139.6, 35.4]]
            ],
        },
    }
    locator = boundaries.Locator.from_geojson([{"features": [ward]}])
    postals = [*POSTALS, Postal("2310001", "14104", "神奈川県", "横浜市中区", "新港")]
    geojson = {
        "features": [
            _district("A27", "14100", "中区の小学校", 139.62, 35.42),
            _district("A27", "14100", "境界の外の小学校", 139.9, 35.9),
        ]
    }

    rows = school_districts.parse(geojson, "小学校", terms, postals, locator)

    # 区が引けない政令市の学区は、区市町村名を空にせず、取り込まない
    assert [(r.name, r.muni_code, r.city) for r in rows] == [
        ("中区の小学校", "14104", "横浜市中区")
    ]


def test_load_and_write(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    assert school_districts.load(paths, POSTALS) == []
    paths.ksj_school_terms_xlsx.parent.mkdir(parents=True)
    paths.ksj_school_terms_xlsx.write_bytes(make_xlsx(TERMS))
    for prefix, kind_path in (
        ("A27", paths.ksj_school_district_zip("A27", "13")),
        ("A32", paths.ksj_school_district_zip("A32", "13")),
    ):
        with zipfile.ZipFile(kind_path, "w") as archive:
            archive.writestr(
                f"{prefix}-21_13.geojson",
                json.dumps(
                    {"features": [_district(prefix, "13105", f"根津{prefix}", 139.76, 35.71)]}
                ),
            )

    rows = school_districts.load(paths, POSTALS)
    school_districts.write(rows, tmp_path / "school_districts.parquet")

    table = pq.read_table(tmp_path / "school_districts.parquet").to_pydict()
    assert sorted(zip(table["kind"], table["name"], strict=True)) == [
        ("中学校", "根津A32"),
        ("小学校", "根津A27"),
    ]
    assert set(table) == {
        "kind",
        "school_code",
        "name",
        "muni_code",
        "city",
        "meshes",
        "terms",
        "note",
    }
