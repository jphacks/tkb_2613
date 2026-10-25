import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tkb_common.schemas import TEXT_ONLY_TYPES, Clue, ClueSource, ClueType, Post
from tkb_engine import PLAN_MAX_POSTS, Gazetteer, plan, simulate

JST = ZoneInfo("Asia/Tokyo")
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"

# 根津と根岸は「根x」に合う。根津だけが文京区のメッシュにある
GAZ = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": "m-bunkyo"},
        {"station_name": "根岸", "mesh_1km": "m-taito"},
    ],
    postal=[
        {
            "postal_code": "1130032",
            "muni_code": "13105",
            "city": "文京区",
            "town": "弥生（次のビルを除く）",
        },
    ],
    muni_meshes={"13105": {"m-bunkyo"}},
)


def _post(post_id: str, when: str) -> Post:
    """when は JST の "2026-10-20 08:10" の形。2026-10-20 は火曜。"""
    created = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    return Post(post_id=post_id, text="", created_at=created, images=[])


def _clue(post_id: str, type_: ClueType, value: str) -> Clue:
    from_text = type_ in TEXT_ONLY_TYPES or type_ is ClueType.PLACE_TEXT
    return Clue(
        post_id=post_id,
        image_index=None if from_text else 0,
        type=type_,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT if from_text else ClueSource.VLM,
    )


def _station_case() -> tuple[list[Clue], list[Post]]:
    """駅名標（a）と郵便番号・住所（b）で根津駅。どちらも平日 8 時台なので R2 も出る。
    z は手がかりのない投稿（投稿の日付が3日に散らばり、時刻を推理に使える）。"""
    posts = [
        _post("a", "2026-10-20 08:10"),
        _post("b", "2026-10-21 08:30"),
        _post("z", "2026-10-23 12:00"),
    ]
    clues = [
        _clue("a", ClueType.STATION_SIGN, "根x"),
        _clue("b", ClueType.POSTAL_CODE, "113-00xx"),
        _clue("b", ClueType.ADDRESS_TEXT, "文京区弥生二丁目xx"),
    ]
    return clues, posts


def _load_demo() -> tuple[list[Clue], list[Post]]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        [Clue.model_validate(c) for c in doc["clues"]],
        [Post.model_validate(p) for p in doc["posts"]],
    )


def test_simulate_breaks_station_and_the_rules_that_depend_on_it() -> None:
    clues, posts = _station_case()

    sim = simulate(clues, posts, GAZ, ["b"])

    assert {c.attribute for c in sim.before} == {
        "home_area",
        "station",
        "home_block",
        "active_time",
    }
    assert sim.after == []
    assert sim.broken == ["home_area", "station", "home_block", "active_time"]
    assert sim.delete == ["b"]


def test_simulate_does_not_change_the_inputs() -> None:
    clues, posts = _station_case()
    clues_copy, posts_copy = list(clues), list(posts)

    simulate(clues, posts, GAZ, ["a", "b"])

    assert clues == clues_copy
    assert posts == posts_copy


def test_simulate_indices_point_into_the_clues_after_deleting() -> None:
    clues, posts = _station_case()
    clues = [_clue("c", ClueType.SHOP, "赤札堂"), *clues]
    posts = [_post("c", "2026-10-25 12:00"), *posts]

    sim = simulate(clues, posts, GAZ, ["c"])

    station = next(c for c in sim.after if c.attribute == "station")
    assert {sim.after_clues[i].post_id for i in station.clue_indices} == {"a", "b"}
    assert sim.broken == []


def test_simulate_with_nothing_to_delete_keeps_everything() -> None:
    clues, posts = _station_case()

    sim = simulate(clues, posts, GAZ, [])

    assert sim.after == sim.before
    assert sim.broken == []


def test_simulate_ignores_duplicate_ids() -> None:
    clues, posts = _station_case()

    assert simulate(clues, posts, GAZ, ["b", "b"]).delete == ["b"]


def test_plan_on_demo_prioritizes_sensitive_evidence() -> None:
    clues, posts = _load_demo()

    result = plan(clues, posts, GAZ)

    assert len(result.delete) <= PLAN_MAX_POSTS
    assert result.delete[0].endswith("000009")
    assert "station" in result.broken
    assert set(result.delete) <= {p.post_id for p in posts}


def test_plan_recommends_name_before_station_and_can_target_name_alone() -> None:
    station_clues, station_posts = _station_case()
    name_post = _post("name", "2026-10-22 12:00")
    name_clue = _clue("name", ClueType.NAME_TEXT, "はるき")

    name_only = plan([name_clue], [name_post], GAZ)
    assert name_only.delete == ["name"]
    assert name_only.broken == ["given_name_or_nickname"]

    together_clues = [*station_clues, name_clue]
    together_posts = [*station_posts, name_post]
    together = plan(together_clues, together_posts, GAZ)
    target_attributes = {c.attribute for c in together.before[-3:]}
    target_clue_indices = {i for c in together.before[-3:] for i in c.clue_indices}
    target_post_ids = {together_clues[i].post_id for i in target_clue_indices}
    assert together.delete[0] in target_post_ids
    assert set(together.broken) & target_attributes


def test_plan_prefers_the_post_used_as_evidence_more_often_on_a_tie() -> None:
    clues, posts = _station_case()

    # a と b のどちらを消しても駅と行動時間は崩れる。根拠になった回数の多い b を選ぶ
    assert plan(clues, posts, GAZ).delete == ["b"]


def test_plan_returns_nothing_when_no_important_conclusion() -> None:
    posts = [_post("a", "2026-10-20 08:10")]
    clues = [_clue("a", ClueType.SHOP, "赤札堂")]

    result = plan(clues, posts, GAZ)

    assert result.delete == []
    assert result.broken == []


def test_plan_prioritizes_identity_birthday_and_face_over_routine() -> None:
    posts = [_post(pid, "2026-10-24 20:00") for pid in ("routine", "face", "birthday", "name")]
    clues = [
        _clue("routine", ClueType.ROUTINE_TEXT, "毎週土曜はジム"),
        _clue("face", ClueType.FACE, "1人"),
        _clue("birthday", ClueType.AGE_TEXT, "10/24生まれ、22歳"),
        _clue("name", ClueType.NAME_TEXT, "山田花子"),
    ]

    result = plan(clues, posts, GAZ)

    assert result.delete == ["name", "birthday", "face"]
    assert {"full_name", "birthday", "age"} <= set(result.broken)
    assert "routine" not in result.delete


def test_plan_recommends_a_face_photo_even_without_an_inferred_conclusion() -> None:
    posts = [_post("face", "2026-10-24 20:00")]
    clues = [_clue("face", ClueType.FACE, "1人")]

    result = plan(clues, posts, GAZ)

    assert result.delete == ["face"]
    assert result.broken == []


def test_plan_stops_at_max_posts() -> None:
    # 曜日を含む本文が 4 投稿にあれば、留守の時間の結論が 4 つ。3 件消しても 1 つ残る
    days = ["月", "水", "木", "金"]
    posts = [_post(f"p{n}", f"2026-10-2{n} 12:00") for n in range(4)]
    clues = [
        _clue(f"p{n}", ClueType.ROUTINE_TEXT, f"毎週{day}曜のジム") for n, day in enumerate(days)
    ]

    result = plan(clues, posts, GAZ)

    assert result.delete == []
    assert "routine" not in result.broken
