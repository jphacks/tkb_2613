"""W1 徒歩の距離と、f1 絞り込みの演出のデータ。投稿はすべて架空。"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import jismesh.utils as ju
import pytest

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine import Gazetteer, infer
from tkb_engine.narrowing import narrowing
from tkb_engine.planner import simulate
from tkb_engine.walk_area import (
    INTEGRATION_MARGIN,
    _walk_minutes,
    circle_shares,
    floor_two_digits,
    mesh_bounds,
    mesh_code,
    meters_per_degree,
)

JST = ZoneInfo("Asia/Tokyo")
NEZU = (35.717325, 139.76575)
NEZU_MESH = mesh_code(*NEZU)


def _gaz(households: dict[str, int] | None = None) -> Gazetteer:
    return Gazetteer(
        stations=[
            {"station_name": "根津", "mesh_1km": NEZU_MESH[:8], "lat": NEZU[0], "lon": NEZU[1]},
        ],
        postal=[{"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"}],
        households={NEZU_MESH: 2000} if households is None else households,
    )


def _post(post_id: str, text: str) -> Post:
    created = datetime(2026, 11, 14, 12, 0, tzinfo=JST)
    return Post(post_id=post_id, text=text, created_at=created, images=[])


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


def _envelope(post_id: str) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=0,
        type=ClueType.CODE,
        value="カスタマバーコード: 〒113-0032 住所表示番号 2-99-9",
        region=(10, 10, 200, 80),
        confidence=0.98,
        source=ClueSource.OCR,
    )


STATION_POSTS = [
    _post("s1", "根津駅、朝のホームが混んでる。"),
    _post("s2", "帰りに根津駅で降りてパン屋へ。"),
]
STATION_CLUES = [
    _text("s1", ClueType.PLACE_TEXT, "根津駅"),
    _text("s2", ClueType.PLACE_TEXT, "根津駅"),
]
WALK_POST = _post("w", "家から駅まで徒歩4分なのに、毎朝ギリギリ。")
WALK_CLUE = _text("w", ClueType.ROUTINE_TEXT, "家から駅まで徒歩4分")


# ---- メッシュ ----


def test_mesh_code_and_bounds_match_jismesh() -> None:
    # 1都3県のあたりを、メッシュの大きさと割り切れない間隔で埋める（ちょうど境目の点は、浮動小数点の
    # 丸めでどちらのメッシュにもなりうるので避ける）
    points = [(34.80037 + i * 0.0731, 138.80041 + j * 0.0917) for i in range(24) for j in range(23)]
    for lat, lon in points:
        code = mesh_code(lat, lon)
        assert code == str(int(ju.to_meshcode(lat, lon, 4)))
        south, west, north, east = mesh_bounds(code)
        assert south <= lat < north and west <= lon < east
        assert ju.to_meshpoint(code, 0, 0) == pytest.approx((south, west))


def test_circle_inside_one_mesh_takes_the_area_share() -> None:
    # 半径 80m の円は、根津駅のメッシュ（およそ 463m × 565m）の中に収まる
    south, west, north, east = mesh_bounds(NEZU_MESH)
    center = ((south + north) / 2, (west + east) / 2)
    per_lat, per_lon = meters_per_degree(center[0])
    mesh_area = (north - south) * per_lat * (east - west) * per_lon

    shares = circle_shares({NEZU_MESH: 2000}, center, 80)

    assert [s.code for s in shares] == [NEZU_MESH]
    assert shares[0].share == pytest.approx(math.pi * 80**2 / mesh_area, rel=0.001)


def test_circle_shares_add_up_to_the_circle_area() -> None:
    codes = {
        mesh_code(NEZU[0] + i * 0.002, NEZU[1] + j * 0.003)
        for i in range(-3, 4)
        for j in range(-3, 4)
    }
    shares = circle_shares(dict.fromkeys(codes, 100), NEZU, 320)

    south, west, north, east = mesh_bounds(NEZU_MESH)
    per_lat, per_lon = meters_per_degree(NEZU[0])
    mesh_area = (north - south) * per_lat * (east - west) * per_lon
    assert sum(s.share for s in shares) * mesh_area == pytest.approx(math.pi * 320**2, rel=0.001)
    # 世帯のないメッシュ（表にない）は入れない
    assert circle_shares({}, NEZU, 320) == []


@pytest.mark.parametrize("minutes", range(1, 21))
@pytest.mark.parametrize("offset", [(0.0, 0.0), (0.0013, -0.0021), (-0.0031, 0.0007)])
def test_apportioned_area_with_the_margin_never_exceeds_the_circle(
    minutes: int, offset: tuple[float, float]
) -> None:
    center = (NEZU[0] + offset[0], NEZU[1] + offset[1])
    radius = minutes * 80
    near = {
        mesh_code(center[0] + i * 0.002, center[1] + j * 0.003)
        for i in range(-12, 13)
        for j in range(-12, 13)
    }
    shares = circle_shares(dict.fromkeys(near, 1), center, radius)
    per_lat, per_lon = meters_per_degree(center[0])

    def area(code: str) -> float:
        s, w, n, e = mesh_bounds(code)
        return (n - s) * per_lat * (e - w) * per_lon

    total = sum(m.share * area(m.code) for m in shares) * (1 - INTEGRATION_MARGIN)
    assert total <= math.pi * radius**2
    assert total >= math.pi * radius**2 * 0.995


@pytest.mark.parametrize(
    ("value", "expected"), [(4425.4, 4400), (1222.6, 1200), (99.9, 99), (11682.9, 11000), (0.4, 0)]
)
def test_floor_two_digits_never_rounds_up(value: float, expected: int) -> None:
    assert floor_two_digits(value) == expected


# ---- 本文 ----


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("家から駅まで徒歩4分", 4),
        ("うちから根津駅まで徒歩４分", 4),
        ("最寄り駅まで徒歩10分の部屋に住んでる", 10),
        ("家の最寄駅まで徒歩4分", 4),
        ("根津駅から徒歩4分の部屋に引っ越した", 4),
        ("家から駅まで徒歩4分、実家の最寄り駅は徒歩20分", 4),
        ("駅から徒歩4分のカフェ", None),  # 家の話ではない
        ("家から研究室までは、運河駅から徒歩5分", None),  # ほかの駅の話
        ("家から徒歩4分のコンビニ", None),  # 駅の話ではない
        ("大学まで徒歩15分。家は根津駅の近く", None),  # 家と駅の間ではない
        ("会社は駅から徒歩5分。家族とランチ", None),
        ("徒歩4分のスーパー。家から駅は遠い", None),
        ("実家から駅まで徒歩4分", None),  # 本人の家ではない
        ("自宅からみなとみらい駅まで徒歩4分", None),  # ひらがなのほかの駅
        ("家から駅まで徒歩30分", None),  # 遠すぎる
        ("家から駅まで徒歩0分", None),
    ],
)
def test_walk_minutes(text: str, minutes: int | None) -> None:
    assert _walk_minutes(text, "根津") == minutes


# ---- W1 ----


def test_w1_draws_a_circle_around_the_r1_station() -> None:
    clues = [*STATION_CLUES, WALK_CLUE]

    result = [c for c in infer(clues, [*STATION_POSTS, WALK_POST], _gaz()) if c.rule == "W1"]

    assert len(result) == 1
    w1 = result[0]
    assert w1.attribute == "home_walk_area"
    assert w1.value.startswith("根津駅から半径320m（徒歩4分）、約")
    assert w1.clue_indices == [0, 1, 2]
    assert "第9条第9号" in w1.note and "国勢調査" in w1.note


def test_w1_breaks_without_the_walk_post_or_the_station() -> None:
    clues = [*STATION_CLUES, WALK_CLUE]
    posts = [*STATION_POSTS, WALK_POST]

    result = simulate(clues, posts, _gaz(), ["w"])

    assert any(c.rule == "W1" for c in result.before)
    assert not any(c.rule == "W1" for c in result.after)
    # 駅がわからなければ（R1 がなければ）出さない
    assert not any(c.rule == "W1" for c in infer([WALK_CLUE], [WALK_POST], _gaz()))


def test_w1_needs_the_census_table() -> None:
    clues = [*STATION_CLUES, WALK_CLUE]
    assert not any(c.rule == "W1" for c in infer(clues, [*STATION_POSTS, WALK_POST], _gaz({})))


# ---- f1 ----


def test_narrowing_lists_region_walk_and_block_with_their_posts() -> None:
    posts = [*STATION_POSTS, WALK_POST, _post("env", "実家から荷物と手紙が届いた。")]
    clues = [*STATION_CLUES, WALK_CLUE, _envelope("env")]
    gaz = _gaz()

    data = narrowing(clues, posts, infer(clues, posts, gaz), gaz)

    assert data is not None
    assert data["region"]["label"] == "1都3県"
    assert data["region"]["households"] == 2000
    walk = data["walk"]
    assert (walk["station"], walk["minutes"], walk["radius_m"]) == ("根津駅", 4, 320)
    assert [m["code"] for m in walk["meshes"]] == [NEZU_MESH]
    assert walk["households"] <= 2000
    assert walk["post_ids"] == ["s1", "s2", "w"]
    assert data["block"] == {"value": "文京区弥生 2-99 付近", "post_ids": ["env"]}
    assert len(data["sources"]) == 2


def test_narrowing_is_none_without_walk_or_block() -> None:
    gaz = _gaz()
    assert (
        narrowing(STATION_CLUES, STATION_POSTS, infer(STATION_CLUES, STATION_POSTS, gaz), gaz)
        is None
    )
