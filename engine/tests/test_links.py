import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tkb_common.schemas import TEXT_ONLY_TYPES, Clue, ClueSource, ClueType, Post
from tkb_engine import Conclusion, Gazetteer, infer, rule_x2, rule_x3, rule_x4, rule_x5

ROOT = Path(__file__).resolve().parents[2]
JST = ZoneInfo("Asia/Tokyo")
GAZ = Gazetteer(stations=[{"station_name": "根津", "mesh_1km": "m-bunkyo"}])
STATION = Conclusion("R1", "station", "根津駅", [0], "")


def _post(post_id: str, when: str) -> Post:
    """when は JST の "2026-10-20 08:10" の形。"""
    created = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    return Post(post_id=post_id, text="", created_at=created, images=[])


def _clue(post_id: str, type_: ClueType, value: str) -> Clue:
    """本文の手がかり。X2〜X5 は本文の手がかりだけを使う。"""
    assert type_ in TEXT_ONLY_TYPES or type_ in {ClueType.PLACE_TEXT, ClueType.ORG_TEXT}
    return Clue(
        post_id=post_id,
        image_index=None,
        type=type_,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def _with_text(post: Post, text: str) -> Post:
    return post.model_copy(update={"text": text})


def _of(conclusions: list[Conclusion], attribute: str) -> list[Conclusion]:
    return [c for c in conclusions if c.attribute == attribute]


# ---- X2 生まれた年 ----


def test_x2_joins_a_birthday_post_and_an_age_from_another_post() -> None:
    posts = [_post("bday", "2026-04-14 21:00"), _post("age", "2026-10-25 12:00")]
    clues = [
        _clue("bday", ClueType.AGE_TEXT, "4月14日は誕生日"),
        _clue("age", ClueType.AGE_TEXT, "21歳"),
    ]
    birthday = Conclusion("R8", "birthday", "4月14日ごろ", [0], "")

    assert rule_x2(clues, posts, [birthday]) == [
        Conclusion(
            "X2",
            "birthday",
            "2005年4月14日ごろ",
            [0, 1],
            "誕生日の投稿と、2026年10月の投稿の「21歳」を結合",
        )
    ]


def test_x2_counts_an_age_written_before_this_years_birthday() -> None:
    posts = [_post("bday", "2026-10-17 21:00"), _post("age", "2026-03-01 12:00")]
    clues = [
        _clue("bday", ClueType.AGE_TEXT, "10/17 誕生日"),
        _clue("age", ClueType.AGE_TEXT, "24歳"),
    ]

    (got,) = rule_x2(clues, posts, [Conclusion("R8", "birthday", "10月17日ごろ", [0], "")])

    assert got.value == "2001年10月17日ごろ"


def test_x2_replaces_the_r8_birthday_and_falls_back_when_the_age_post_is_gone() -> None:
    posts = [_post("bday", "2026-10-25 12:00"), _post("age", "2026-10-25 12:03")]
    clues = [
        _clue("bday", ClueType.AGE_TEXT, "4月14日は誕生日"),
        _clue("age", ClueType.AGE_TEXT, "21歳"),
    ]

    assert [c.value for c in _of(infer(clues, posts, GAZ), "birthday")] == ["2005年4月14日ごろ"]
    assert [c.value for c in _of(infer(clues[:1], posts, GAZ), "birthday")] == ["4月14日ごろ"]


def test_x2_ignores_a_birthday_that_already_has_a_year() -> None:
    clues = [_clue("p1", ClueType.AGE_TEXT, "21歳")]
    posts = [_post("p1", "2026-10-25 12:00")]
    birthday = Conclusion("R8", "birthday", "2001年10月17日ごろ", [0], "")

    assert rule_x2(clues, posts, [birthday]) == []


# ---- X3 留守の予定 ----


def test_x3_joins_the_home_station_and_a_trip_plan_from_another_post() -> None:
    posts = [
        _post("station", "2026-10-20 08:00"),
        _with_text(_post("trip", "2026-10-25 12:00"), "来週から3泊で実家に帰省する"),
    ]
    clues = [
        _clue("station", ClueType.PLACE_TEXT, "根津駅"),
        _clue("trip", ClueType.ROUTINE_TEXT, "来週から3泊で実家に帰省"),
    ]

    (got,) = rule_x3(clues, posts, [STATION])

    # 2026-10-25 は日曜。来週は 10-26 の月曜から
    assert got.attribute == "long_term_home_absence"
    assert got.value == "根津駅付近の家が来週（10月26日の週）から4日ほど留守になる可能性（帰省）"
    assert got.clue_indices == [0, 1]


def test_x3_reads_an_explicit_start_date_and_length() -> None:
    posts = [
        _post("station", "2026-10-20 08:00"),
        _with_text(_post("trip", "2026-10-25 12:00"), "11/3から1週間、北海道旅行"),
    ]
    clues = [
        _clue("station", ClueType.PLACE_TEXT, "根津駅"),
        _clue("trip", ClueType.PLACE_TEXT, "北海道"),
    ]

    (got,) = rule_x3(clues, posts, [STATION])

    assert got.value == "根津駅付近の家が11月3日から7日ほど留守になる可能性（旅行）"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 2026-10-21 は水曜
        ("明日から出張", "10月22日から"),
        ("明後日から2日間の遠征", "10月23日から2日ほど"),
        ("週末は旅行", "週末（10月24日ごろ）から"),
        ("しばらく留守にします", "10月21日の投稿のころから"),
    ],
)
def test_x3_counts_the_start_from_the_post_date(text: str, expected: str) -> None:
    posts = [
        _post("station", "2026-10-20 08:00"),
        _with_text(_post("trip", "2026-10-21 12:00"), text),
    ]
    clues = [
        _clue("station", ClueType.PLACE_TEXT, "根津駅"),
        _clue("trip", ClueType.ROUTINE_TEXT, text),
    ]

    (got,) = rule_x3(clues, posts, [STATION])

    assert got.value.startswith(f"根津駅付近の家が{expected}留守になる可能性")


