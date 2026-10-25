from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_common.schemas import TEXT_ONLY_TYPES, Clue, ClueSource, ClueType, Post
from tkb_engine import (
    Conclusion,
    Gazetteer,
    infer,
    rule_r1,
    rule_r2,
    rule_r3,
    rule_r4,
    rule_r5,
    rule_r6,
    rule_r7,
)

JST = ZoneInfo("Asia/Tokyo")

# 根津と根岸は「根x」に合う。根津だけが文京区のメッシュにある
GAZ = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": "m-bunkyo"},
        {"station_name": "根岸", "mesh_1km": "m-taito"},
        {"station_name": "新宿", "mesh_1km": "m-shinjuku"},
        # 根津の隣の駅（駅名標に並ぶ）
        {"station_name": "湯島", "mesh_1km": "m-bunkyo"},
        {"station_name": "千駄木", "mesh_1km": "m-bunkyo"},
    ],
    postal=[
        {"postal_code": "1130031", "muni_code": "13105", "city": "文京区", "town": "根津"},
        {
            "postal_code": "1130032",
            "muni_code": "13105",
            "city": "文京区",
            "town": "弥生（次のビルを除く）",
        },
        {"postal_code": "1600022", "muni_code": "13104", "city": "新宿区", "town": "新宿"},
    ],
    muni_meshes={"13105": {"m-bunkyo"}, "13104": {"m-shinjuku"}},
)


def _post(post_id: str, when: str) -> Post:
    """when は JST の "2026-10-20 08:10" の形。2026-10-20 は火曜。"""
    created = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    return Post(post_id=post_id, text="", created_at=created, images=[])


def _clue(post_id: str, type_: ClueType, value: str) -> Clue:
    """本文の手がかり（routine_text・place_text など）は source=text、それ以外は写真から。"""
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


def _by_attribute(conclusions: list[Conclusion]) -> dict[str, Conclusion]:
    return {c.attribute: c for c in conclusions}


# ---- Gazetteer ----


def test_station_names_treats_x_as_any_char_and_drops_suffix() -> None:
    assert GAZ.station_names("根x") == {"根津", "根岸"}
    assert GAZ.station_names(" 新宿駅 ") == {"新宿"}
    assert GAZ.station_names("渋谷") == set()


def test_stations_in_returns_stations_in_municipality_meshes() -> None:
    assert GAZ.stations_in({"13105"}) == {"根津", "湯島", "千駄木"}
    assert GAZ.stations_in({"99999"}) == set()


def test_area_from_partial_postal_code() -> None:
    munis, towns = GAZ.area(_clue("p", ClueType.POSTAL_CODE, "113-00xx"))
    assert munis == {"13105"}
    assert towns == {"根津", "弥生"}


def test_area_from_address_matches_city_then_town() -> None:
    munis, towns = GAZ.area(_clue("p", ClueType.ADDRESS_TEXT, "文京区 弥生二丁目xx"))
    assert munis == {"13105"}
    assert towns == {"弥生"}


def test_area_returns_empty_when_nothing_matches() -> None:
    assert GAZ.area(_clue("p", ClueType.ADDRESS_TEXT, "台東区上野")) == (set(), set())


def test_load_reads_parquet_tables(tmp_path: Path) -> None:
    pq.write_table(
        pa.Table.from_pylist([{"station_name": "根津", "mesh_1km": "m1"}]),
        tmp_path / "stations.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [{"postal_code": "1130031", "muni_code": "13105", "city": "文京区", "town": "根津"}]
        ),
        tmp_path / "postal.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [{"muni_code": "13105", "mesh_1km": "m1"}, {"muni_code": "13105", "mesh_1km": "m2"}]
        ),
        tmp_path / "muni_mesh.parquet",
    )

    gaz = Gazetteer.load(tmp_path)

    assert gaz.station_names("根津") == {"根津"}
    assert gaz.muni_meshes == {"13105": {"m1", "m2"}}
    assert len(gaz.postal) == 1


# ---- R1 ----


