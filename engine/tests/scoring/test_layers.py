from dataclasses import replace

import numpy as np
import pytest

from tkb_engine.gazetteer import CollectionArea
from tkb_engine.scoring import layers
from tkb_engine.scoring.constants import OUTSIDE_WEIGHT
from tkb_engine.scoring.signals import Signal, SignalKind
from tkb_engine.scoring.tables import ScoringTables, Shelter


def test_walk_minutes_uses_the_80m_per_minute_rule(tables: ScoringTables) -> None:
    # 「徒歩4分」は 240m を超え 320m 以下。250m のマスは 1、330m のマスは 0.01
    distances = np.full(tables.size, np.nan, dtype=np.float32)
    distances[:3] = [250.0, 330.0, 240.0]
    weights = layers.walk_minutes(replace(tables, station_m=distances), 4)

    assert weights[0] == 1.0
    assert weights[1] == OUTSIDE_WEIGHT
    assert weights[2] == OUTSIDE_WEIGHT  # 240m はちょうど3分
    assert weights[3] == OUTSIDE_WEIGHT  # 2,400m 以内に駅がないマス


def test_line_marks_cells_within_800m_of_any_station_of_the_line(tables: ScoringTables) -> None:
    assert layers.line_names(tables) == {"千代田線", "南北線"}
    weights = layers.line(tables, "千代田線")

    assert weights is not None
    cells, _ = tables.station_walk.of(0)
    assert set(np.flatnonzero(weights == 1.0).tolist()) == set(cells.tolist())
    assert 0 < len(cells) < tables.size
    assert layers.line(tables, "山手線") is None


def test_bus_stop_marks_cells_within_300m(tables: ScoringTables) -> None:
    weights = layers.bus_stop(tables, "弥生二丁目")

    assert weights is not None
    inside = np.flatnonzero(weights == 1.0)
    assert 0 < inside.shape[0] < tables.size
    assert layers.bus_stop(tables, "根津駅前") is None


def test_shelter_uses_the_school_district_when_it_is_a_school(tables: ScoringTables) -> None:
    weights = layers.shelter(tables, "根津小学校", [])

    assert weights is not None
    assert set(weights[tables.school == 0].tolist()) == {1.0}
    assert set(weights[tables.school == -1].tolist()) == {OUTSIDE_WEIGHT}


def test_shelter_decays_with_distance_from_shelters_of_the_same_name(
    tables: ScoringTables,
) -> None:
    point = Shelter("東京大学", float(tables.lat[0]), float(tables.lon[0]))
    weights = layers.shelter(tables, "東京大学", [point, Shelter("別の施設", 0.0, 0.0)])

    assert weights is not None
    assert weights[0] == pytest.approx(1.0)
    far = int(np.argmax(weights < 1.0))
    assert 0 < weights[far] < 1.0
    assert layers.shelter(tables, "どこにもない施設", [point]) is None


def test_town_marks_every_town_whose_name_contains_the_fragment(tables: ScoringTables) -> None:
    # 「弥生」は文京区弥生二丁目と中野区弥生町一丁目の両方に当てはまる
    weights = layers.town(tables, "弥生")

    assert weights is not None
    assert set(weights[tables.town == 0].tolist()) == {1.0}
    assert set(weights[tables.town == 2].tolist()) == {1.0}
    assert set(weights[tables.town == 1].tolist()) == {OUTSIDE_WEIGHT}
    assert layers.town(tables, "銀座") is None


BUNKYO = [
    CollectionArea("文京区", "弥生1・2丁目", "月木", ["弥生1・2丁目"]),
    CollectionArea("文京区", "根津1・2丁目", "水土", ["根津1・2丁目"]),
]


def test_collection_keeps_cities_without_data(tables: ScoringTables) -> None:
    weights = layers.collection(tables, "月木", BUNKYO)

    assert weights is not None
    assert set(weights[tables.town == 0].tolist()) == {1.0}  # 文京区弥生二丁目：月木
    assert set(weights[tables.town == 1].tolist()) == {OUTSIDE_WEIGHT}  # 根津一丁目：水土
    assert set(weights[tables.town == 2].tolist()) == {1.0}  # 中野区：データがない


def test_collection_keeps_towns_that_no_area_covers(tables: ScoringTables) -> None:
    weights = layers.collection(tables, "月木", BUNKYO[:1])

    assert weights is not None
    assert set(weights[tables.town == 1].tolist()) == {1.0}
    assert layers.collection(tables, "月木", []) is None


@pytest.mark.parametrize(
    ("area", "census", "covered"),
    [
        ("弥生1・2丁目", "弥生二丁目", True),
        ("千駄木3～5丁目", "千駄木四丁目", True),
        ("千駄木3～5丁目", "千駄木二丁目", False),
        ("小石川1丁目1～16番", "小石川一丁目", True),
        ("根津", "根津一丁目", True),
        ("本郷1・2丁目", "湯島二丁目", False),
        ("西片", "西片", True),
        ("本郷12丁目", "本郷十二丁目", True),
    ],
)
def test_area_town_names_cover_census_town_names(area: str, census: str, covered: bool) -> None:
    assert layers._covers(area, census) is covered


def test_weights_for_dispatches_by_signal_kind(tables: ScoringTables) -> None:
    def signal(kind: SignalKind, value: str) -> Signal:
        return Signal(kind, "p", value, "")

    assert layers.weights_for(tables, signal(SignalKind.WALK_MINUTES, "4"), [], []) is not None
    assert layers.weights_for(tables, signal(SignalKind.LINE, "南北線"), [], []) is not None
    assert layers.weights_for(tables, signal(SignalKind.BUS_STOP, "弥生二丁目"), [], []) is not None
    assert layers.weights_for(tables, signal(SignalKind.SHELTER, "根津小学校"), [], []) is not None
    assert layers.weights_for(tables, signal(SignalKind.TOWN, "弥生"), [], []) is not None
    assert layers.weights_for(tables, signal(SignalKind.COLLECTION, "月木"), [], BUNKYO) is not None
    assert layers.weights_for(tables, signal(SignalKind.AGE, "22"), [], []) is None
