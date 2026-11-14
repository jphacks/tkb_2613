"""層7：よく行く場所からの地理的プロファイリング（Rossmo の CGT）。

よく行く場所は、手元のデータに位置がある場所だけ（駅の表の駅、避難所の表の施設）。
本人との関係（「散歩」「楽しみ」「また」「帰る」など）が同じ文にある投稿だけを使う。

CGT（Rossmo 1995, 2000）：マス i の点数
    p_i = Σ_n [ φ / d^f + (1 − φ) B^(g−f) / (2B − d)^g ]
    φ = 1（d > B）、0（d ≦ B）
d はマスと場所 n のマンハッタン距離（メートル）、B は緩衝地帯（場所どうしの最近傍距離の
平均の半分）、f = g = 1.2。点数は一番高いマスを 1 にして、ほかの層と掛けられるようにする。

もう1つの拠点：場所が3つ以上あるとき、ほかの場所までの最近傍距離が、全部の場所の
最近傍距離の中央値の OTHER_BASE_FACTOR 倍を超え、かつ OTHER_BASE_MIN_M を超える場所は
「もう1つの拠点」（大学など）として外す（Rossmo は拠点が2つある行動の型を別に扱っている）。
外したあと場所が2つ未満なら、層7は出さない。
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from tkb_common.schemas import Post
from tkb_engine.cross_post_facts import forbidden_context
from tkb_engine.scoring.constants import ROSSMO_F, ROSSMO_G, ROSSMO_MIN_PLACES
from tkb_engine.scoring.signals import Signal, SignalKind, excerpt, sentences
from tkb_engine.scoring.tables import ScoringTables, Shelter

METERS_PER_DEG_LAT = 110_950.0
# もう1つの拠点を外す基準（PR に書く）
OTHER_BASE_FACTOR = 3.0
OTHER_BASE_MIN_M = 5_000.0
OTHER_BASE_MIN_PLACES = 3
# 同じ名前の駅（路線ごとの行）がこれより離れていれば、どの駅か決められないので使わない
SAME_STATION_SPREAD_M = 1_000.0
STATION_NAME_MIN = 3
VISIT_WORDS = (
    "散歩",
    "楽しみ",
    "また",
    "よく",
    "いつも",
    "毎週",
    "通",
    "帰",
    "行",
    "寄",
    "好き",
    "めぐり",
)
# 略称 → 避難所の表の名前（本文の略称を、表の施設に結ぶ）
ALIASES = {"東大": "東京大学"}


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    post_ids: tuple[str, ...]


@dataclass(frozen=True)
class Geoprofile:
    weights: npt.NDArray[np.float64]
    places: list[Place]
    other_bases: list[Place]
    buffer_m: float


def place_signals(
    post: Post, station_names: Sequence[str], shelter_names: Sequence[str]
) -> list[Signal]:
    """よく行く場所のシグナル。名前の長いものから探し、見つけた所は消してから次を探す。"""
    stations = set(station_names)
    # 2文字の駅名（湯島・根津など）は、ほかの言葉の一部と見分けにくいので「〇〇駅」のときだけ
    patterns = {n: f"{n}駅" if len(n) < STATION_NAME_MIN else n for n in stations}
    patterns.update({n: n for n in shelter_names})
    patterns.update({n: n for n in ALIASES})
    names = sorted(patterns, key=lambda n: len(patterns[n]), reverse=True)
    found: list[Signal] = []
    for sentence in sentences(post.text):
        if forbidden_context(sentence) or not any(w in sentence for w in VISIT_WORDS):
            continue
        rest = sentence
        for name in names:
            if patterns[name] in rest:
                value = ALIASES.get(name, name)
                found.append(Signal(SignalKind.PLACE, post.post_id, value, excerpt(sentence)))
                rest = rest.replace(patterns[name], "")
    return found


def resolve(
    signals: Sequence[Signal], tables: ScoringTables, shelters: Sequence[Shelter]
) -> list[Place]:
    """場所の名前を位置に直す。同じ名前で離れた所が2つ以上あれば使わない。"""
    posts: dict[str, list[str]] = {}
    for s in signals:
        if s.kind == SignalKind.PLACE:
            posts.setdefault(s.value, []).append(s.post_id)
    places: list[Place] = []
    for name, post_ids in posts.items():
        points = [
            (float(tables.stations.lat[i]), float(tables.stations.lon[i]))
            for i, n in enumerate(tables.stations.name)
            if n == name
        ] or [(s.lat, s.lon) for s in shelters if s.name == name]
        if not points or _spread(points) > SAME_STATION_SPREAD_M:
            continue
        lat = sum(p[0] for p in points) / len(points)
        lon = sum(p[1] for p in points) / len(points)
        places.append(Place(name, lat, lon, tuple(dict.fromkeys(post_ids))))
    return places


def _spread(points: Sequence[tuple[float, float]]) -> float:
    return max((_manhattan(a, b) for a in points for b in points), default=0.0)


def _xy(lat: float, lon: float) -> tuple[float, float]:
    return lon * METERS_PER_DEG_LAT * math.cos(math.radians(lat)), lat * METERS_PER_DEG_LAT


def _manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = _xy(*a)
    bx, by = _xy(*b)
    return abs(ax - bx) + abs(ay - by)


def split_other_bases(places: Sequence[Place]) -> tuple[list[Place], list[Place]]:
    """ほかの場所の集まりから大きく離れた場所を外す。(残す場所, もう1つの拠点)"""
    if len(places) < OTHER_BASE_MIN_PLACES:
        return list(places), []
    nearest = [_nearest(p, places) for p in places]
    threshold = max(OTHER_BASE_FACTOR * statistics.median(nearest), OTHER_BASE_MIN_M)
    kept = [p for p, d in zip(places, nearest, strict=True) if d <= threshold]
    other = [p for p, d in zip(places, nearest, strict=True) if d > threshold]
    return kept, other


def _nearest(place: Place, places: Sequence[Place]) -> float:
    return min(_manhattan((place.lat, place.lon), (o.lat, o.lon)) for o in places if o is not place)


def geoprofile(tables: ScoringTables, places: Sequence[Place]) -> Geoprofile | None:
    """層7の重み。場所が2つ未満なら None。"""
    kept, other = split_other_bases(places)
    if len(kept) < ROSSMO_MIN_PLACES:
        return None
    buffer_m = statistics.fmean(_nearest(p, kept) for p in kept) / 2
    lat = tables.lat.astype(np.float64)
    lon = tables.lon.astype(np.float64)
    x = lon * METERS_PER_DEG_LAT * np.cos(np.radians(lat))
    y = lat * METERS_PER_DEG_LAT
    score = np.zeros(tables.size, dtype=np.float64)
    for p in kept:
        px, py = _xy(p.lat, p.lon)
        d = np.abs(x - px) + np.abs(y - py)
        outside = d > buffer_m
        near = np.where(outside, 1.0, (2 * buffer_m - d))
        score += np.where(
            outside,
            1.0 / np.power(np.maximum(d, 1.0), ROSSMO_F),
            buffer_m ** (ROSSMO_G - ROSSMO_F) / np.power(np.maximum(near, 1.0), ROSSMO_G),
        )
    peak = float(score.max())
    weights = score / peak if peak > 0 else score
    return Geoprofile(weights=weights, places=kept, other_bases=other, buffer_m=buffer_m)