def test_r1_narrows_station_by_area_and_finds_town() -> None:
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.ROUTINE_TEXT, "電車混んでる"),
        _clue("p3", ClueType.POSTAL_CODE, "113-00xx"),
        _clue("p4", ClueType.ADDRESS_TEXT, "文京区弥生二丁目xx"),
    ]

    got = _by_attribute(rule_r1(clues, GAZ))

    assert got["home_area"].value == "弥生"
    assert got["home_area"].clue_indices == [2, 3]
    assert got["station"].value == "根津駅"
    assert got["station"].clue_indices == [0, 2, 3]


def test_r1_needs_min_evidence_for_station() -> None:
    one = [_clue("p1", ClueType.STATION_SIGN, "新宿")]
    two = [*one, _clue("p2", ClueType.PLACE_TEXT, "新宿駅")]

    assert rule_r1(one, GAZ) == []
    station = _by_attribute(rule_r1(two, GAZ))["station"]
    assert (station.value, station.clue_indices) == ("新宿駅", [0, 1])


def test_r1_no_station_when_candidates_stay_ambiguous() -> None:
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.STATION_SIGN, "根x"),
    ]

    assert rule_r1(clues, GAZ) == []


def test_r1_ignores_area_outside_station_candidates() -> None:
    # 新宿区の住所では「根x」の候補が絞れないので、住所は駅の根拠に入れない
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.ADDRESS_TEXT, "新宿区新宿3丁目"),
    ]

    got = _by_attribute(rule_r1(clues, GAZ))

    assert "station" not in got
    assert got["home_area"].value == "新宿"


def test_r1_no_town_when_area_is_ambiguous() -> None:
    clues = [_clue("p1", ClueType.POSTAL_CODE, "113-00xx")]

    assert rule_r1(clues, GAZ) == []


def _sign(post_id: str, value: str, region: tuple[int, int, int, int] | None) -> Clue:
    """写真の駅名標の文字（同じ post_id・image_index なら同じ駅名標）。"""
    return Clue(
        post_id=post_id,
        image_index=0,
        type=ClueType.STATION_SIGN,
        value=value,
        region=region,
        confidence=0.95,
        source=ClueSource.VLM,
    )


def test_r1_reads_a_station_sign_with_neighbor_stations() -> None:
    # テスト写真の nezu_sign と同じ形：大きい「根津」と、小さい隣の駅名・かな・駅番号
    clues = [
        _sign("p1", "根津", (549, 422, 1300, 705)),
        _sign("p1", "ねづ", (600, 380, 700, 411)),
        _sign("p1", "C 14", (1310, 430, 1360, 474)),
        _sign("p1", "湯島", (100, 750, 200, 789)),
        _sign("p1", "千駄木", (1200, 750, 1300, 794)),
    ]

    station = _by_attribute(rule_r1(clues, GAZ))["station"]

    assert station.value == "根津駅"
    # 隣の駅名も根拠に入る（表にない「ねづ」「C 14」は入らない）
    assert station.clue_indices == [0, 3, 4]


def test_r1_without_regions_takes_the_first_name_on_the_sign() -> None:
    clues = [
        _sign("p1", "根津", None),
        _sign("p1", "湯島", None),
        _sign("p1", "千駄木", None),
    ]

    assert _by_attribute(rule_r1(clues, GAZ))["station"].value == "根津駅"


def test_r1_signs_in_different_photos_are_counted_separately() -> None:
    clues = [
        _sign("p1", "根津", (0, 0, 300, 100)),
        _sign("p2", "根津", (0, 0, 300, 100)),
        _sign("p3", "新宿", (0, 0, 300, 100)),
    ]

    station = _by_attribute(rule_r1(clues, GAZ))["station"]

    assert (station.value, station.clue_indices) == ("根津駅", [0, 1])


def test_r1_most_votes_wins_even_if_names_disagree() -> None:
    clues = [
        _clue("p1", ClueType.PLACE_TEXT, "新宿駅"),
        _clue("p2", ClueType.PLACE_TEXT, "新宿"),
        _sign("p3", "根津", (0, 0, 300, 100)),
    ]

    station = _by_attribute(rule_r1(clues, GAZ))["station"]

    assert (station.value, station.clue_indices) == ("新宿駅", [0, 1])


