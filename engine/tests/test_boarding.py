"""BP1 搭乗券・BP2 住所と留守。人物・番地・予約番号はすべて架空。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine import Conclusion, Gazetteer, infer
from tkb_engine.boarding import flight_date, rule_bp1, rule_bp2
from tkb_engine.cross_post import infer_rule_and_link_claims
from tkb_engine.planner import simulate

JST = ZoneInfo("Asia/Tokyo")
GAZ = Gazetteer(
    stations=[{"station_name": "根津", "mesh_1km": "m-bunkyo"}],
    postal=[{"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"}],
)
# 予約番号 QZ7X9K は伏せる前の形（detect を通らずに来ても値に出ないことを確かめる）
RAW_BCBP = "PDF417: M1KAKURE/HARUKI       EQZ7X9K HNDHIJNH 0681 305Y023A0012 100"
MASKED_BCBP = "PDF417: M1KAKURE/HARUKI       E*******HNDHIJNH 0681 305Y023A0012 100"
ENVELOPE = "カスタマバーコード: 〒113-0032 住所表示番号 2-99"


def _post(post_id: str, when: str, text: str = "") -> Post:
    created = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    return Post(post_id=post_id, text=text, created_at=created, images=[])


def _code(post_id: str, value: str) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=0,
        type=ClueType.CODE,
        value=value,
        region=(10, 10, 200, 80),
        confidence=0.98,
        source=ClueSource.OCR,
    )


def _text(post_id: str, type_: ClueType, value: str) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=None,
        type=type_,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def _of(conclusions: list[Conclusion], rule: str, attribute: str) -> list[Conclusion]:
    return [c for c in conclusions if c.rule == rule and c.attribute == attribute]


# ---- BP1 搭乗券 ----


@pytest.mark.parametrize("value", [RAW_BCBP, MASKED_BCBP])
def test_bp1_reads_the_name_and_the_flight_day_without_the_pnr(value: str) -> None:
    posts = [_post("bp", "2026-10-25 12:33", "来週は広島に帰る！名前はちゃんと隠しました。")]

    result = rule_bp1([_code("bp", value)], posts)
    assert "投稿者本人とは未確認" in result[0].note

    assert [(c.attribute, c.value, c.clue_indices) for c in result] == [
        ("full_name", "KAKURE HARUKI", [0]),
        ("long_term_home_absence", "11月1日に東京（羽田）→広島の便に乗る予定（搭乗券）", [0]),
    ]
    for c in result:
        assert "予約番号も読み取れる" in c.note
        assert "QZ7X9K" not in c.value + c.note


def test_bp1_keeps_the_name_but_no_plan_for_a_finished_trip() -> None:
    posts = [_post("bp", "2026-10-25 12:33", "広島から帰ってきた。楽しかった！")]

    result = rule_bp1([_code("bp", MASKED_BCBP)], posts)

    assert [c.attribute for c in result] == ["full_name"]


def test_bp1_takes_the_plan_from_a_later_pass_when_the_first_trip_is_over() -> None:
    posts = [
        _post("old", "2026-10-20 12:00", "ただいま！"),
        _post("bp", "2026-10-25 12:33", "来週は広島に帰る！"),
    ]
    clues = [_code("old", MASKED_BCBP.replace("HARUKI", "HARUKA")), _code("bp", MASKED_BCBP)]

    result = rule_bp1(clues, posts)

    assert [(c.attribute, c.clue_indices) for c in result] == [
        ("full_name", [0]),
        ("long_term_home_absence", [1]),
    ]


def test_bp1_ignores_other_codes_and_text() -> None:
    posts = [_post("p1", "2026-10-25 12:00")]
    clues = [
        _code("p1", "QRCode: https://example.com/demo"),
        _code("p1", ENVELOPE),
        # 本文に書かれた文字列は写真のバーコードではない
        _text("p1", ClueType.PLACE_TEXT, MASKED_BCBP),
    ]
    assert rule_bp1(clues, posts) == []


def test_bp1_names_unknown_airports_by_their_code() -> None:
    value = MASKED_BCBP.replace("HNDHIJ", "HNDXYZ")
    result = rule_bp1([_code("bp", value)], [_post("bp", "2026-10-25 12:33")])
    assert result[1].value == "11月1日に東京（羽田）→XYZの便に乗る予定（搭乗券）"


@pytest.mark.parametrize(
    ("julian", "posted", "expected"),
    [
        (305, date(2026, 10, 25), date(2026, 11, 1)),
        (298, date(2026, 10, 25), date(2026, 10, 25)),  # 投稿の当日
        (297, date(2026, 10, 25), None),  # 搭乗後に上げた搭乗券（翌年には回さない）
        (5, date(2026, 12, 28), date(2027, 1, 5)),  # 年末の投稿で年始の便は翌年
        (366, date(2026, 12, 1), None),  # 2026年も2027年も366日目はない
        (366, date(2028, 6, 1), date(2028, 12, 31)),
    ],
)
def test_flight_date_takes_the_year_from_the_post(
    julian: int, posted: date, expected: date | None
) -> None:
    assert flight_date(julian, posted) == expected


# ---- BP2 住所と留守 ----

ENVELOPE_POST = _post(
    "env", "2026-10-25 12:30", "実家から荷物と手紙が届いた。住所はちゃんと消したよ。"
)
PASS_POST = _post("bp", "2026-10-25 12:33", "来週は広島に帰る！名前はちゃんと隠しました。")


def test_bp2_joins_a_block_and_a_boarding_pass_from_different_posts() -> None:
    clues = [_code("env", ENVELOPE), _code("bp", MASKED_BCBP)]

    result = infer(clues, [ENVELOPE_POST, PASS_POST], GAZ)

    assert [(c.value, c.clue_indices) for c in _of(result, "BP2", "long_term_home_absence")] == [
        ("文京区弥生 2-99 付近の家が、11月1日に留守になる可能性（搭乗券）", [0, 1])
    ]
    # BP2 に置き換えたので、搭乗券だけの留守の予定は出さない。名前は残す
    assert _of(result, "BP1", "long_term_home_absence") == []
    assert [c.value for c in _of(result, "BP1", "full_name")] == ["KAKURE HARUKI"]


@pytest.mark.parametrize("excluded", ["env", "bp"])
def test_bp2_breaks_when_either_post_is_excluded(excluded: str) -> None:
    clues = [_code("env", ENVELOPE), _code("bp", MASKED_BCBP)]

    result = simulate(clues, [ENVELOPE_POST, PASS_POST], GAZ, [excluded])

    assert [c for c in result.after if c.rule == "BP2"] == []
    assert any(c.rule == "BP2" for c in result.before)


def test_bp2_needs_the_two_facts_in_different_posts() -> None:
    post = _post("same", "2026-10-25 12:30")
    clues = [_code("same", ENVELOPE), _code("same", MASKED_BCBP)]
    assert [c for c in infer(clues, [post], GAZ) if c.rule == "BP2"] == []


def test_bp2_uses_a_trip_in_the_text_when_the_block_is_known() -> None:
    trip = _post("trip", "2026-10-25 12:27", "来週から3泊で実家に帰省する。")
    clues = [_code("env", ENVELOPE), _text("trip", ClueType.ROUTINE_TEXT, "来週から3泊で帰省")]

    result = infer(clues, [ENVELOPE_POST, trip], GAZ)

    assert [c.value for c in _of(result, "BP2", "long_term_home_absence")] == [
        "文京区弥生 2-99 付近の家が、来週（10月26日の週）から4日ほど留守になる可能性（帰省）"
    ]
    assert [c for c in result if c.rule == "X3"] == []


def test_bp2_uses_the_station_with_a_boarding_pass() -> None:
    station = Conclusion("R1", "station", "根津駅", [0], "")
    clues = [_text("p1", ClueType.PLACE_TEXT, "根津駅"), _code("bp", MASKED_BCBP)]
    posts = [_post("p1", "2026-10-25 12:00"), PASS_POST]

    result = rule_bp2(clues, posts, [station], None)

    assert [(c.value, c.clue_indices) for c in result] == [
        ("根津駅付近の家が、11月1日に留守になる可能性（搭乗券）", [0, 1])
    ]


def test_bp2_falls_back_to_the_station_when_the_block_shares_the_post() -> None:
    block = Conclusion("R6", "home_block", "文京区弥生 2-99 付近", [1], "")
    station = Conclusion("R1", "station", "根津駅", [0], "")
    clues = [
        _text("p1", ClueType.PLACE_TEXT, "根津駅"),
        _code("bp", ENVELOPE),
        _code("bp", MASKED_BCBP),
    ]
    posts = [_post("p1", "2026-10-25 12:00"), PASS_POST]

    result = rule_bp2(clues, posts, [block, station], None)

    assert [(c.value, c.clue_indices) for c in result] == [
        ("根津駅付近の家が、11月1日に留守になる可能性（搭乗券）", [0, 2])
    ]


def test_bp2_leaves_station_and_text_trip_to_x3() -> None:
    station = Conclusion("R1", "station", "根津駅", [0], "")
    clues = [
        _text("p1", ClueType.PLACE_TEXT, "根津駅"),
        _text("trip", ClueType.ROUTINE_TEXT, "来週から帰省"),
    ]
    posts = [_post("p1", "2026-10-25 12:00"), _post("trip", "2026-10-25 12:10")]
    from tkb_engine.links import text_trip_plan

    plan = text_trip_plan(clues, posts, {"p1"})
    assert plan is not None
    assert rule_bp2(clues, posts, [station], plan) == []


def test_bp_conclusions_become_profile_candidates_with_both_posts() -> None:
    clues = [_code("env", ENVELOPE), _code("bp", MASKED_BCBP)]

    items = infer_rule_and_link_claims([ENVELOPE_POST, PASS_POST], clues, GAZ)

    by_attribute = {item.attribute.value: item for item in items}
    assert by_attribute["full_name"].value == "KAKURE HARUKI"
    absence = by_attribute["announced_long_absence"]
    assert absence.value == "文京区弥生 2-99 付近の家が、11月1日に留守になる可能性（搭乗券）"
    assert {e.post_id for e in absence.evidence if e.required} == {"env", "bp"}
    assert all("QZ7X9K" not in (e.excerpt or "") for item in items for e in item.evidence)