def test_x3_skips_finished_trips_and_trips_without_a_known_home() -> None:
    posts = [_with_text(_post("trip", "2026-10-25 12:00"), "北海道旅行から帰ってきた")]
    clues = [
        _clue("station", ClueType.PLACE_TEXT, "根津駅"),
        _clue("trip", ClueType.PLACE_TEXT, "北海道"),
    ]

    assert rule_x3(clues, posts, [STATION]) == []
    assert rule_x3(clues, posts, []) == []


# ---- X4 行きつけの店 ----


def test_x4_finds_a_shop_in_two_posts_and_links_the_home_station() -> None:
    posts = [
        _post("shop1", "2026-10-20 08:00"),
        _with_text(_post("shop2", "2026-10-21 08:00"), "根津駅から歩いてすぐのベーカリーねこぜ"),
    ]
    clues = [
        _clue("shop1", ClueType.PLACE_TEXT, "ベーカリーねこぜ"),
        _clue("shop2", ClueType.PLACE_TEXT, "根津駅"),
        _clue("shop2", ClueType.PLACE_TEXT, "ベーカリーねこぜ"),
    ]
    station = Conclusion("R1", "station", "根津駅", [1], "")

    (got,) = rule_x4(clues, posts, [station], GAZ)

    assert got.attribute == "frequent_shop"
    assert got.value == "ベーカリーねこぜ（根津駅の近く）"
    assert got.clue_indices == [0, 1, 2]


def test_x4_needs_two_posts_and_ignores_station_names() -> None:
    posts = [_post("p1", "2026-10-20 08:00"), _post("p2", "2026-10-21 08:00")]
    once = [_clue("p1", ClueType.PLACE_TEXT, "ベーカリーねこぜ")]
    stations = [
        _clue("p1", ClueType.PLACE_TEXT, "根津駅"),
        _clue("p2", ClueType.PLACE_TEXT, "根津駅"),
    ]

    assert rule_x4(once, posts, [], GAZ) == []
    assert rule_x4(stations, posts, [], GAZ) == []


# ---- X5 勤務先 ----


def test_x5_takes_a_shop_named_in_a_post_about_a_shift() -> None:
    posts = [_with_text(_post("work", "2026-10-20 22:00"), "カフェ コモレビのシフト終わり")]
    clues = [
        _clue("work", ClueType.PLACE_TEXT, "カフェ コモレビ"),
        _clue("work", ClueType.ROUTINE_TEXT, "シフト終わり"),
    ]

    (got,) = rule_x5(clues, posts, GAZ)

    assert got.attribute == "workplace"
    assert got.value == "カフェ コモレビ（勤務先・バイト先の可能性）"
    assert got.clue_indices == [0, 1]