def test_r1_no_station_when_votes_tie() -> None:
    clues = [
        _clue("p1", ClueType.PLACE_TEXT, "新宿駅"),
        _sign("p2", "根津", (0, 0, 300, 100)),
        _sign("p3", "千駄木", (0, 0, 300, 100)),
    ]

    assert "station" not in _by_attribute(rule_r1(clues, GAZ))


def test_r1_neighbor_names_do_not_vote_for_themselves() -> None:
    # 駅名標の「湯島」は隣の駅。湯島を推すのは本文の1件だけなので、根津と並んで決まらない
    clues = [
        _sign("p1", "根津", (0, 0, 600, 200)),
        _sign("p1", "湯島", (0, 300, 100, 330)),
        _clue("p2", ClueType.PLACE_TEXT, "湯島駅"),
    ]

    assert "station" not in _by_attribute(rule_r1(clues, GAZ))


# ---- R2 ----


def _station(value: str = "根津駅") -> list[Conclusion]:
    return [Conclusion("R1", "station", value, [0])]


def test_r2_finds_weekday_time_of_location_posts() -> None:
    posts = [
        _post("p1", "2026-10-19 08:10"),  # 月
        _post("p2", "2026-10-21 08:40"),  # 水
        _post("p3", "2026-10-24 08:20"),  # 土：平日ではない
        _post("p4", "2026-10-22 08:30"),  # 場所の手がかりがない
    ]
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.SHOP, "赤札堂"),
        _clue("p3", ClueType.SHOP, "赤札堂"),
        _clue("p4", ClueType.ROUTINE_TEXT, "眠い"),
    ]

    [got] = rule_r2(clues, posts, _station())

    assert got.attribute == "active_time"
    assert got.value == "平日 8時ごろに根津駅のまわりにいる"
    assert got.clue_indices == [0, 1]


def test_r2_needs_station_from_r1() -> None:
    posts = [_post("p1", "2026-10-19 08:10"), _post("p2", "2026-10-21 08:40")]
    clues = [_clue("p1", ClueType.SHOP, "赤札堂"), _clue("p2", ClueType.SHOP, "赤札堂")]

    assert rule_r2(clues, posts, []) == []


def test_r2_needs_min_posts_in_same_window() -> None:
    posts = [_post("p1", "2026-10-19 08:10"), _post("p2", "2026-10-21 18:00")]
    clues = [_clue("p1", ClueType.SHOP, "赤札堂"), _clue("p2", ClueType.SHOP, "赤札堂")]

    assert rule_r2(clues, posts, _station()) == []


# ---- R3 ----


def test_r3_finds_same_weekday_and_time() -> None:
    posts = [
        _post("p1", "2026-10-06 20:10"),
        _post("p2", "2026-10-13 20:30"),
        _post("p3", "2026-10-20 19:50"),
    ]
    clues = [
        _clue("p1", ClueType.ROUTINE_TEXT, "毎週火曜のジム"),
        _clue("p2", ClueType.ROUTINE_TEXT, "ジム"),
        _clue("p3", ClueType.ROUTINE_TEXT, "ジム"),
    ]

    # 曜日を含む routine_text（0）は時刻のまとまりの結論に入っているので、別の結論にしない
    [got] = rule_r3(clues, posts)

    # 「毎週火曜のジム」は「ジム」を含むので、多く出てきた「ジム」だけを括弧に入れる
    assert got.value == "毎週火曜 20時ごろに出かけている（ジム）"
    assert got.clue_indices == [0, 1, 2]


def test_r3_uses_weekday_in_text_alone() -> None:
    posts = [_post("p1", "2026-10-20 12:00")]
    clues = [_clue("p1", ClueType.ROUTINE_TEXT, "毎週金曜はヨガ")]

    [got] = rule_r3(clues, posts)

    assert (got.value, got.clue_indices, got.note) == (
        "毎週金曜（毎週金曜はヨガ）",
        [0],
        "本文の曜日",
    )


