"""層1〜6：シグナルごとに、マスに掛ける重み（当てはまれば 1、当てはまらなければ 0.01）。

設計：inference-model-spec.md 2章。数字は constants.py にまとめてある。
重みが決められないシグナル（駅の表にない路線など）は None を返し、掛けない。
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from tkb_engine.gazetteer import CollectionArea
from tkb_engine.scoring.constants import (
    BUS_STOP_WALK_M,
    OUTSIDE_WEIGHT,
    SHELTER_MEAN_DISTANCE_M,
    STATION_WALK_M,
    WALK_METERS_PER_MINUTE,
)
from tkb_engine.scoring.signals import Signal, SignalKind
from tkb_engine.scoring.tables import ScoringTables, Walk

Weights = npt.NDArray[np.float64]
LINE_PREFIX = re.compile(r"^\d+号線")
LINE_NAME_MIN = 3
EARTH_RADIUS_M = 6_371_008.8
KANJI_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CENSUS_CHOME = re.compile(r"^(.+?)([一二三四五六七八九十]+)丁目$")
AREA_CHOME = re.compile(r"^(.+?)(\d+(?:[・～~\-]\d+)*)丁目")


@dataclass(frozen=True)
class Shelter:
    name: str
    lat: float
    lon: float


def short_line_name(line_name: str) -> str:
    """「9号線千代田線」→「千代田線」。"""
    return LINE_PREFIX.sub("", line_name)


def line_names(tables: ScoringTables) -> set[str]:
    return {
        name
        for name in (short_line_name(g) for g in tables.stations.group)
        if len(name) >= LINE_NAME_MIN and name.endswith("線")
    }


def binary(tables: ScoringTables, inside: npt.NDArray[np.bool_]) -> Weights:
    return np.where(inside, 1.0, OUTSIDE_WEIGHT)


def walk_minutes(tables: ScoringTables, minutes: int) -> Weights:
    """層1：一番近い駅までの道のり d が 80×(N−1) < d ≦ 80×N のマス。"""
    low = WALK_METERS_PER_MINUTE * (minutes - 1)
    high = WALK_METERS_PER_MINUTE * minutes
    d = tables.station_m
    inside = np.isfinite(d) & (d > low) & (d <= high)
    return binary(tables, inside)


def line(tables: ScoringTables, name: str) -> Weights | None:
    """層2：その路線のどれかの駅から道のり 800m 以内のマス。"""
    places = [i for i, g in enumerate(tables.stations.group) if short_line_name(g) == name]
    if not places:
        return None
    return binary(tables, _within(tables, tables.station_walk, places, STATION_WALK_M))


def bus_stop(tables: ScoringTables, name: str) -> Weights | None:
    """層3：同じ名前のバス停のどれかから道のり 300m 以内のマス。"""
    places = [i for i, n in enumerate(tables.bus_stops.name) if n == name]
    if not places:
        return None
    return binary(tables, _within(tables, tables.bus_walk, places, BUS_STOP_WALK_M))


def _within(
    tables: ScoringTables, walk: Walk, places: Sequence[int], limit: float
) -> npt.NDArray[np.bool_]:
    inside = np.zeros(tables.size, dtype=bool)
    for place in places:
        cells, distance = walk.of(place)
        inside[cells[distance <= limit]] = True
    return inside


def shelter(tables: ScoringTables, name: str, shelters: Sequence[Shelter]) -> Weights | None:
    """層4：小学校で学区があれば学区の中、なければ同じ名前の避難所からの距離 d で exp(−d/554)。"""
    schools = [i for i, n in enumerate(tables.school_name) if n == name]
    if schools:
        return binary(tables, np.isin(tables.school, schools))
    points = [s for s in shelters if s.name == name]
    if not points:
        return None
    nearest = np.min(
        np.stack([_haversine(tables, s.lat, s.lon) for s in points]),
        axis=0,
    )
    result: Weights = np.exp(-nearest / SHELTER_MEAN_DISTANCE_M)
    return result


def _haversine(tables: ScoringTables, lat: float, lon: float) -> Weights:
    p1 = np.radians(tables.lat.astype(np.float64))
    p2 = math.radians(lat)
    dp = p2 - p1
    dl = math.radians(lon) - np.radians(tables.lon.astype(np.float64))
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dl / 2) ** 2
    result: Weights = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(h))
    return result


def town(tables: ScoringTables, fragment: str) -> Weights | None:
    """層5：名前にその文字を含む町丁目の区域の中のマス。"""
    towns = [i for i, n in enumerate(tables.towns.name) if fragment in n]
    if not towns:
        return None
    return binary(tables, np.isin(tables.town, towns))


def collection(tables: ScoringTables, days: str, areas: Sequence[CollectionArea]) -> Weights | None:
    """層6：燃やすごみの曜日が合う収集地区（町丁目）の区域の中。

    データのない市区町村と、データのある市区町村でもどの地区にも当てはまらない町丁目は消さない（1）。
    """
    stated = set(days)
    known = [a for a in areas if a.burnable_days]
    if not known or not stated:
        return None
    town_weight = np.ones(len(tables.towns.name), dtype=np.float64)
    for i, (city, name) in enumerate(zip(tables.towns.city, tables.towns.name, strict=True)):
        matched = [a for a in known if a.city == city and any(_covers(t, name) for t in a.towns)]
        if matched and not any(stated <= set(a.burnable_days) for a in matched):
            town_weight[i] = OUTSIDE_WEIGHT
    weights: Weights = np.where(tables.town >= 0, town_weight[tables.town], 1.0)
    return weights


def _covers(area_town: str, census_name: str) -> bool:
    """知識表の町名（「弥生1・2丁目」「千駄木3～5丁目」「小石川1丁目1～16番」）が、
    国勢調査の町丁目（「弥生二丁目」）を含むか。"""
    census = CENSUS_CHOME.match(census_name)
    area = AREA_CHOME.match(area_town)
    if area is None:
        base = census.group(1) if census else census_name
        return area_town in (census_name, base)
    if census is None or census.group(1) != area.group(1):
        return False
    return _kanji_number(census.group(2)) in _numbers(area.group(2))


def _numbers(spec: str) -> set[int]:
    result: set[int] = set()
    for part in spec.split("・"):
        bounds = re.split(r"[～~\-]", part)
        low, high = int(bounds[0]), int(bounds[-1])
        result.update(range(low, high + 1))
    return result


def _kanji_number(text: str) -> int:
    if text == "十":
        return 10
    if "十" in text:
        tens, _, ones = text.partition("十")
        return (KANJI_DIGITS.get(tens, 1)) * 10 + KANJI_DIGITS.get(ones, 0)
    return KANJI_DIGITS[text]


def weights_for(
    tables: ScoringTables,
    signal: Signal,
    shelters: Sequence[Shelter],
    areas: Sequence[CollectionArea],
) -> Weights | None:
    """シグナル1つ分の重み（層1〜6）。層0・層7・層8のシグナルと、決められないものは None。"""
    match signal.kind:
        case SignalKind.WALK_MINUTES:
            return walk_minutes(tables, int(signal.value))
        case SignalKind.LINE:
            return line(tables, signal.value)
        case SignalKind.BUS_STOP:
            return bus_stop(tables, signal.value)
        case SignalKind.SHELTER:
            return shelter(tables, signal.value, shelters)
        case SignalKind.TOWN:
            return town(tables, signal.value)
        case SignalKind.COLLECTION:
            return collection(tables, signal.value, areas)
        case _:
            return None
