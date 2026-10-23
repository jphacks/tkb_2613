import json
import zipfile
from pathlib import Path

import pytest

import tkb_data_prep.__main__ as pipeline
from tkb_data_prep import stations
from tkb_data_prep.config import Paths
from tkb_data_prep.summary import report

MESH_HEADER = "都道府県市区町村コード,市区町村名,基準メッシュ・コード\r\n"
ESTAT = (
    "KEY_CODE,HTKSYORI,HTKSAKI,GASSAN,T001101001,T001101034\r\n"
    ",,,,　人口（総数）,　世帯総数\r\n"
    "533945261,0,,,100,50\r\n"
    "533945262,0,,,30,20\r\n"
)


def build_inputs(root: Path) -> Paths:
    paths = Paths(raw_dir=root / "raw", manual_dir=root / "manual", out_dir=root / "out")
    meshes = {
        "11": "11201,川越市,53394000\r\n",
        "12": "12101,千葉市中央区,53401000\r\n",
        # 島しょ部：e-Stat の zip がない第1次地域区画
        "13": "13104,新宿区,53394526\r\n13361,大島町,52390000\r\n",
        "14": "14101,横浜市鶴見区,53392600\r\n",
    }
    for pref, body in meshes.items():
        path = paths.stat_mesh_csv(pref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((MESH_HEADER + body).encode("cp932"))

    paths.estat_dir.mkdir(parents=True)
    with zipfile.ZipFile(paths.estat_dir / "tblT001101H5339.zip", "w") as archive:
        archive.writestr("tblT001101H5339.txt", ESTAT.encode("cp932"))

    paths.postal_zip.parent.mkdir(parents=True)
    with zipfile.ZipFile(paths.postal_zip, "w") as archive:
        archive.writestr(
            "utf_ken_all.csv",
            '13104,"160  ","1600022","","","","東京都","新宿区","新宿",0,0,1,0,0,0\n',
        )

    shinjuku = {
        "properties": {"N02_003": "京王線", "N02_004": "京王電鉄", "N02_005": "新宿"}
        | {"N02_005c": "003700"},
        "geometry": {"type": "LineString", "coordinates": [[139.700, 35.6896], [139.701, 35.6896]]},
    }
    paths.stations_zip.parent.mkdir(parents=True)
    with zipfile.ZipFile(paths.stations_zip, "w") as archive:
        archive.writestr(stations.GEOJSON_SUFFIX, json.dumps({"features": [shinjuku]}))

    paths.manual_dir.mkdir()
    paths.area_codes_csv.write_text(
        "area_code,section_code,target_text\n03,219,東京都新宿区、所沢市\n", encoding="utf-8"
    )
    return paths


def test_run_writes_every_table_and_reports_counts(tmp_path: Path) -> None:
    paths = build_inputs(tmp_path)

    tables = pipeline.run(paths)
    lines = report(tables)

    assert sorted(p.name for p in paths.out_dir.iterdir()) == [
        "area_codes.parquet",
        "households_500m.parquet",
        "muni_mesh.parquet",
        "postal.parquet",
        "stations.parquet",
    ]
    text = "\n".join(lines)
    assert "世帯数の合計 70" in text
    assert "人口の合計   130" in text
    assert "世帯数の行がない 1km メッシュ 4 / 5" in text
    assert "e-Stat の zip がない第1次地域区画: 5239 5340" in text
    assert "03（番号区画 219）東京都所沢市: 市区町村名が見つかりません" in text


def test_main_prints_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = build_inputs(tmp_path)
    monkeypatch.setattr(pipeline, "Paths", lambda: paths)

    assert pipeline.main() == 0
    assert "== 行数 ==" in capsys.readouterr().out


def test_main_explains_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pipeline, "Paths", lambda: Paths(raw_dir=tmp_path))

    assert pipeline.main() == 1
    assert "make data" in capsys.readouterr().err