def test_r3_needs_min_posts() -> None:
    posts = [_post("p1", "2026-10-06 20:10"), _post("p2", "2026-10-13 20:30")]
    clues = [_clue("p1", ClueType.ROUTINE_TEXT, "ジム")]

    assert rule_r3(clues, posts) == []


# ---- infer ----


def test_infer_chains_r1_into_r2() -> None:
    posts = [
        _post("p1", "2026-10-19 08:10"),
        _post("p2", "2026-10-21 08:40"),
        _post("p3", "2026-10-24 15:00"),
    ]
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.POSTAL_CODE, "113-00xx"),
        _clue("p3", ClueType.ADDRESS_TEXT, "文京区弥生二丁目"),
    ]

    got = infer(clues, posts, GAZ)

    assert [(c.rule, c.attribute) for c in got] == [
        ("R1", "home_area"),
        ("R1", "station"),
        ("R2", "active_time"),
    ]


# ---- R4 路線 ----

# 駅と路線の組ごとに1行。正式名は「9号線千代田線」のように番号がつく
LINE_GAZ = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": "m-bunkyo", "line_name": "9号線千代田線"},
        {"station_name": "根岸", "mesh_1km": "m-taito", "line_name": "根岸線"},
        {"station_name": "新宿", "mesh_1km": "m-shinjuku", "line_name": "山手線"},
        {"station_name": "新宿", "mesh_1km": "m-shinjuku", "line_name": "中央線"},
    ],
)


def _station_conclusion(name: str) -> Conclusion:
    return Conclusion("R1", "station", f"{name}駅", [0])


def test_line_names_drop_the_route_number_and_find_lines_in_text() -> None:
    assert LINE_GAZ.lines_of("根津") == {"千代田線"}
    assert LINE_GAZ.lines_of("新宿") == {"山手線", "中央線"}
    assert LINE_GAZ.line_names("千代田線 また遅延") == {"千代田線"}
    assert LINE_GAZ.line_names("電車混んでる") == set()


def test_r4_finds_the_line_of_the_station_from_one_mention() -> None:
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.ROUTINE_TEXT, "千代田線また遅延"),
        _clue("p3", ClueType.PLACE_TEXT, "山手線"),
    ]

    got = rule_r4(clues, [_station_conclusion("根津")], LINE_GAZ)

    assert got == [Conclusion("R4", "line", "千代田線", [1], got[0].note)]
    assert "根津駅" in got[0].note


def test_r4_without_station_needs_the_line_in_several_posts() -> None:
    once = [_clue("p1", ClueType.PLACE_TEXT, "中央線")]
    twice = [*once, _clue("p2", ClueType.ROUTINE_TEXT, "中央線止まってる")]
    same_post = [*once, _clue("p1", ClueType.ROUTINE_TEXT, "中央線止まってる")]

    assert rule_r4(once, [], LINE_GAZ) == []
    assert rule_r4(same_post, [], LINE_GAZ) == []
    assert [(c.value, c.clue_indices) for c in rule_r4(twice, [], LINE_GAZ)] == [("中央線", [0, 1])]


def test_r4_ignores_lines_in_clue_types_that_are_not_text_or_signs() -> None:
    clues = [
        _clue("p1", ClueType.SHOP, "千代田線ラーメン"),
        _clue("p2", ClueType.SHOP, "千代田線ラーメン"),
    ]

    assert rule_r4(clues, [_station_conclusion("根津")], LINE_GAZ) == []


def test_infer_adds_the_line_after_the_station() -> None:
    gaz = Gazetteer(
        stations=[*GAZ.stations, *LINE_GAZ.stations], postal=GAZ.postal, muni_meshes=GAZ.muni_meshes
    )
    posts = [
        _post("p1", "2026-10-19 08:10"),
        _post("p2", "2026-10-21 08:40"),
        _post("p3", "2026-10-24 15:00"),
    ]
    clues = [
        _clue("p1", ClueType.STATION_SIGN, "根x"),
        _clue("p2", ClueType.POSTAL_CODE, "113-00xx"),
        _clue("p3", ClueType.ROUTINE_TEXT, "千代田線遅延"),
    ]

    got = _by_attribute(infer(clues, posts, gaz))

    assert got["station"].value == "根津駅"
    assert got["line"].value == "千代田線"


