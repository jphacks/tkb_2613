import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION
from tkb_data_prep.import_places import import_geojsonl
from tkb_data_prep.merge_places import merge_place_indexes
from tkb_data_prep.mesh import code_1km


def _index(tmp_path: Path, name: str, dataset: str, place: str) -> Path:
    mesh = tmp_path / "muni_mesh.parquet"
    pq.write_table(pa.table({"mesh_1km": [code_1km(35.0, 139.0)]}), mesh)
    source = tmp_path / f"{name}.geojsonl"
    feature = {
        "type": "Feature",
        "id": "1",
        "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
        "properties": {
            "names": {"primary": place},
            "addresses": [{"country": "JP"}],
            "sources": [{"dataset": dataset, "license": "CC0 1.0"}],
        },
    }
    source.write_text(json.dumps(feature), encoding="utf-8")
    output = tmp_path / f"{name}.sqlite3"
    import_geojsonl(source, output, mesh_index_path=mesh, provider="P", dataset=dataset)
    return output


def test_merge_combines_inputs_and_sets_version(tmp_path: Path) -> None:
    a = _index(tmp_path, "a", "ds-a", "施設A")
    b = _index(tmp_path, "b", "ds-b", "施設B")
    output = tmp_path / "out" / "merged.sqlite3"

    added = merge_place_indexes([a, b], output)

    assert list(added.values()) == [1, 1]
    with sqlite3.connect(output) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == PLACE_INDEX_SCHEMA_VERSION
        assert db.execute("SELECT COUNT(*) FROM poi_place").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM poi_alias").fetchone()[0] >= 2


def test_merge_refuses_overwrite_and_bad_version(tmp_path: Path) -> None:
    a = _index(tmp_path, "a", "ds-a", "施設A")
    output = tmp_path / "merged.sqlite3"
    merge_place_indexes([a], output)
    with pytest.raises(FileExistsError):
        merge_place_indexes([a], output)
    with sqlite3.connect(a) as db:
        db.execute("PRAGMA user_version = 1")
    with pytest.raises(ValueError, match="schema version"):
        merge_place_indexes([a], tmp_path / "other.sqlite3")
