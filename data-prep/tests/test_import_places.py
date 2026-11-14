import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tkb_data_prep.import_places import DEFAULT_OUTPUT, import_geojsonl, main


def _feature(place_id: str, *, country: str | None, license_name: str | None) -> dict[str, object]:
    source = {
        "dataset": "provider-dataset",
        "record_id": f"source-{place_id}",
        "provider": "Provider",
    }
    if license_name is not None:
        source["license"] = license_name
    properties: dict[str, object] = {
        "id": place_id,
        "names": {"primary": "中央施設", "common": {"ja": ["ちゅうおう"]}},
        "basic_category": "cultural",
        "sources": [source],
    }
    if country is not None:
        properties["addresses"] = [{"country": country}]
    return {
        "type": "Feature",
        "id": place_id,
        "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
        "properties": properties,
    }


def test_stream_import_indexes_only_licensed_japan_records(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    features = [
        _feature("licensed", country="JP", license_name="CC-BY-4.0"),
        _feature("unknown-license", country="JP", license_name=None),
        _feature("other-country", country="US", license_name="CC-BY-4.0"),
    ]
    source.write_text("\n".join(json.dumps(feature) for feature in features), encoding="utf-8")
    output = tmp_path / "places.sqlite3"

    assert import_geojsonl(source, output, provider="Provider", dataset="places", version="r1") == 2
    with sqlite3.connect(output) as db:
        matches = db.execute(
            "SELECT place_id FROM poi_alias WHERE name_key = ? ORDER BY place_id",
            ("ちゅうおう",),
        ).fetchall()
        stored = json.loads(
            db.execute(
                "SELECT record_json FROM poi_place WHERE place_id = ?", ("places:unknown-license",)
            ).fetchone()[0]
        )
    assert matches == [("places:licensed",)]
    assert stored["sources"][0]["license_id"] is None


def test_country_missing_requires_explicit_bounded_input_flag(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    source.write_text(
        json.dumps(_feature("no-country", country=None, license_name="CC-BY-4.0")), encoding="utf-8"
    )
    default_output = tmp_path / "default.sqlite3"
    bounded_output = tmp_path / "bounded.sqlite3"

    assert import_geojsonl(source, default_output, provider="Provider", dataset="places") == 0
    assert (
        import_geojsonl(
            source,
            bounded_output,
            provider="Provider",
            dataset="places",
            allow_country_missing=True,
        )
        == 1
    )


def test_import_refuses_overwrite(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    source.write_text("", encoding="utf-8")
    output = tmp_path / "places.sqlite3"
    output.touch()
    with pytest.raises(FileExistsError):
        import_geojsonl(source, output, provider="Provider", dataset="places")


def test_cli_default_and_help_use_api_gazetteer_directory(monkeypatch, capsys) -> None:
    assert Path("data/processed/places.sqlite3") == DEFAULT_OUTPUT
    monkeypatch.setattr(sys, "argv", ["tkb_data_prep.import_places", "--help"])

    with pytest.raises(SystemExit) as result:
        main()

    assert result.value.code == 0
    help_text = capsys.readouterr().out.replace("\\", "/")
    assert "data/processed/places.sqlite3" in help_text
    assert "engine/data/processed" not in help_text
