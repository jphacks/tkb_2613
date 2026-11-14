import csv
import json
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from tkb_api.config import Settings
from tkb_api.routes.diagnose import get_gazetteer
from tkb_data_prep import national_gazetteer, stations
from tkb_data_prep.config import ALL_PREFECTURE_CODES, Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.mesh import code_1km
from tkb_engine.gazetteer import Gazetteer, Knowledge


def _station_feature() -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "N02_005": "テスト",
            "N02_005c": "test-station",
            "N02_003": "テスト線",
            "N02_004": "テスト鉄道",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[139.7000, 35.6896], [139.7010, 35.6896]],
        },
    }


def _write_fixtures(paths: Paths) -> None:
    mesh = code_1km(35.6896, 139.7006)
    paths.postal_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(paths.postal_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # Use csv.writer to retain quoted/empty cells exactly as the source format does.
        source = StringIO()
        writer = csv.writer(source, lineterminator="\n")
        for number, pref in enumerate(ALL_PREFECTURE_CODES, start=1):
            writer.writerow(
                [f"{pref}001", "", f"{number:07d}", "", "", "", f"県{pref}", f"市{pref}", "町"]
            )
        archive.writestr("utf_ken_all.csv", source.getvalue())

    for pref in ALL_PREFECTURE_CODES:
        path = paths.stat_mesh_csv(pref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"都道府県市区町村コード,市区町村名,基準メッシュ・コード\n{pref}001,市{pref},{mesh}\n",
            encoding="utf-8",
        )

    paths.stations_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(paths.stations_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            stations.GEOJSON_SUFFIX,
            json.dumps({"type": "FeatureCollection", "features": [_station_feature()]}),
        )


def test_national_codes_cover_exactly_01_to_47() -> None:
    assert tuple(f"{number:02d}" for number in range(1, 48)) == ALL_PREFECTURE_CODES


def test_streams_national_inputs_and_loads_with_gazetteer(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path / "raw", out_dir=tmp_path / "processed")
    _write_fixtures(paths)

    assert national_gazetteer.build(paths) == (47, 47, 1)
    gazetteer = Gazetteer.load(paths.national_out_dir, knowledge=Knowledge())

    runtime_gazetteers = [
        get_gazetteer(Settings(mock_mode=mock_mode, gazetteer_dir=paths.national_out_dir))
        for mock_mode in (True, False)
    ]

    assert len(gazetteer.postal) == 47
    assert len(gazetteer.muni_meshes) == 47
    assert gazetteer.postal[0]["pref"] == "県01"
    assert gazetteer.postal[-1]["pref"] == "県47"
    assert gazetteer.station_names("テスト") == {"テスト"}
    assert all(runtime.station_names("テスト") == {"テスト"} for runtime in runtime_gazetteers)


def test_feature_reader_yields_incrementally_and_rejects_bad_json() -> None:
    features = [_station_feature(), _station_feature()]
    source = StringIO(json.dumps({"type": "FeatureCollection", "features": features}))
    assert len(list(national_gazetteer._iter_features(source))) == 2

    with pytest.raises(DataPrepError, match="feature"):
        list(national_gazetteer._iter_features(StringIO('{"features":[{"bad":]')))


def test_national_build_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path / "raw", out_dir=tmp_path / "processed")
    _write_fixtures(paths)
    paths.national_out_dir.mkdir(parents=True)
    sentinel = paths.national_out_dir / "postal.parquet"
    sentinel.write_bytes(b"keep")

    with pytest.raises(DataPrepError, match="上書きしません"):
        national_gazetteer.build(paths)
    assert sentinel.read_bytes() == b"keep"
