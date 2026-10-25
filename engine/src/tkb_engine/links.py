"""別々の投稿をつなぐ推理ルール X2〜X5。

rules.py の R1〜R12 の結論と手がかりを受け取り、1件ずつでは出ない結論を足す。
「この投稿とこの投稿がつながって、こうわかる」を見せるためのルール。

- X2 生まれた年：R12 の誕生日（年なし）と、別の投稿の「◯歳」とその投稿の日付から、生まれた年
  （birthday。R12 の結論と置き換える）
- X3 留守の予定：生活圏（町名・最寄り駅・市区町村の順に使う）と、
  別の投稿の旅行・帰省・出張の予定から、家を空ける時期（long_term_home_absence）。終わった旅行の話は使わない
- X4 行きつけの店：同じ店名が X4_MIN_POSTS 件以上の投稿に出てくる（frequent_shop）。
  そのどれかに R1 の最寄り駅も出てくれば「◯◯駅の近く」を添える
- X5 勤務先・バイト先：会社・店の名前と、同じ投稿の「シフト」「バイト」などの言葉（workplace）

ルールを足すときは rule_xN を書き、link に並べる。しきい値は下にまとめる。
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import SCHOOL_WORDS, Conclusion, _local, _most_frequent

# ---- しきい値（仮の値） ----
# X4：行きつけとみなすのに要る、同じ店名が出てくる投稿の数
X4_MIN_POSTS = 2
# ----------------------------

AGE = re.compile(r"(\d{1,3})\s*歳")
# X3：旅行・帰省などの予定の言葉と、もう終わった話の言葉
TRIP_WORDS = ("旅行", "帰省", "実家に帰", "出張", "遠征", "旅に出", "留守")
PAST_WORDS = ("行ってきた", "帰ってきた", "ただいま", "帰宅した", "楽しかった")
# X3：予定の手がかりを探す type（本文の手がかり）
TRIP_TYPES = {ClueType.ROUTINE_TEXT, ClueType.PLACE_TEXT, ClueType.RELATION_TEXT}
# X4：店名の手がかり（写真の看板は shop、本文の店名は place_text）
SHOP_TYPES = {ClueType.SHOP, ClueType.PLACE_TEXT}
# X5：働いていることを示す言葉と、勤務先の名前の手がかり（本文の店名は place_text になる）
WORK_WORDS = ("バイト", "シフト", "出勤", "退勤", "勤務", "職場", "残業", "まかない")
WORK_TYPES = {ClueType.ORG_TEXT, ClueType.SHOP, ClueType.PLACE_TEXT}


def rule_x2(
    clues: Sequence[Clue], posts: Sequence[Post], conclusions: Sequence[Conclusion]
) -> list[Conclusion]:
    """X2 生まれた年：誕生日の投稿と、別の投稿の年齢（birthday）。"""
    birthday = next((c for c in conclusions if c.attribute == "birthday"), None)
    if birthday is None:
        return []
    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日ごろ", birthday.value)
    if m is None:
        return []
    month, day = int(m[1]), int(m[2])
    created = {p.post_id: _local(p) for p in posts}
    birthday_posts = {clues[i].post_id for i in birthday.clue_indices}
    ages = [
        (created[c.post_id], int(a[1]), i)
        for i, c in enumerate(clues)
        if c.type is ClueType.AGE_TEXT
        and c.post_id in created
        and c.post_id not in birthday_posts
        and (a := AGE.search(c.value))
    ]
    if not ages:
        return []
    when, age, index = max(ages)
    # 年齢を書いた日が、その年の誕生日より前なら、まだ誕生日が来ていない
    year = when.year - age - (1 if (when.month, when.day) < (month, day) else 0)
    return [
        Conclusion(
            "X2",
            "birthday",
            f"{year}年{month}月{day}日ごろ",
            sorted({*birthday.clue_indices, index}),
            f"誕生日の投稿と、{when.year}年{when.month}月の投稿の「{age}歳」を結合",
        )
    ]


def rule_x3(
    clues: Sequence[Clue], posts: Sequence[Post], conclusions: Sequence[Conclusion]
) -> list[Conclusion]:
    """X3 留守の予定：生活圏と、別の投稿の旅行・帰省の予定（long_term_home_absence）。"""
    home = next(
        (
            c
            for attribute in ("home_area", "station", "home_city")
            for c in conclusions
            if c.attribute == attribute
        ),
        None,
    )
    if home is None:
        return []
    home_posts = {clues[i].post_id for i in home.clue_indices}
    by_id = {p.post_id: p for p in posts}
    for i, clue in enumerate(clues):
        post = by_id.get(clue.post_id)
        if clue.type not in TRIP_TYPES or post is None or post.post_id in home_posts:
            continue
        text = f"{clue.value} {post.text}"
        word = next((w for w in TRIP_WORDS if w in text), None)
        if word is None or any(w in text for w in PAST_WORDS):
            continue
        when = _trip_start(text, _local(post))
        days = _trip_days(text)
        length = f"{days}日ほど" if days else ""
        return [
            Conclusion(
                "X3",
                "long_term_home_absence",
                f"{home.value}付近の家が{when}{length}留守になる可能性（{word}）",
                sorted({*home.clue_indices, i}),
                "生活圏の投稿と、旅行・帰省の予定の投稿を結合。日付は投稿の日から数えた",
            )
        ]
    return []


def rule_x4(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    conclusions: Sequence[Conclusion],
    gaz: Gazetteer,
) -> list[Conclusion]:
    """X4 行きつけの店：いくつもの投稿に出てくる同じ店（frequent_shop）。"""
    shops: dict[str, list[int]] = {}
    names: dict[str, str] = {}
    for i, c in enumerate(clues):
        value = c.value.strip()
        if (
            c.type not in SHOP_TYPES
            or not value
            or "x" in value.lower()
            or gaz.station_names(value)
            or any(w in value for w in SCHOOL_WORDS)
        ):
            continue
        key = "".join(value.lower().split())
        shops.setdefault(key, []).append(i)
        names.setdefault(key, value)
    posts_of = {key: {clues[i].post_id for i in ids} for key, ids in shops.items()}
    frequent = {k: ids for k, ids in shops.items() if len(posts_of[k]) >= X4_MIN_POSTS}
    # 投稿の数で比べる（同じ投稿に2回出ても1回）。投稿ごとに代表の手がかり1つにして数える
    best = _most_frequent(
        {k: [ids[0] for ids in _by_post(clues, frequent[k]).values()] for k in frequent}
    )
    if best is None:
        return []

    evidence = set(frequent[best])
    value = names[best]
    station = next((c for c in conclusions if c.attribute == "station"), None)
    if station is not None:
        # 店の投稿のどれかに最寄り駅の名前が出てくれば、その投稿の駅名の手がかりも根拠に入れる
        texts = {p.post_id: p.text for p in posts}
        near = station.value.removesuffix("駅")
        with_station = {pid for pid in posts_of[best] if near in texts.get(pid, "")}
        with_station |= {
            c.post_id for c in clues if c.post_id in posts_of[best] and near in c.value
        }
        if with_station:
            value += f"（{station.value}の近く）"
            evidence.update(
                i for i, c in enumerate(clues) if c.post_id in with_station and near in c.value
            )
    return [
        Conclusion(
            "X4",
            "frequent_shop",
            value,
            sorted(evidence),
            f"同じ店が {len(posts_of[best])} 件の投稿に出てくる",
        )
    ]


def rule_x5(clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer) -> list[Conclusion]:
    """X5 勤務先・バイト先：働く話をした投稿に出てくる会社・店の名前（workplace）。"""
    # 働く話をした投稿：本文か、生活の決まりの手がかりに WORK_WORDS がある
    work_posts = {p.post_id for p in posts if any(w in p.text for w in WORK_WORDS)}
    work_posts |= {
        c.post_id
        for c in clues
        if c.type is ClueType.ROUTINE_TEXT and any(w in c.value for w in WORK_WORDS)
    }

    places: dict[str, list[int]] = {}
    for i, c in enumerate(clues):
        value = c.value.strip()
        if (
            c.type in WORK_TYPES
            and c.post_id in work_posts
            and value
            and "x" not in value.lower()
            and not any(w in value for w in SCHOOL_WORDS)
            and not gaz.station_names(value)
        ):
            places.setdefault(value, []).append(i)
    best = _most_frequent(places)
    if best is None:
        return []
    best_posts = {clues[i].post_id for i in places[best]}
    # 同じ投稿の「シフト終わり」などの手がかりも根拠に入れる
    routine = [
        i
        for i, c in enumerate(clues)
        if c.post_id in best_posts
        and c.type is ClueType.ROUTINE_TEXT
        and any(w in c.value for w in WORK_WORDS)
    ]
    return [
        Conclusion(
            "X5",
            "workplace",
            f"{best}（勤務先・バイト先の可能性）",
            sorted({*places[best], *routine}),
            "店・会社の名前と、同じ投稿の働く話",
        )
    ]


def link(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    conclusions: Sequence[Conclusion],
    gaz: Gazetteer,
) -> list[Conclusion]:
    """R1〜R12 の結論に X2〜X5 を足した一覧。X2 が出たら R12 の誕生日と置き換える。"""
    x2 = rule_x2(clues, posts, conclusions)
    base = [c for c in conclusions if not (x2 and c.attribute == "birthday")]
    return [
        *base,
        *x2,
        *rule_x3(clues, posts, base),
        *rule_x4(clues, posts, base, gaz),
        *rule_x5(clues, posts, gaz),
    ]


def _trip_start(text: str, posted: datetime) -> str:
    """予定の始まりを「10月28日から」の形で。わからなければ投稿の日を使う。"""
    if m := re.search(r"(\d{1,2})\s*(?:月|/)\s*(\d{1,2})\s*日?\s*(?:から|〜|~)", text):
        return f"{int(m[1])}月{int(m[2])}日から"
    for word, offset in (("明後日", 2), ("明日", 1)):
        if word in text:
            start = posted + timedelta(days=offset)
            return f"{start.month}月{start.day}日から"
    if "来週" in text:
        start = posted + timedelta(days=7 - posted.weekday())
        return f"来週（{start.month}月{start.day}日の週）から"
    if "週末" in text:
        start = posted + timedelta(days=(5 - posted.weekday()) % 7)
        return f"週末（{start.month}月{start.day}日ごろ）から"
    return f"{posted.month}月{posted.day}日の投稿のころから"


def _trip_days(text: str) -> int | None:
    """何日留守にするか。「3泊」は4日、「5日間」は5日、「1週間」は7日。"""
    if m := re.search(r"(\d+)\s*泊", text):
        return int(m[1]) + 1
    if m := re.search(r"(\d+)\s*日間", text):
        return int(m[1])
    if re.search(r"(?:1|一)\s*週間", text):
        return 7
    return None


def _by_post(clues: Sequence[Clue], indices: Sequence[int]) -> dict[str, list[int]]:
    """手がかりの番号を、投稿ごとにまとめる。"""
    grouped: dict[str, list[int]] = {}
    for i in indices:
        grouped.setdefault(clues[i].post_id, []).append(i)
    return grouped
