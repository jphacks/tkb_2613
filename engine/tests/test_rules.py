from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_common.schemas import TEXT_ONLY_TYPES, Clue, ClueSource, ClueType, Post
from tkb_engine import Conclusion, Gazetteer, infer, rule_r1, rule_r2, rule_r3
from tkb_engine.gazetteer import CollectionArea, Knowledge, TrashBag, University
from tkb_engine.rules import rule_r4, rule_r5, rule_r6, rule_r7, rule_r8, rule_r9, rule_r10

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

    assert got.value == "毎週火曜 20時ごろに出かけている（ジム・毎週火曜のジム）"
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
        ("R6", "home_block"),
        ("R2", "active_time"),
    ]


# ---- R4〜R10 ----

KNOW_GAZ = Gazetteer(
    stations=[
        {"station_name": "八王子", "mesh_1km": "m-hachioji"},
        {"station_name": "王子", "mesh_1km": "m-kita"},
    ],
    postal=[
        {"postal_code": "1920083", "muni_code": "13201", "city": "八王子市", "town": "旭町"},
        {"postal_code": "1140002", "muni_code": "13117", "city": "北区", "town": "王子"},
        {"postal_code": "1900012", "muni_code": "13202", "city": "立川市", "town": "曙町"},
    ],
    muni_meshes={"13201": {"m-hachioji"}, "13117": {"m-kita"}},
    knowledge=Knowledge(
        trash_bags=[
            TrashBag(city="八王子市", color="青", liters=40, count=10, price=750),
            TrashBag(city="立川市", color="青", liters=40, count=10, price=800),
        ],
        collection_areas=[
            CollectionArea(city="八王子市", area="A地区", burnable_days="水土"),
            CollectionArea(city="八王子市", area="B地区", burnable_days="月木"),
        ],
        universities=[
            University(
                name="X大学",
                campus="本校",
                city="八王子市",
                periods={1: (9.0, 10 + 40 / 60), 2: (10 + 50 / 60, 12.5)},
            ),
        ],
    ),
)


def test_r4_city_from_trash_bag_needs_matching_features() -> None:
    clues = [_clue("p1", ClueType.LOCAL_ITEM, "指定ゴミ袋 青 40L 10枚 750円")]
    assert [c.value for c in rule_r4(clues, KNOW_GAZ)] == ["八王子市"]
    # 値段がないと八王子市と立川市の両方に合うので決めない
    vague = [_clue("p1", ClueType.LOCAL_ITEM, "指定ゴミ袋 青 40L 10枚")]
    assert rule_r4(vague, KNOW_GAZ) == []


def test_r4_drops_conflicting_cities() -> None:
    clues = [
        _clue("p1", ClueType.LOCAL_ITEM, "指定ゴミ袋 青 40L 10枚 750円"),
        _clue("p2", ClueType.NOTICE, "立川市 資源ごみ"),
    ]
    assert rule_r4(clues, KNOW_GAZ) == []


def test_r5_reads_only_the_burnable_days() -> None:
    clues = [_clue("p1", ClueType.NOTICE, "八王子市 燃やさないごみ 月・木 / 燃やすごみ 水・土")]
    r4 = rule_r4(clues, KNOW_GAZ)
    assert [c.value for c in rule_r5(clues, KNOW_GAZ, r4)] == ["八王子市 A地区"]
    assert rule_r5(clues, KNOW_GAZ, []) == []


def test_r1_votes_for_a_station_written_in_a_shop_name() -> None:
    clues = [
        _clue("p1", ClueType.NOTICE, "八王子市 燃やすごみ 水・土"),
        _clue("p2", ClueType.REFLECTION, "向かいの看板「カフェ八王子駅前店」"),
    ]
    r4 = rule_r4(clues, KNOW_GAZ)
    station = _by_attribute(rule_r1(clues, KNOW_GAZ, r4))["station"]
    # 「王子」ではなく、いちばん長く合う「八王子」
    assert station.value == "八王子駅"
    assert station.clue_indices == [0, 1]
    # 市区町村で絞らなければ、根拠が1つで足りない
    assert rule_r1(clues[1:], KNOW_GAZ) == []


def test_r6_block_from_a_barcode_needs_a_known_postal_code() -> None:
    clues = [_clue("p1", ClueType.CODE, "伝票のバーコード 192-0083 9-3")]
    assert [c.value for c in rule_r6(clues, KNOW_GAZ)] == ["八王子市旭町 9-3 付近"]
    unknown = [_clue("p1", ClueType.CODE, "伝票のバーコード 999-9999 9-3")]
    assert rule_r6(unknown, KNOW_GAZ) == []


def test_r7_school_needs_the_timetable_to_fit() -> None:
    posts = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 10:41")]
    clues = [
        _clue("p0", ClueType.NOTICE, "八王子市 燃やすごみ 水・土"),
        _clue("p1", ClueType.ROUTINE_TEXT, "歩いて大学行く"),
        _clue("p2", ClueType.ROUTINE_TEXT, "2限ねむい"),
    ]
    r4 = rule_r4(clues, KNOW_GAZ)
    school = rule_r7(clues, posts, KNOW_GAZ, r4)
    assert [c.value for c in school] == ["X大学 本校（歩いて通える所に住んでいる）"]
    late = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 13:30")]
    assert rule_r7(clues, late, KNOW_GAZ, r4) == []


def test_r8_name_combines_readings_and_drops_honorifics() -> None:
    weak = _clue("p2", ClueType.NAME_TEXT, "xx ハルキ 様").model_copy(update={"confidence": 0.45})
    clues = [_clue("p1", ClueType.NAME_TEXT, "Happy Birthday"), weak]
    assert rule_r8(clues) == []
    clues.append(_clue("p3", ClueType.NAME_TEXT, "はるきへ"))
    name = rule_r8(clues)[0]
    assert (name.value, name.clue_indices) == ("ハルキ", [1, 2])


def test_r9_age_from_a_number_or_a_first_legal_drink() -> None:
    posts = [_post("p1", "2026-10-22 21:30")]
    drink = [_clue("p1", ClueType.AGE_TEXT, "誕生日、やっと堂々と頼めた🍺")]
    assert [c.value for c in rule_r9(drink, posts)] == ["20歳（誕生日は10月22日ごろ）"]
    plain = [_clue("p1", ClueType.AGE_TEXT, "30歳の抱負")]
    assert [c.value for c in rule_r9(plain, posts)] == ["30歳"]
    assert rule_r9([_clue("p1", ClueType.AGE_TEXT, "誕生日")], posts) == []


def test_r10_occupation_needs_a_shift_or_two_outfits() -> None:
    boots = _clue("p1", ClueType.UNIFORM, "安全靴")
    assert rule_r10([boots]) == []
    night = _clue("p2", ClueType.ROUTINE_TEXT, "夜勤明け")
    assert [c.value for c in rule_r10([boots, night])] == ["夜勤のある現場仕事"]
