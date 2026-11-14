import numpy as np
import pytest

from tkb_common.schemas import Post
from tkb_engine.scoring.geoprofile import (
    OTHER_BASE_MIN_M,
    Place,
    geoprofile,
    place_signals,
    resolve,
    split_other_bases,
)
from tkb_engine.scoring.signals import SignalKind
from tkb_engine.scoring.tables import ScoringTables, Shelter

STATIONS = ["根津", "東大前", "千駄木", "湯島", "運河"]
SHELTERS = ["東京大学", "根津小学校"]


def post(text: str) -> Post:
    return Post(
        post_id="at://did:plc:x/app.bsky.feed.post/1",
        text=text,
        created_at="2026-11-01T08:00:00+09:00",
        images=[],
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("東大の構内、散歩コースにちょうどいい", ["東京大学"]),
        ("千駄木の古本屋めぐりが休日の楽しみ", ["千駄木"]),
        ("湯島駅のそばのラーメン屋、また行列", ["湯島"]),
        ("研究室で徹夜。運河駅の始発で帰る", ["運河"]),
        ("東大前駅によく行く", ["東大前"]),
        ("千駄木のニュースを見た", []),  # よく行く話ではない
        ("千駄木の会社に見学で行った", []),  # 訪問
    ],
)
def test_place_signals(text: str, expected: list[str]) -> None:
    found = place_signals(post(text), STATIONS, SHELTERS)
    assert [s.value for s in found] == expected
    assert all(s.kind == SignalKind.PLACE for s in found)


def place(name: str, lat: float, lon: float) -> Place:
    return Place(name, lat, lon, ("p",))


TODAI = place("東京大学", 35.7120, 139.7627)
SENDAGI = place("千駄木", 35.7253, 139.7632)
YUSHIMA = place("湯島", 35.7078, 139.7704)
UNGA = place("運河", 35.9150, 139.9060)


def test_split_other_bases_drops_a_far_place() -> None:
    kept, other = split_other_bases([TODAI, SENDAGI, YUSHIMA, UNGA])
    assert [p.name for p in kept] == ["東京大学", "千駄木", "湯島"]
    assert [p.name for p in other] == ["運河"]


def test_split_other_bases_needs_three_places() -> None:
    assert split_other_bases([TODAI, UNGA]) == ([TODAI, UNGA], [])


def test_split_other_bases_keeps_places_within_the_minimum_distance() -> None:
    near = place("近い", 35.7253 + 3_000 / 110_950, 139.7632)
    assert OTHER_BASE_MIN_M > 3_000
    assert split_other_bases([TODAI, SENDAGI, YUSHIMA, near])[1] == []


def test_resolve_uses_station_and_shelter_points(tables: ScoringTables) -> None:
    signals = place_signals(post("根津駅によく行く。東大を散歩"), ["根津"], ["東京大学"])
    places = resolve(signals, tables, [Shelter("東京大学", 35.712, 139.7627)])

    assert [p.name for p in places] == ["根津", "東京大学"]
    assert places[0].lat == pytest.approx(float(tables.stations.lat[0]))


def test_resolve_skips_names_found_in_far_apart_places(tables: ScoringTables) -> None:
    signals = place_signals(post("東大を散歩"), [], ["東京大学"])
    far = [Shelter("東京大学", 35.712, 139.7627), Shelter("東京大学", 35.66, 139.68)]
    assert resolve(signals, tables, far) == []


def test_geoprofile_peaks_near_the_places_and_needs_two(tables: ScoringTables) -> None:
    a = place("西", float(tables.lat[0]), float(tables.lon[0]))
    b = place("東", float(tables.lat[4]), float(tables.lon[4]))

    profile = geoprofile(tables, [a, b])

    assert profile is not None
    assert profile.weights.max() == pytest.approx(1.0)
    assert profile.buffer_m > 0
    far = int(np.argmax(tables.lat))
    assert profile.weights[far] < profile.weights[2]
    assert geoprofile(tables, [a]) is None
