"""住まいの推定：層を掛け合わせた確率の地図、8割の範囲、投稿ごとの影響、層8。

点数(マス) ＝ 層0(マス) × 層1(マス) × … を合計 1 に割り戻したものを、
そのマスに住んでいる確率とみなす。
層7（よく行く場所）は参考の層なので、本計算（main）には掛けず、掛けた結果（with_geoprofile）を並べる。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import CollectionArea
from tkb_engine.scoring.constants import (
    COVERAGE,
    DAYS_PER_YEAR,
    WALK_METERS_PER_MINUTE,
    YEARS_PER_AGE_CLASS,
)
from tkb_engine.scoring.geoprofile import Geoprofile, geoprofile, place_signals, resolve
from tkb_engine.scoring.layers import line_names, weights_for
from tkb_engine.scoring.prior import age_class, age_class_label, prior
from tkb_engine.scoring.signals import (
    Signal,
    SignalKind,
    photo_town_signals,
    text_signals,
)
from tkb_engine.scoring.tables import ScoringTables

Weights = npt.NDArray[np.float64]
LOCATION_KINDS = frozenset(
    {
        SignalKind.WALK_MINUTES,
        SignalKind.LINE,
        SignalKind.BUS_STOP,
        SignalKind.SHELTER,
        SignalKind.TOWN,
        SignalKind.COLLECTION,
    }
)


@dataclass(frozen=True)
class Region:
    """8割の範囲。people は範囲に住む（年齢がわかればその5歳階級の）人数。"""

    people: float
    cells: int
    top_cell: int
    same_birthday: float | None  # 層8：同じ年齢・同じ誕生日の計算上の人数（目安）


@dataclass(frozen=True)
class Evidence:
    """推定に使った材料（Signal）と、重みが決まったか（applied）。"""

    signal: Signal
    applied: bool


@dataclass(frozen=True)
class Estimate:
    probability: Weights  # main（層7を掛けない）
    region: Region
    with_geoprofile: tuple[Weights, Region] | None
    geoprofile: Geoprofile | None
    evidence: list[Evidence]
    age: int | None
    birthday: str | None
    # 投稿ごと：その投稿を外したときの 8割の範囲（main）
    without: dict[str, Region] = field(default_factory=dict)
    # 投稿を1件ずつ重ねたとき（投稿の時刻の順）：(投稿 ID, 8割の範囲)。最初は投稿なし（None）
    steps: list[tuple[str | None, Region]] = field(default_factory=list)


def collect_signals(
    posts: Sequence[Post], clues: Sequence[Clue], tables: ScoringTables
) -> list[Signal]:
    """投稿ごとのシグナル。clues の番号は、渡された clues の並びでの番号。"""
    lines = line_names(tables)
    stops = sorted(set(tables.bus_stops.name))
    towns = tables.towns.name
    stations = sorted(set(tables.stations.name))
    shelters = sorted({s.name for s in tables.shelters})
    found: list[Signal] = []
    for post in posts:
        found.extend(text_signals(post, lines, stops))
        found.extend(photo_town_signals(post, clues, list(range(len(clues))), towns))
        found.extend(place_signals(post, stations, shelters))
    return found


def estimate(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    tables: ScoringTables,
    areas: Sequence[CollectionArea],
) -> Estimate | None:
    """住まいの推定。場所のシグナル（層1〜7）が1つもなければ None。"""
    signals = collect_signals(posts, clues, tables)
    if not any(s.kind in LOCATION_KINDS or s.kind == SignalKind.PLACE for s in signals):
        return None
    cache: dict[tuple[SignalKind, str], Weights | None] = {}

    def weights(s: Signal) -> Weights | None:
        key = (s.kind, s.value)
        if key not in cache:
            cache[key] = weights_for(tables, s, tables.shelters, areas)
        return cache[key]

    def run(subset: Sequence[Signal]) -> tuple[Weights, Region, int | None]:
        age = _first_int(subset, SignalKind.AGE)
        birthday = _first(subset, SignalKind.BIRTHDAY)
        base = prior(tables, age)
        score = base.copy()
        for s in subset:
            if s.kind in LOCATION_KINDS and (w := weights(s)) is not None:
                score *= w
        probability = _normalized(score)
        return probability, _region(tables, probability, base, age, birthday), age

    probability, region, age = run(signals)
    geo = geoprofile(tables, resolve(signals, tables, tables.shelters))
    with_geo = None
    if geo is not None:
        p7 = _normalized(probability * geo.weights)
        with_geo = (
            p7,
            _region(tables, p7, prior(tables, age), age, _first(signals, SignalKind.BIRTHDAY)),
        )
    post_ids = list(dict.fromkeys(s.post_id for s in signals))
    without = {pid: run([s for s in signals if s.post_id != pid])[1] for pid in post_ids}
    order = sorted((p for p in posts if p.post_id in set(post_ids)), key=lambda p: p.created_at)
    steps: list[tuple[str | None, Region]] = [(None, run([])[1])]
    included: set[str] = set()
    for post in order:
        included.add(post.post_id)
        steps.append((post.post_id, run([s for s in signals if s.post_id in included])[1]))
    return Estimate(
        probability=probability,
        region=region,
        with_geoprofile=with_geo,
        geoprofile=geo,
        evidence=[
            Evidence(s, s.kind not in LOCATION_KINDS or weights(s) is not None) for s in signals
        ],
        age=age,
        birthday=_first(signals, SignalKind.BIRTHDAY),
        without=without,
        steps=steps,
    )


def _first(signals: Sequence[Signal], kind: SignalKind) -> str | None:
    return next((s.value for s in signals if s.kind == kind), None)


def _first_int(signals: Sequence[Signal], kind: SignalKind) -> int | None:
    value = _first(signals, kind)
    return int(value) if value is not None else None


def _normalized(score: Weights) -> Weights:
    total = float(score.sum())
    result: Weights = score / total if total > 0 else score
    return result


def coverage_cells(probability: Weights) -> npt.NDArray[np.int64]:
    """確率の高い順に足して COVERAGE に届くまでのマス（届いたマスを含む）。"""
    order = np.argsort(-probability, kind="stable")
    cumulative = np.cumsum(probability[order])
    count = int(np.searchsorted(cumulative, COVERAGE, side="left")) + 1
    result: npt.NDArray[np.int64] = order[: min(count, order.shape[0])]
    return result


def _region(
    tables: ScoringTables,
    probability: Weights,
    base: Weights,
    age: int | None,
    birthday: str | None,
) -> Region:
    cells = coverage_cells(probability)
    people = float(base[cells].sum())
    same_birthday = None
    if age is not None and birthday is not None:
        same_birthday = people / YEARS_PER_AGE_CLASS / DAYS_PER_YEAR
    return Region(
        people=people,
        cells=int(cells.shape[0]),
        top_cell=int(cells[0]),
        same_birthday=same_birthday,
    )


def rank_percent(probability: Weights, cell: int) -> tuple[int, float]:
    """そのマスの順位（確率の高い順、同じ確率なら上の順位）と、上位何%か。"""
    rank = int((probability > probability[cell]).sum()) + 1
    return rank, 100.0 * rank / probability.shape[0]


def describe_cell(tables: ScoringTables, cell: int) -> dict[str, object]:
    """マスの市区町村・町丁目・道のりで一番近い駅（画面の「一番濃いのはここ」）。"""
    town = int(tables.town[cell])
    station = int(tables.station[cell])
    meters = float(tables.station_m[cell])
    return {
        "city": tables.towns.city[town] if town >= 0 else None,
        "town": tables.towns.name[town] if town >= 0 else None,
        "station": tables.stations.name[station] if station >= 0 else None,
        "station_walk_minutes": (
            int(np.ceil(meters / WALK_METERS_PER_MINUTE)) if station >= 0 else None
        ),
    }


def age_label(age: int | None) -> str | None:
    return None if age is None else age_class_label(age_class(age))