def test_x5_ignores_shops_and_stations_without_work_talk() -> None:
    posts = [
        _with_text(_post("visit", "2026-10-20 12:00"), "カフェ コモレビでランチ"),
        _with_text(_post("work", "2026-10-21 22:00"), "根津駅でバイト帰り"),
    ]
    clues = [
        _clue("visit", ClueType.PLACE_TEXT, "カフェ コモレビ"),
        _clue("work", ClueType.PLACE_TEXT, "根津駅"),
    ]

    assert rule_x5(clues, posts, GAZ) == []


# ---- 投稿をつなぐ流れ ----

CHAIN = [
    ("根津駅、朝のホームが思ったより混んでる。", [(ClueType.PLACE_TEXT, "根津駅")]),
    ("4月14日は誕生日だった。ケーキを1人で食べた。", [(ClueType.AGE_TEXT, "4月14日は誕生日")]),
    ("21歳、いまだに自炊がうまくならない。", [(ClueType.AGE_TEXT, "21歳")]),
    (
        "ベーカリーねこぜの塩パン、ここ毎週来てる。",
        [(ClueType.PLACE_TEXT, "ベーカリーねこぜ"), (ClueType.ROUTINE_TEXT, "毎週来てる")],
    ),
    (
        "根津駅から歩いてすぐのベーカリーねこぜ、新作のあんバターがおいしい。",
        [(ClueType.PLACE_TEXT, "根津駅"), (ClueType.PLACE_TEXT, "ベーカリーねこぜ")],
    ),
    (
        "カフェ コモレビのシフト終わり。まかないのオムライスが最高。",
        [(ClueType.PLACE_TEXT, "カフェ コモレビ"), (ClueType.ROUTINE_TEXT, "シフト終わり")],
    ),
    (
        "来週から3泊で実家に帰省する。猫の世話は友達に頼んだ。",
        [(ClueType.ROUTINE_TEXT, "来週から3泊で実家に帰省"), (ClueType.RELATION_TEXT, "猫")],
    ),
]


def test_infer_links_separate_posts_into_new_conclusions() -> None:
    posts = [
        _with_text(_post(f"p{n}", f"2026-10-25 12:{n:02d}"), text)
        for n, (text, _) in enumerate(CHAIN)
    ]
    clues = [
        _clue(f"p{n}", type_, value) for n, (_, found) in enumerate(CHAIN) for type_, value in found
    ]

    got = {c.attribute: c.value for c in infer(clues, posts, GAZ)}

    assert got["station"] == "根津駅"
    assert got["birthday"] == "2005年4月14日ごろ"
    assert got["long_term_home_absence"] == (
        "根津駅付近の家が来週（10月26日の週）から4日ほど留守になる可能性（帰省）"
    )
    assert got["frequent_shop"] == "ベーカリーねこぜ（根津駅の近く）"
    assert got["workplace"] == "カフェ コモレビ（勤務先・バイト先の可能性）"


def test_chain_demo_fixture_matches_the_planned_posts_and_finds_every_link() -> None:
    doc = json.loads((ROOT / "eval/fixtures/demo_chain.json").read_text())
    x1 = json.loads((ROOT / "eval/demo_account/x1_posts.json").read_text())
    chain = json.loads((ROOT / "eval/demo_account/chain_posts.json").read_text())
    posts = [Post.model_validate(post) for post in doc["posts"]]
    clues = [Clue.model_validate(clue) for clue in doc["clues"]]

    assert [p.text for p in posts] == [item["text"] for item in [*x1["posts"], *chain["posts"]]]
    got = {c.attribute: c.value for c in infer(clues, posts, GAZ)}
    assert got["home_school_commute"] == "根津駅付近から筑波大学へ通学している可能性"
    assert got["birthday"] == "2005年4月14日ごろ"
    assert got["long_term_home_absence"].startswith("根津駅付近の家が来週")
    assert got["frequent_shop"] == "ベーカリーねこぜ（根津駅の近く）"
    assert got["workplace"] == "カフェ コモレビ（勤務先・バイト先の可能性）"
