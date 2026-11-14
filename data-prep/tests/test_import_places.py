import json
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys
from tkb_data_prep.import_places import (
    DEFAULT_OUTPUT,
    import_geojsonl,
    import_geoparquet,
    main,
)


def _feature(
    place_id: str,
    *,
    country: str | None,
    license_name: str | None,
    coordinates: tuple[float, float] = (139.0, 35.0),
) -> dict[str, object]:
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
        "geometry": {"type": "Point", "coordinates": list(coordinates)},
        "properties": properties,
    }


def test_stream_import_indexes_only_licensed_japan_records(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    features = [
        _feature("licensed", country="JP", license_name="CC-BY-4.0"),
        _feature("unknown-license", country="JP", license_name=None),
        _feature("other-country", country="US", license_name="CC-BY-4.0"),
        _feature("far-japan", country="JP", license_name="CC-BY-4.0", coordinates=(155, 35)),
    ]
    mixed = _feature("mixed-country", country="JP", license_name="CC-BY-4.0")
    mixed_properties = mixed["properties"]
    assert isinstance(mixed_properties, dict)
    mixed_properties["addresses"] = [{"country": "JP"}, {"country": "US"}]
    features.append(mixed)
    source.write_text("\n".join(json.dumps(feature) for feature in features), encoding="utf-8")
    output = tmp_path / "places.sqlite3"

    assert import_geojsonl(source, output, provider="Provider", dataset="places", version="r1") == 2
    with sqlite3.connect(output) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (PLACE_INDEX_SCHEMA_VERSION,)
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


def test_import_indexes_explicit_space_dot_width_and_kana_variants(tmp_path) -> None:
    feature = _feature("variants", country="JP", license_name="CC-BY-4.0")
    properties = feature["properties"]
    assert isinstance(properties, dict)
    properties["names"] = {"primary": "東京・文化 館"}
    source = tmp_path / "places.geojsonl"
    source.write_text(json.dumps(feature), encoding="utf-8")
    output = tmp_path / "places.sqlite3"

    import_geojsonl(source, output, provider="Provider", dataset="places")

    with sqlite3.connect(output) as db:
        keys = {row[0] for row in db.execute("SELECT name_key FROM poi_alias")}
    assert set(place_name_keys("東京・文化 館")) <= keys
    assert set(place_name_keys("東京 文化館")) <= keys
    assert set(place_name_keys("東京･文化館")) <= keys


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

    outside_source = tmp_path / "outside-no-country.geojsonl"
    outside_source.write_text(
        json.dumps(
            _feature(
                "outside-no-country",
                country=None,
                license_name="CC-BY-4.0",
                coordinates=(154.0001, 35),
            )
        ),
        encoding="utf-8",
    )
    outside_output = tmp_path / "outside.sqlite3"
    assert (
        import_geojsonl(
            outside_source,
            outside_output,
            provider="Provider",
            dataset="places",
            allow_country_missing=True,
        )
        == 0
    )


def test_japan_bounds_are_inclusive_and_reject_outside_coordinates(tmp_path) -> None:
    source = tmp_path / "bounds.geojsonl"
    coordinates = [
        (122, 20),
        (154, 46),
        (121.9999, 35),
        (154.0001, 35),
        (139, 19.9999),
        (139, 46.0001),
    ]
    features = [
        _feature(f"bounds-{i}", country="JP", license_name="CC-BY-4.0", coordinates=point)
        for i, point in enumerate(coordinates)
    ]
    source.write_text("\n".join(json.dumps(feature) for feature in features), encoding="utf-8")
    output = tmp_path / "bounds.sqlite3"
    assert import_geojsonl(source, output, provider="Provider", dataset="places") == 2


def test_import_refuses_overwrite(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    source.write_text("", encoding="utf-8")
    output = tmp_path / "places.sqlite3"
    output.touch()
    with pytest.raises(FileExistsError):
        import_geojsonl(source, output, provider="Provider", dataset="places")


def test_geoparquet_batches_filter_country_private_address_and_unknown_license(tmp_path) -> None:
    source = tmp_path / "places.parquet"
    rows = []
    for place_id, theme, kind, country, category, license_name in [
        ("jp-ok", "places", "place", "JP", "cultural", "CC0-1.0"),
        ("jp-unlicensed", "places", "place", "JP", "cultural", None),
        ("us", "places", "place", "US", "cultural", "CC0-1.0"),
        ("far-jp", "places", "place", "JP", "cultural", "CC0-1.0"),
        ("mixed", "places", "place", "JP", "cultural", "CC0-1.0"),
        ("address", "addresses", "address", "JP", "cultural", "CC0-1.0"),
        ("private", "places", "place", "JP", "private_residence", "CC0-1.0"),
        ("apartment", "places", "place", "JP", "apartment", "CC0-1.0"),
    ]:
        feature = _feature(place_id, country=country, license_name=license_name)
        properties = feature["properties"]
        assert isinstance(properties, dict)
        properties["basic_category"] = category
        if place_id == "jp-ok":
            properties["addresses"] = [
                {
                    "country": "JP",
                    "locality": "横手市",
                    "freeform": "個人住所相当の番地情報",
                }
            ]
        elif place_id == "mixed":
            properties["addresses"] = [{"country": "JP"}, {"country": "US"}]
        coordinates = Point(155 if place_id == "far-jp" else 139, 35).wkb
        rows.append(
            {
                "id": place_id,
                "theme": theme,
                "type": kind,
                "geometry": coordinates,
                **properties,
            }
        )
    pq.write_table(pa.Table.from_pylist(rows), source)
    output = tmp_path / "places.sqlite3"

    assert import_geoparquet(
        source, output, provider="Overture Maps", dataset="places", batch_size=2
    ) == 2
    with sqlite3.connect(output) as db:
        ids = {row[0] for row in db.execute("SELECT place_id FROM poi_place")}
        aliases = {
            row[0]
            for row in db.execute("SELECT place_id FROM poi_alias")
        }
        stored = json.loads(
            db.execute(
                "SELECT record_json FROM poi_place WHERE place_id = ?", ("places:jp-ok",)
            ).fetchone()[0]
        )
    assert ids == {"places:jp-ok", "places:jp-unlicensed"}
    assert aliases == {"places:jp-ok"}
    assert stored["area_label"] == "横手市"
    assert "個人住所相当の番地情報" not in json.dumps(stored, ensure_ascii=False)


def test_area_label_uses_only_unambiguous_japan_locality(tmp_path) -> None:
    source = tmp_path / "places.geojsonl"
    feature = _feature("area", country="JP", license_name="CC0-1.0")
    properties = feature["properties"]
    assert isinstance(properties, dict)
    properties["addresses"] = [
        {"country": "JP", "locality": "世田谷区", "freeform": "1-2-3"},
    ]
    source.write_text(json.dumps(feature), encoding="utf-8")
    output = tmp_path / "area.sqlite3"
    import_geojsonl(source, output, provider="P", dataset="places")
    with sqlite3.connect(output) as db:
        stored = json.loads(db.execute("SELECT record_json FROM poi_place").fetchone()[0])
    assert stored["area_label"] == "世田谷区"
    assert "freeform" not in stored


def test_geoparquet_requires_partition_columns_and_refuses_overwrite(tmp_path) -> None:
    malformed = tmp_path / "missing-partitions.parquet"
    pq.write_table(pa.table({"id": ["x"]}), malformed)
    with pytest.raises(ValueError, match="theme, type"):
        import_geoparquet(malformed, tmp_path / "out.sqlite3", provider="P", dataset="D")

    valid = tmp_path / "valid.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": "x",
                    "theme": "places",
                    "type": "place",
                    "geometry": Point(139, 35).wkb,
                    "names": {"primary": "施設"},
                    "addresses": [{"country": "JP"}],
                    "sources": [],
                }
            ]
        ),
        valid,
    )
    output = tmp_path / "exists.sqlite3"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        import_geoparquet(valid, output, provider="P", dataset="D")
    assert output.read_bytes() == b"keep"


def test_cli_default_and_help_use_api_gazetteer_directory(monkeypatch, capsys) -> None:
    assert Path("data/processed/places.sqlite3") == DEFAULT_OUTPUT
    monkeypatch.setattr(sys, "argv", ["tkb_data_prep.import_places", "--help"])

    with pytest.raises(SystemExit) as result:
        main()

    assert result.value.code == 0
    help_text = capsys.readouterr().out.replace("\\", "/")
    assert "data/processed/places.sqlite3" in help_text
    assert "engine/data/processed" not in help_text