# ---- R5 名前・R6 年齢・R7 学校 ----


def test_r5_reads_a_full_name_from_an_address_label() -> None:
    clues = [
        _clue("p1", ClueType.NAME_TEXT, "内藤 大貴 様"),
        _clue("p2", ClueType.NAME_TEXT, "内藤　大貴さん"),
        _clue("p3", ClueType.NAME_TEXT, "だいき"),
    ]

    got = _by_attribute(rule_r5(clues))

    assert got["full_name"].value == "内藤大貴"
    assert got["full_name"].clue_indices == [0, 1]
    assert got["given_name_or_nickname"].value == "だいき"


def test_r5_treats_three_or_more_kanji_without_a_space_as_a_full_name() -> None:
    assert (
        _by_attribute(rule_r5([_clue("p1", ClueType.NAME_TEXT, "内藤大貴")]))["full_name"].value
        == "内藤大貴"
    )
    assert set(_by_attribute(rule_r5([_clue("p1", ClueType.NAME_TEXT, "大貴")]))) == {
        "given_name_or_nickname"
    }


def test_r5_skips_names_with_unreadable_characters() -> None:
    assert rule_r5([_clue("p1", ClueType.NAME_TEXT, "xx はるき 様")]) == []


def test_r5_does_not_decide_between_names_that_tie() -> None:
    clues = [
        _clue("p1", ClueType.NAME_TEXT, "内藤 大貴"),
        _clue("p2", ClueType.NAME_TEXT, "山田 花子"),
    ]

    assert rule_r5(clues) == []


def test_r6_takes_the_age_from_the_latest_post() -> None:
    posts = [_post("p1", "2025-10-17 21:00"), _post("p2", "2026-10-17 21:00")]
    clues = [
        _clue("p1", ClueType.AGE_TEXT, "24歳になりました"),
        _clue("p2", ClueType.AGE_TEXT, "25歳になりました"),
    ]

    assert rule_r6(clues, posts) == [
        Conclusion("R6", "age", "25歳（2026年10月の投稿）", [1], "本文の年齢と投稿の日付")
    ]


def test_r6_needs_a_number_of_years() -> None:
    posts = [_post("p1", "2026-10-17 21:00")]

    assert rule_r6([_clue("p1", ClueType.AGE_TEXT, "誕生日")], posts) == []


def test_r7_reads_school_names_only() -> None:
    clues = [
        _clue("p1", ClueType.ORG_TEXT, "東京xx大学"),
        _clue("p2", ClueType.ORG_TEXT, "筑波大学"),
        _clue("p3", ClueType.ORG_TEXT, "筑波大学"),
        _clue("p4", ClueType.ORG_TEXT, "赤札堂"),
    ]

    assert rule_r7(clues) == [
        Conclusion("R7", "school", "筑波大学", [1, 2], "学校の名前の手がかり")
    ]


def test_r3_keeps_the_words_short_but_all_evidence() -> None:
    posts = [_post(f"p{n}", f"2026-10-{17 + 7 * n:02d} 19:{10 * n:02d}") for n in range(3)]
    clues = [
        _clue("p0", ClueType.ROUTINE_TEXT, "夜勤前"),
        _clue("p0", ClueType.ROUTINE_TEXT, "電車混んでる"),
        _clue("p1", ClueType.ROUTINE_TEXT, "朝から電車混んでる"),
        _clue("p1", ClueType.ROUTINE_TEXT, "夜勤明け"),
        _clue("p2", ClueType.ROUTINE_TEXT, "電車混んでる"),
    ]

    (got,) = rule_r3(clues, posts)

    assert got.value == "毎週土曜 19時ごろに出かけている（電車混んでる・夜勤前）"
    assert got.clue_indices == [0, 1, 2, 3, 4]


def test_r3_leaves_out_empty_parentheses() -> None:
    posts = [_post(f"p{n}", f"2026-10-{17 + 7 * n:02d} 19:00") for n in range(3)]

    (got,) = rule_r3([], posts)

    assert got.value == "毎週土曜 19時ごろに出かけている"
