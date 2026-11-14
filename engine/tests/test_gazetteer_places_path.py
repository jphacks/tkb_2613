import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION
from tkb_engine.gazetteer import Gazetteer, Knowledge, resolve_places_index_path


def _places_index(path: Path, *, version: int = PLACE_INDEX_SCHEMA_VERSION) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {version}")


def _gazetteer_tables(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    empty_string = pa.array([], type=pa.string())
    pq.write_table(
        pa.table({"station_name": empty_string, "mesh_1km": empty_string}),
        directory / "stations.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "postal_code": empty_string,
                "muni_code": empty_string,
                "city": empty_string,
                "town": empty_string,
            }
        ),
        directory / "postal.parquet",
    )
    pq.write_table(
        pa.table({"muni_code": empty_string, "mesh_1km": empty_string}),
        directory / "muni_mesh.parquet",
    )


def test_gazetteer_load_uses_places_index_in_selected_directory_first(tmp_path: Path) -> None:
    processed = tmp_path / "data" / "processed"
    national = processed / "national"
    _gazetteer_tables(national)
    root_index = processed / "places.sqlite3"
    national_index = national / "places.sqlite3"
    _places_index(root_index)
    _places_index(national_index)

    gazetteer = Gazetteer.load(national, knowledge=Knowledge())

    assert resolve_places_index_path(national) == national_index
    assert gazetteer.places_path == national_index
    assert gazetteer.places_index_compatible is True


def test_gazetteer_load_falls_back_to_processed_index_for_national_tables(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "data" / "processed"
    national = processed / "national"
    _gazetteer_tables(national)
    root_index = processed / "places.sqlite3"
    _places_index(root_index)

    assert resolve_places_index_path(processed) == root_index
    gazetteer = Gazetteer.load(national, knowledge=Knowledge())

    assert resolve_places_index_path(national) == root_index
    assert gazetteer.places_path == root_index
    assert gazetteer.places_index_compatible is True


def test_selected_national_schema_mismatch_does_not_fall_back_to_parent(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "data" / "processed"
    national = processed / "national"
    _gazetteer_tables(national)
    root_index = processed / "places.sqlite3"
    national_index = national / "places.sqlite3"
    _places_index(root_index)
    _places_index(national_index, version=PLACE_INDEX_SCHEMA_VERSION - 1)

    gazetteer = Gazetteer.load(national, knowledge=Knowledge())

    assert gazetteer.places_path == national_index
    assert gazetteer.places_index_compatible is False


def test_explicit_other_directory_does_not_fall_back_to_its_parent(tmp_path: Path) -> None:
    parent = tmp_path / "custom"
    selected = parent / "tables"
    parent_index = parent / "places.sqlite3"
    _places_index(parent_index)

    assert resolve_places_index_path(selected) is None


def test_missing_places_index_resolves_to_none(tmp_path: Path) -> None:
    processed = tmp_path / "data" / "processed"
    national = processed / "national"

    assert resolve_places_index_path(processed) is None
    assert resolve_places_index_path(national) is None
