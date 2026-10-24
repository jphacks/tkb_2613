"""【使い捨ての実験】推理ルールの試作。

engine の本実装ではない。マージしない（spike/rules ブランチだけに置く）。

手がかりの一覧（と投稿の時刻）にルールを順に当てはめ、結論ごとに根拠の手がかりの番号を返す。
しきい値はすべて仮の値。結果を見ながら調整する。

- R1 生活圏：station_sign / place_text（駅名）と、address_text / postal_code（区と町名）から、
  最寄り駅と町名
- R2 行動時間：場所の手がかりがある投稿のうち、平日の同じ時間帯のものが R2_MIN_POSTS 件以上
- R3 留守の時間：同じ曜日・同じ時間帯の投稿が R3_MIN_POSTS 件以上、または曜日を含む routine_text
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from tkb_common.schemas import Clue, ClueType, Post

# ---- 仮のしきい値 ----
R1_MIN_EVIDENCE = 2  # 最寄り駅を決めるのに要る、支持する手がかりの数
R2_WINDOW_HOURS = 1.0  # 「同じ時間帯」とみなす幅（±時間）
R2_MIN_POSTS = 2
R3_WINDOW_HOURS = 1.0
R3_MIN_POSTS = 3
# ----------------------

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

R1_NAME_TYPES = {ClueType.STATION_SIGN, ClueType.PLACE_TEXT}
R1_AREA_TYPES = {ClueType.ADDRESS_TEXT, ClueType.POSTAL_CODE}
# 場所の手がかり（R2 で「場所の投稿」とみなす）。shop は店の場所のデータがないので R1 には使わない
LOCATION_TYPES = R1_NAME_TYPES | R1_AREA_TYPES | {ClueType.SHOP}


@dataclass(frozen=True)
class Conclusion:
    rule: str
    attribute: str
    value: str
    clue_indices: list[int]
    note: str = ""


@dataclass
class Gazetteer:
    """data-prep の表（stations・postal・muni_mesh）。"""

    stations: list[dict[str, str]] = field(default_factory=list)
    postal: list[dict[str, str]] = field(default_factory=list)
    muni_meshes: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Gazetteer":
        meshes: dict[str, set[str]] = {}
        for row in pq.read_table(data_dir / "muni_mesh.parquet").to_pylist():
            meshes.setdefault(row["muni_code"], set()).add(row["mesh_1km"])
        return cls(
            stations=pq.read_table(data_dir / "stations.parquet").to_pylist(),
            postal=pq.read_table(data_dir / "postal.parquet").to_pylist(),
            muni_meshes=meshes,
        )


def _pattern(value: str) -> re.Pattern[str]:
    """読めない文字の x を1文字として扱う。"""
    return re.compile("".join("." if ch == "x" else re.escape(ch) for ch in value))


def _station_names(value: str, gaz: Gazetteer) -> set[str]:
    name = value.strip().removesuffix("駅")
    pattern = _pattern(name)
    return {s["station_name"] for s in gaz.stations if pattern.fullmatch(s["station_name"])}


def _area(clue: Clue, gaz: Gazetteer) -> tuple[set[str], set[str]]:
    """区市町村コードと町名の候補。"""
    if clue.type is ClueType.POSTAL_CODE:
        pattern = _pattern(clue.value.replace("-", ""))
        rows = [r for r in gaz.postal if pattern.fullmatch(r["postal_code"])]
    else:
        value = clue.value.replace(" ", "")
        rows = [
            r
            for r in gaz.postal
            if r["city"] in value
            and value.split(r["city"], 1)[1].startswith(_town(r["town"]))
            and _town(r["town"])
        ]
    return {r["muni_code"] for r in rows}, {_town(r["town"]) for r in rows}


def _town(town: str) -> str:
    return re.sub(r"（.*）$", "", town)


def rule_r1(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    name_hits: dict[int, set[str]] = {
        i: _station_names(c.value, gaz) for i, c in enumerate(clues) if c.type in R1_NAME_TYPES
    }
    name_hits = {i: names for i, names in name_hits.items() if names}

    area_hits = {i: _area(c, gaz) for i, c in enumerate(clues) if c.type in R1_AREA_TYPES}
    area_hits = {i: hit for i, hit in area_hits.items() if hit[0]}

    conclusions: list[Conclusion] = []

    # 町名：住所と郵便番号の候補の重なり
    if area_hits:
        munis = set.intersection(*(m for m, _ in area_hits.values()))
        towns = set.intersection(*(t for _, t in area_hits.values()))
        if len(towns) == 1:
            conclusions.append(
                Conclusion(
                    "R1",
                    "home_area",
                    next(iter(towns)),
                    sorted(area_hits),
                    "住所と郵便番号の重なり",
                )
            )
    else:
        munis = set()

    # 最寄り駅：駅名の候補を、区のメッシュで絞る
    if not name_hits:
        return conclusions
    candidates = set.intersection(*name_hits.values())
    evidence = set(name_hits)
    if munis:
        meshes = set().union(*(gaz.muni_meshes.get(m, set()) for m in munis))
        in_area = {s["station_name"] for s in gaz.stations if s["mesh_1km"] in meshes}
        if candidates & in_area:
            candidates &= in_area
            evidence |= set(area_hits)
    if len(candidates) == 1 and len(evidence) >= R1_MIN_EVIDENCE:
        station = next(iter(candidates))
        conclusions.append(
            Conclusion(
                "R1",
                "station",
                f"{station}駅",
                sorted(evidence),
                "駅名の候補を区のメッシュで絞った",
            )
        )
    return conclusions


def _local(post: Post) -> datetime:
    return post.created_at.astimezone(JST)


def _hour(post: Post) -> float:
    t = _local(post)
    return t.hour + t.minute / 60


def _largest_cluster(posts: list[Post], window: float) -> list[Post]:
    """時刻（時:分）が ±window 時間に収まる投稿の、いちばん大きいまとまり。"""
    best: list[Post] = []
    for center in posts:
        group = [p for p in posts if abs(_hour(p) - _hour(center)) <= window]
        if len(group) > len(best):
            best = group
    return best


def _hour_label(posts: list[Post]) -> str:
    return f"{round(sum(_hour(p) for p in posts) / len(posts))}時ごろ"


def rule_r2(clues: Sequence[Clue], posts: Sequence[Post], r1: list[Conclusion]) -> list[Conclusion]:
    station = next((c for c in r1 if c.attribute == "station"), None)
    if station is None:
        return []
    location_posts = {c.post_id for c in clues if c.type in LOCATION_TYPES}
    weekday = [p for p in posts if p.post_id in location_posts and _local(p).weekday() < 5]
    group = _largest_cluster(weekday, R2_WINDOW_HOURS)
    if len(group) < R2_MIN_POSTS:
        return []
    ids = {p.post_id for p in group}
    indices = [i for i, c in enumerate(clues) if c.post_id in ids and c.type in LOCATION_TYPES]
    return [
        Conclusion(
            "R2",
            "active_time",
            f"平日 {_hour_label(group)}に{station.value}のまわりにいる",
            indices,
            f"場所の投稿 {len(group)} 件",
        )
    ]


def rule_r3(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Conclusion]:
    conclusions: list[Conclusion] = []
    routine = {i: c for i, c in enumerate(clues) if c.type is ClueType.ROUTINE_TEXT}

    for day in range(7):
        same_day = [p for p in posts if _local(p).weekday() == day]
        group = _largest_cluster(same_day, R3_WINDOW_HOURS)
        if len(group) < R3_MIN_POSTS:
            continue
        ids = {p.post_id for p in group}
        indices = [i for i, c in routine.items() if c.post_id in ids]
        words = sorted({c.value for i, c in routine.items() if i in indices})
        conclusions.append(
            Conclusion(
                "R3",
                "routine",
                f"毎週{WEEKDAYS[day]}曜 {_hour_label(group)}に出かけている（{'・'.join(words)}）",
                indices,
                f"同じ曜日・時間帯の投稿 {len(group)} 件（根拠の番号は、その投稿の routine_text）",
            )
        )

    # 曜日を含む routine_text だけでも結論にする（投稿の時刻がそろわなくても）
    for i, c in routine.items():
        m = re.search(f"([{WEEKDAYS}])曜", c.value)
        if m and not any(f"{m[1]}曜" in con.value and i in con.clue_indices for con in conclusions):
            conclusions.append(
                Conclusion("R3", "routine", f"毎週{m[1]}曜（{c.value}）", [i], "本文の曜日")
            )
    return conclusions


def infer(clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer) -> list[Conclusion]:
    r1 = rule_r1(clues, gaz)
    return [*r1, *rule_r2(clues, posts, r1), *rule_r3(clues, posts)]
