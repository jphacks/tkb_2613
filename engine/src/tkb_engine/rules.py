"""推理ルール R1〜R3。手がかりの組み合わせから結論を出す。

入力：
- clues：投稿ごとに抜き出した手がかり（tkb_common.schemas.Clue）を全投稿ぶん並べた一覧。
  結論の根拠は、この一覧での番号（clue_indices）で返す
- posts：診断した投稿（tkb_common.schemas.Post）。R2・R3 は created_at（投稿の時刻）を使う
- gaz：data-prep の表（Gazetteer）。R1 が駅名・郵便番号・住所を引き当てる

出力：Conclusion の一覧。1つの Conclusion が捜査ボードの1行のもとになる。
attribute はまだ試作のときの名前（station / home_area / active_time / routine）のまま。
プロフィールの16項目（tkb_common.schemas.ProfileAttribute）への対応づけはこれから行う。
station → commute_station_or_line、home_area → residential_area はそのまま当てはまる。

ルールの中身：
- R1 生活圏：station_sign / place_text（駅名）と address_text / postal_code（区と町名）から、
  最寄り駅と町名
- R2 行動時間：R1 で駅が決まったとき、場所の手がかりがある平日の投稿が、同じ時間帯に
  R2_MIN_POSTS 件以上
- R3 留守の時間：同じ曜日・同じ時間帯の投稿が R3_MIN_POSTS 件以上、または曜日を含む routine_text

ルールを足すときは rule_rN(clues, posts, ...) -> list[Conclusion] を書き、infer に並べる。
しきい値は下の「しきい値」にまとめる。値は eval/fixtures/demo_observations.json で決めた仮の値で、
eval/spike/run.py の結果を見ながら調整する。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import Gazetteer

# ---- しきい値（仮の値） ----
# R1：最寄り駅を決めるのに要る、支持する手がかりの数（駅名＋区を絞った住所・郵便番号）
R1_MIN_EVIDENCE = 2
# R2：「同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R2_WINDOW_HOURS = 1.0
R2_MIN_POSTS = 2
# R3：「同じ曜日の同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R3_WINDOW_HOURS = 1.0
R3_MIN_POSTS = 3
# ----------------------------

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"

R1_NAME_TYPES = {ClueType.STATION_SIGN, ClueType.PLACE_TEXT}
R1_AREA_TYPES = {ClueType.ADDRESS_TEXT, ClueType.POSTAL_CODE}
# 場所の手がかり（R2 で「場所の投稿」とみなす）。shop は店の場所のデータがないので R1 には使わない
LOCATION_TYPES = R1_NAME_TYPES | R1_AREA_TYPES | {ClueType.SHOP}


@dataclass(frozen=True)
class Conclusion:
    """ルールが出した結論。

    - rule：出したルール（"R1" など）
    - attribute：項目の名前（モジュールの説明を参照）
    - value：画面に出す値
    - clue_indices：根拠の手がかりの、clues での番号
    - note：どう結論したかのメモ（推理の実況に使える）
    """

    rule: str
    attribute: str
    value: str
    clue_indices: list[int]
    note: str = ""


def rule_r1(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    """R1 生活圏：町名（home_area）と最寄り駅（station）。"""
    name_hits = {
        i: names
        for i, c in enumerate(clues)
        if c.type in R1_NAME_TYPES and (names := gaz.station_names(c.value))
    }
    area_hits = {
        i: hit for i, c in enumerate(clues) if c.type in R1_AREA_TYPES and (hit := gaz.area(c))[0]
    }

    conclusions: list[Conclusion] = []

    # 町名：住所と郵便番号の候補の重なり
    munis: set[str] = set()
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

    # 最寄り駅：駅名の候補を、区のメッシュで絞る
    if not name_hits:
        return conclusions
    candidates = set.intersection(*name_hits.values())
    evidence = set(name_hits)
    if munis:
        in_area = gaz.stations_in(munis)
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


def rule_r2(clues: Sequence[Clue], posts: Sequence[Post], r1: list[Conclusion]) -> list[Conclusion]:
    """R2 行動時間：平日のどの時間帯に R1 の駅のまわりにいるか（active_time）。"""
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
    """R3 留守の時間：毎週決まった曜日・時間帯に出かけている（routine）。"""
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
    """すべてのルールを順に当てはめる。R2 は R1 の結論を使う。"""
    r1 = rule_r1(clues, gaz)
    return [*r1, *rule_r2(clues, posts, r1), *rule_r3(clues, posts)]


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
