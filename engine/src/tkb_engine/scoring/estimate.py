"""住まいの推定：層を掛け合わせた確率の地図、8割の範囲、投稿ごとの影響、層8。

点数(マス) ＝ 層0(マス) × 層1(マス) × … を合計 1 に割り戻したものを、
そのマスに住んでいる確率とみなす。
層7（よく行く場所）は参考の層なので、本計算（main）には掛けず、掛けた結果（with_geoprofile）を並べる。
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from tkb_common.residence import ResidenceLocalizationStatus
from tkb_common.schemas import (
    Clue,
    Post,
    ProfileAttribute,
    ProfileCandidateSet,
    ProfileCandidateSetStatus,
    ProfileStatus,
)
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
    sentences,
    text_signals,
    text_town_signals,
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
    localization_status: ResidenceLocalizationStatus
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
        found.extend(_new(text_town_signals(post, towns), found))
        found.extend(place_signals(post, stations, shelters))
    return found


def estimate(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    tables: ScoringTables,
    areas: Sequence[CollectionArea],
    profile_claims: Sequence[ProfileCandidateSet] = (),
) -> Estimate | None:
    """住まいの点数を計算し、traceableな profile 地理候補がなければ位置を隠す。"""
    signals = collect_signals(posts, clues, tables)
    cache: dict[tuple[SignalKind, str], Weights | None] = {}
    profile_support, profile_conflicts = _profile_supports(profile_claims, tables)
    has_geographic_claim = any(
        candidate_set.attribute
        in {ProfileAttribute.HOME_NEAREST_STATION, ProfileAttribute.RESIDENTIAL_AREA}
        and (candidate_set.candidates or candidate_set.status is ProfileCandidateSetStatus.CONFLICT)
        for candidate_set in profile_claims
    )
    if (
        not any(s.kind in LOCATION_KINDS or s.kind == SignalKind.PLACE for s in signals)
        and not profile_support
        and not profile_conflicts
        and not has_geographic_claim
    ):
        return None

    def weights(s: Signal) -> Weights | None:
        key = (s.kind, s.value)
        if key not in cache:
            cache[key] = weights_for(tables, s, tables.shelters, areas)
        return cache[key]

    def run(
        subset: Sequence[Signal], included_post_ids: set[str]
    ) -> tuple[Weights, Region, int | None]:
        age = _first_int(subset, SignalKind.AGE)
        birthday = _first(subset, SignalKind.BIRTHDAY)
        base = prior(tables, age)
        score = base.copy()
        support_mask, _ = _active_profile_mask(profile_support, included_post_ids)
        for s in subset:
            if s.kind not in LOCATION_KINDS or (w := weights(s)) is None:
                continue
            score *= w
        if support_mask is not None:
            score = np.where(support_mask, score, 0.0)
        probability = _normalized(score)
        return probability, _region(tables, probability, base, age, birthday), age

    all_post_ids = {post.post_id for post in posts}
    probability, region, age = run(signals, all_post_ids)
    final_profile_mask, profile_conflict = _active_profile_mask(profile_support, all_post_ids)
    explicit_profile_conflict = any(
        conflict.required_post_ids <= all_post_ids for conflict in profile_conflicts
    )
    owner_town_conflict = _has_independent_home_town_conflict(
        signals, posts, profile_support, all_post_ids, tables
    )
    localization_status: ResidenceLocalizationStatus = (
        "conflict"
        if profile_conflict or explicit_profile_conflict or owner_town_conflict
        else "supported"
        if final_profile_mask is not None and probability.sum() > 0
        else "insufficient"
    )
    geo = geoprofile(tables, resolve(signals, tables, tables.shelters))
    with_geo = None
    if geo is not None:
        p7 = _normalized(probability * geo.weights)
        with_geo = (
            p7,
            _region(tables, p7, prior(tables, age), age, _first(signals, SignalKind.BIRTHDAY)),
        )
    contributing_post_ids = {signal.post_id for signal in signals}
    contributing_post_ids.update(
        post_id for support in profile_support for post_id in support.required_post_ids
    )
    contributing_post_ids.update(
        post_id for conflict in profile_conflicts for post_id in conflict.required_post_ids
    )
    post_ids = [post.post_id for post in posts if post.post_id in contributing_post_ids]
    without = {
        pid: run([s for s in signals if s.post_id != pid], all_post_ids - {pid})[1]
        for pid in post_ids
    }
    order = sorted((p for p in posts if p.post_id in set(post_ids)), key=lambda p: p.created_at)
    steps: list[tuple[str | None, Region]] = [(None, run([], set())[1])]
    included: set[str] = set()
    for post in order:
        included.add(post.post_id)
        steps.append(
            (
                post.post_id,
                run([s for s in signals if s.post_id in included], included)[1],
            )
        )
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
        localization_status=localization_status,
        without=without,
        steps=steps,
    )


@dataclass(frozen=True)
class _ProfileSupport:
    attribute: ProfileAttribute
    value: str
    mask: npt.NDArray[np.bool_]
    required_post_ids: frozenset[str]
    specific: bool


@dataclass(frozen=True)
class _ProfileConflict:
    required_post_ids: frozenset[str]


def _profile_supports(
    candidate_sets: Sequence[ProfileCandidateSet], tables: ScoringTables
) -> tuple[list[_ProfileSupport], list[_ProfileConflict]]:
    """Resolve grounded home candidates once; per-step runs only check path dependencies."""
    supports: list[_ProfileSupport] = []
    conflicts: list[_ProfileConflict] = []
    mask_cache: dict[tuple[ProfileAttribute, str], tuple[npt.NDArray[np.bool_], bool] | None] = {}
    for candidate_set in candidate_sets:
        if candidate_set.attribute not in {
            ProfileAttribute.HOME_NEAREST_STATION,
            ProfileAttribute.RESIDENTIAL_AREA,
        }:
            continue
        if candidate_set.status is ProfileCandidateSetStatus.CONFLICT:
            required = frozenset(
                evidence.post_id
                for evidence in candidate_set.conflicting_evidence
                if evidence.required and evidence.post_id is not None
            )
            if required:
                conflicts.append(_ProfileConflict(required))
        for candidate in candidate_set.candidates:
            if candidate.status is not ProfileStatus.FOUND:
                continue
            key = (candidate_set.attribute, candidate.value)
            if key not in mask_cache:
                mask_cache[key] = _candidate_mask(*key, tables)
            resolved = mask_cache[key]
            if resolved is None:
                continue
            mask, specific = resolved
            for path in candidate.evidence_paths:
                required = frozenset(
                    evidence.post_id
                    for evidence in path.evidence
                    if evidence.required and evidence.post_id is not None
                )
                # A geography constraint must be traceable to at least one owner post.
                if required:
                    supports.append(
                        _ProfileSupport(
                            *key,
                            mask,
                            required,
                            specific,
                        )
                    )
    return supports, conflicts


def _candidate_mask(
    attribute: ProfileAttribute, value: str, tables: ScoringTables
) -> tuple[npt.NDArray[np.bool_], bool] | None:
    normalized_value = "".join(unicodedata.normalize("NFKC", value).casefold().split())
    if attribute is ProfileAttribute.HOME_NEAREST_STATION:
        station_value = normalized_value.removesuffix("駅")
        ids = [
            index
            for index, name in enumerate(tables.stations.name)
            if "".join(unicodedata.normalize("NFKC", name).casefold().split()).removesuffix("駅")
            == station_value
        ]
        if ids:
            points = list(
                {(float(tables.stations.lat[i]), float(tables.stations.lon[i])) for i in ids}
            )
            if _point_spread_m(points) > 1_000:
                return None
            mask = np.isin(tables.station, ids) & (tables.station_m <= 3_000)
            return (mask, True) if mask.any() else None
        return None

    town_ids: list[int] = []
    for index, (city, town) in enumerate(zip(tables.towns.city, tables.towns.name, strict=True)):
        city_norm = "".join(unicodedata.normalize("NFKC", city).casefold().split())
        town_norm = "".join(unicodedata.normalize("NFKC", town).casefold().split())
        base_town = re.sub(r"(?:[〇零一二三四五六七八九十百]+|[0-9]+)丁目$", "", town_norm)
        if normalized_value == city_norm or normalized_value in {
            town_norm,
            f"{city_norm}{town_norm}",
            base_town,
            f"{city_norm}{base_town}",
        }:
            town_ids.append(index)
    if town_ids:
        matched_towns = {tables.towns.name[index] for index in town_ids}
        exact_town = any(
            normalized_value
            == "".join(unicodedata.normalize("NFKC", tables.towns.name[index]).casefold().split())
            or normalized_value
            == "".join(
                unicodedata.normalize("NFKC", tables.towns.city[index] + tables.towns.name[index])
                .casefold()
                .split()
            )
            for index in town_ids
        )
        cities = {tables.towns.city[index] for index in town_ids}
        mask = np.isin(tables.town, town_ids)
        if not mask.any():
            return None
        city_value = any(
            normalized_value == "".join(unicodedata.normalize("NFKC", city).casefold().split())
            for city in cities
        )
        return mask, exact_town and not city_value and len(matched_towns) == 1 and len(cities) == 1
    return None


def _point_spread_m(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return max(
        (
            abs(a[0] - b[0]) * 111_000
            + abs(a[1] - b[1]) * 111_000 * np.cos(np.radians((a[0] + b[0]) / 2))
            for i, a in enumerate(points)
            for b in points[i + 1 :]
        ),
        default=0.0,
    )


def _active_profile_mask(
    supports: Sequence[_ProfileSupport], included_post_ids: set[str]
) -> tuple[npt.NDArray[np.bool_] | None, bool]:
    by_attribute: dict[ProfileAttribute, dict[str, list[_ProfileSupport]]] = {}
    for support in supports:
        if support.required_post_ids <= included_post_ids:
            by_attribute.setdefault(support.attribute, {}).setdefault(support.value, []).append(
                support
            )
    # A broad municipality or multiply-matched town may disambiguate an exact station,
    # but cannot authorize a localized map on its own.
    station_groups = by_attribute.get(ProfileAttribute.HOME_NEAREST_STATION, {})
    area_groups = by_attribute.get(ProfileAttribute.RESIDENTIAL_AREA, {})

    def group_mask(values: list[_ProfileSupport]) -> npt.NDArray[np.bool_]:
        mask = values[0].mask.copy()
        for support in values[1:]:
            mask |= support.mask
        return mask

    if not station_groups:
        viable = {
            value: group_mask(values)
            for value, values in area_groups.items()
            if all(support.specific for support in values)
        }
        if len(viable) != 1:
            return None, False
        return next(iter(viable.values())), False
    if not area_groups:
        if len(station_groups) != 1:
            return None, False
        return group_mask(next(iter(station_groups.values()))), False

    pairs = [
        (station_value, area_value, group_mask(station_paths) & group_mask(area_paths))
        for station_value, station_paths in station_groups.items()
        for area_value, area_paths in area_groups.items()
    ]
    viable_pairs = [pair for pair in pairs if pair[2].any()]
    if not viable_pairs:
        return None, True
    # Broad or ambiguous values are safe only when independent geography leaves one pair.
    if len(viable_pairs) != 1:
        return None, False
    return viable_pairs[0][2], False


def _has_independent_home_town_conflict(
    signals: Sequence[Signal],
    posts: Sequence[Post],
    supports: Sequence[_ProfileSupport],
    included_post_ids: set[str],
    tables: ScoringTables,
) -> bool:
    """Only a separate, explicit owner-home town statement can contradict profile masks."""
    owner_home = re.compile(
        r"(?:私|自分|僕|俺)(?:の)?(?:自宅|家|うち)(?:の近く|近所)?|(?:自宅|うち)(?:の近く|近所)"
    )
    posts_by_id = {post.post_id: post for post in posts}
    profile_mask, conflict = _active_profile_mask(supports, included_post_ids)
    if conflict or profile_mask is None:
        return False
    for signal in signals:
        if signal.kind is not SignalKind.TOWN or signal.clue_indices:
            continue
        post = posts_by_id.get(signal.post_id)
        if post is None:
            continue
        matching_sentence = next(
            (
                sentence
                for sentence in sentences(post.text)
                if signal.value in sentence and owner_home.search(sentence)
            ),
            None,
        )
        if matching_sentence is None:
            continue
        if any(
            signal.post_id not in support.required_post_ids
            and support.required_post_ids <= included_post_ids
            for support in supports
        ):
            town_weights = weights_for(
                tables,
                signal,
                tables.shelters,
                (),
            )
            if town_weights is None:
                continue
            town_cells = (town_weights >= 1.0) & (tables.town >= 0)
            if len(set(tables.town[town_cells].tolist())) != 1:
                continue
            if not np.any(town_cells & profile_mask):
                return True
    return False


def _new(candidates: Sequence[Signal], found: Sequence[Signal]) -> list[Signal]:
    """同じ投稿の同じ町名（写真と本文の両方で読めたもの）は1回だけ数える。"""
    seen = {(s.post_id, s.kind, s.value) for s in found}
    return [s for s in candidates if (s.post_id, s.kind, s.value) not in seen]


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
    valid_town = 0 <= town < len(tables.towns.name)
    valid_station = 0 <= station < len(tables.stations.name)
    return {
        "city": tables.towns.city[town] if valid_town else None,
        "town": tables.towns.name[town] if valid_town else None,
        "station": tables.stations.name[station] if valid_station else None,
        "station_walk_minutes": (
            int(np.ceil(meters / WALK_METERS_PER_MINUTE)) if valid_station else None
        ),
    }


def age_label(age: int | None) -> str | None:
    return None if age is None else age_class_label(age_class(age))
