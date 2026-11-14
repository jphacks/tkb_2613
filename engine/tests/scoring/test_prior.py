from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tkb_engine.scoring import tables as scoring_tables
from tkb_engine.scoring.prior import age_class, age_class_label, prior
from tkb_engine.scoring.tables import ScoringTables, cell_code

PROCESSED = Path(__file__).resolve().parents[3] / "data" / "processed"


def test_cell_code_matches_the_100m_mesh() -> None:
    # 文京区弥生二丁目の代表の点は 100m マス 5339465191（data-prep で作った表と同じ）
    assert cell_code(35.716146, 139.764057) == 5339465191


def test_cell_codes_of_the_test_grid_are_inside_one_1km_mesh(tables: ScoringTables) -> None:
    assert {str(c)[:8] for c in tables.cell.tolist()} == {"53394651"}
    assert len(set(tables.cell.tolist())) == 100


@pytest.mark.parametrize(
    ("age", "index", "label"), [(0, 0, "0〜4歳"), (22, 4, "20〜24歳"), (101, 19, "95歳以上")]
)
def test_age_class(age: int, index: int, label: str) -> None:
    assert age_class(age) == index
    assert age_class_label(index) == label


def test_age_class_rejects_negative() -> None:
    with pytest.raises(ValueError, match="負"):
        age_class(-1)


def test_prior_splits_each_500m_mesh_evenly(tables: ScoringTables) -> None:
    young = prior(tables, 22)
    everyone = prior(tables, None)

    assert young.sum() == pytest.approx(25 + 50 + 75 + 100)
    assert everyone.sum() == pytest.approx(100 + 200 + 300 + 400)
    assert np.unique(young[tables.mesh == 0]).tolist() == [1.0]


def write_tables(directory: Path, built: ScoringTables) -> None:
    columns = {"mesh_500m": [str(i) for i in range(built.age.shape[0])], "total": built.total}
    for i in range(20):
        columns[f"age_{5 * i:02d}"] = built.age[:, i]
    pq.write_table(pa.table(columns), directory / "scoring_age_500m.parquet")
    towns = built.towns
    pq.write_table(
        pa.table(
            {
                "key_code": towns.key_code,
                "muni_code": towns.muni_code,
                "city": towns.city,
                "name": towns.name,
                "population": [1] * len(towns.name),
                "lat": towns.lat,
                "lon": towns.lon,
            }
        ),
        directory / "scoring_towns.parquet",
    )
    pq.write_table(
        pa.table(
            {
                name: getattr(built, name)
                for name in ("cell", "lat", "lon", "mesh", "town", "school", "station", "station_m")
            }
        ),
        directory / "scoring_cells.parquet",
    )
    for kind, places, group, walk in (
        ("stations", built.stations, "line_name", built.station_walk),
        ("bus_stops", built.bus_stops, "operator", built.bus_walk),
    ):
        pq.write_table(
            pa.table(
                {"name": places.name, group: places.group, "lat": places.lat, "lon": places.lon}
            ),
            directory / f"scoring_{kind}.parquet",
        )
        place = np.repeat(np.arange(len(places.name)), np.diff(walk.indptr))
        pq.write_table(
            pa.table(
                {"place": place.astype(np.int32), "cell": walk.cell, "distance": walk.distance}
            ),
            directory
            / f"scoring_{kind.replace('_stops', '').replace('stations', 'station')}_walk.parquet",
        )
    pq.write_table(
        pa.table(
            {
                "school_code": ["B1"],
                "name": built.school_name,
                "muni_code": ["13105"],
                "city": built.school_city,
            }
        ),
        directory / "scoring_schools.parquet",
    )


def test_load_reads_every_table(tmp_path: Path, tables: ScoringTables) -> None:
    write_tables(tmp_path, tables)

    loaded = scoring_tables.load(tmp_path)

    assert loaded is not None
    assert loaded.size == 100
    assert loaded.towns.name == tables.towns.name
    cells, distance = loaded.station_walk.of(0)
    expected_cells, expected_distance = tables.station_walk.of(0)
    assert sorted(cells.tolist()) == sorted(expected_cells.tolist())
    assert distance.max() == pytest.approx(expected_distance.max())
    assert loaded.cell_of(float(tables.lat[0]), float(tables.lon[0])) == 0
    assert loaded.cell_of(36.5, 140.5) is None


def test_load_returns_none_when_a_table_is_missing(tmp_path: Path, tables: ScoringTables) -> None:
    write_tables(tmp_path, tables)
    (tmp_path / "scoring_bus_walk.parquet").unlink()
    assert scoring_tables.load(tmp_path) is None


def test_load_returns_none_when_a_table_is_broken(tmp_path: Path, tables: ScoringTables) -> None:
    write_tables(tmp_path, tables)
    (tmp_path / "scoring_cells.parquet").write_bytes(b"broken")
    assert scoring_tables.load(tmp_path) is None


@pytest.mark.skipif(
    not (PROCESSED / "scoring_cells.parquet").is_file(), reason="make data の表がない（CI）"
)
def test_prior_of_20_to_24_matches_the_census_mesh_total() -> None:
    loaded = scoring_tables.load(PROCESSED)
    assert loaded is not None
    census = pq.read_table(PROCESSED / "scoring_age_500m.parquet").column("age_20").to_numpy()

    # 1都3県（1都3県の 1km メッシュにかかる 500m メッシュ）の20〜24歳の合計。
    # 令和2年国勢調査 地域メッシュ統計（T001192）の秘匿されていない行の和（1,971,515 人）と一致する
    assert prior(loaded, 22).sum() == pytest.approx(float(census.sum()), rel=1e-6)
    assert prior(loaded, 22).sum() == pytest.approx(1_971_515, abs=1)


def test_load_reads_shelter_points_when_the_table_exists(
    tmp_path: Path, tables: ScoringTables
) -> None:
    write_tables(tmp_path, tables)
    assert scoring_tables.load(tmp_path).shelters == []  # type: ignore[union-attr]
    pq.write_table(
        pa.table(
            {"name": ["東京大学"], "kind": ["指定緊急避難場所"], "lat": [35.7], "lon": [139.7]}
        ),
        tmp_path / "shelters.parquet",
    )

    loaded = scoring_tables.load(tmp_path)

    assert loaded is not None
    assert loaded.shelters == [scoring_tables.Shelter("東京大学", 35.7, 139.7)]
