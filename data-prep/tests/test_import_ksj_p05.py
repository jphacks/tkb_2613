import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tkb_data_prep.import_ksj_p05 import (
    DATASET,
    LICENSE_ID,
    P05ArchiveError,
    _bounded_read,
    import_p05,
)
from tkb_data_prep.mesh import code_1km


def _feature(
    code: str = "13101",
    classification: str = "1",
    name: str = "千代田区役所",
    address: str = "東京都千代田区霞が関1番地",
    coordinates: tuple[float, float] = (139.7391, 35.6865),
) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {
            "P05_001": code,
            "P05_002": classification,
            "P05_003": name,
            "P05_004": address,
        },
        "geometry": {"type": "Point", "coordinates": list(coordinates)},
    }


def _archive(
    path: Path,
    features_by_prefecture: dict[str, list[dict[str, object]]] | None = None,
) -> Path:
    features_by_prefecture = features_by_prefecture or {}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        for number in range(1, 48):
            prefecture = f"{number:02d}"
            document = {
                "type": "FeatureCollection",
                "features": features_by_prefecture.get(prefecture, []),
            }
            inner_buffer = io.BytesIO()
            with zipfile.ZipFile(inner_buffer, "w", compression=zipfile.ZIP_DEFLATED) as inner:
                inner.writestr(
                    f"P05-22_{prefecture}.geojson",
                    json.dumps(document, ensure_ascii=False),
                )
            outer.writestr(f"P05-22_{prefecture}_GML.zip", inner_buffer.getvalue())
    return path


def _mesh_index(path: Path) -> Path:
    mesh = code_1km(35.6865, 139.7391)
    pq.write_table(
        pa.table(
            {
                "muni_code": ["13101"],
                "muni_name": ["千代田区"],
                "mesh_1km": [mesh],
            }
        ),
        path,
    )
    return path


def test_imports_national_archive_without_storing_full_address(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "P05-22_GML.zip", {"13": [_feature()]})
    mesh_index = _mesh_index(tmp_path / "muni_mesh.parquet")
    output = tmp_path / "national" / "places.sqlite3"

    result = import_p05(archive, output, mesh_index_path=mesh_index)

    assert result.records == 1
    assert len(result.prefectures) == 47
    assert result.prefectures["13"] == 1
    assert sum(result.prefectures.values()) == 1
    assert result.classifications == {"1": 1}
    assert result.expanded_bytes > 0
    assert result.output_bytes == output.stat().st_size
    with sqlite3.connect(output) as db:
        record_json = db.execute(
            "SELECT record_json FROM poi_place WHERE place_id = ?",
            (f"{DATASET}:{DATASET}_13_000001",),
        ).fetchone()[0]
        record = json.loads(record_json)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM poi_alias").fetchone()[0] > 0
    assert record["label"] == "千代田区役所"
    assert record["area_label"] == "千代田区"
    assert record["taxonomy"] == {
        "p05_classification_code": "1",
        "p05_municipality_code": "13101",
    }
    assert record["sources"][0]["license_id"] == LICENSE_ID
    assert record["sources"][0]["version"] == "2022"
    assert record["sources"][0]["source_url"] == (
        "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html"
    )
    assert "加工して作成" in record["sources"][0]["attribution"]
    assert "霞が関" not in record_json
    assert "addresses" not in record


def test_unknown_municipality_name_is_not_guessed(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path / "P05-22_GML.zip",
        {"13": [_feature(code="13999", address="東京都架空市住所1番地")]},
    )
    mesh_index = _mesh_index(tmp_path / "muni_mesh.parquet")
    output = tmp_path / "places.sqlite3"

    import_p05(archive, output, mesh_index_path=mesh_index)

    with sqlite3.connect(output) as db:
        record = json.loads(db.execute("SELECT record_json FROM poi_place").fetchone()[0])
    assert record["area_label"] is None
    assert "架空" not in json.dumps(record, ensure_ascii=False)


def test_requires_all_47_prefecture_archives(tmp_path: Path) -> None:
    path = tmp_path / "partial.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("P05-22_13_GML.zip", b"not a zip")
    with pytest.raises(P05ArchiveError, match="exactly the 47"):
        import_p05(
            path,
            tmp_path / "places.sqlite3",
            mesh_index_path=_mesh_index(tmp_path / "mesh.parquet"),
        )


def test_reports_unrecognized_facility_classification_code(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path / "P05-22_GML.zip",
        {"13": [_feature(classification="9")]},
    )
    with pytest.raises(P05ArchiveError, match='"9": 1'):
        import_p05(
            archive,
            tmp_path / "places.sqlite3",
            mesh_index_path=_mesh_index(tmp_path / "mesh.parquet"),
        )
    assert not (tmp_path / "places.sqlite3").exists()


def test_rejects_archive_with_zero_features(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "P05-22_GML.zip")
    with pytest.raises(P05ArchiveError, match="no facility features"):
        import_p05(
            archive,
            tmp_path / "places.sqlite3",
            mesh_index_path=_mesh_index(tmp_path / "mesh.parquet"),
        )
    assert not (tmp_path / "places.sqlite3").exists()


def test_rejects_unsafe_nested_member_path(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as outer:
        for number in range(1, 48):
            pref = f"{number:02d}"
            contents = io.BytesIO()
            with zipfile.ZipFile(contents, "w") as inner:
                member = "../escape.geojson" if pref == "13" else f"P05-22_{pref}.geojson"
                inner.writestr(member, '{"type":"FeatureCollection","features":[]}')
            outer.writestr(f"P05-22_{pref}_GML.zip", contents.getvalue())
    with pytest.raises(P05ArchiveError, match="unsafe ZIP member path"):
        import_p05(
            path,
            tmp_path / "places.sqlite3",
            mesh_index_path=_mesh_index(tmp_path / "mesh.parquet"),
        )


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "places.sqlite3"
    output.write_bytes(b"keep existing")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        import_p05(tmp_path / "missing.zip", output, mesh_index_path=tmp_path / "missing.parquet")
    assert output.read_bytes() == b"keep existing"


def test_bounded_reader_rejects_actual_expansion_past_cap() -> None:
    with pytest.raises(P05ArchiveError, match="exceeds 7 bytes"):
        _bounded_read(io.BytesIO(b"01234567"), 7, "fixture entry")
