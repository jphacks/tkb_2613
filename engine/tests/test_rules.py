import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_common.schemas import TEXT_ONLY_TYPES, Clue, ClueSource, ClueType, Post
from tkb_engine import Conclusion, Gazetteer, infer, rule_r1, rule_r2, rule_r3
from tkb_engine.gazetteer import CollectionArea, Knowledge, TrashBag, University
from tkb_engine.rules import (
    rule_birthday,
    rule_r4,
    rule_r5,
    rule_r6,
    rule_r7,
    rule_r8,
    rule_r9,
    rule_r10,
    rule_r11,
    rule_x1,
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
        source=(
            ClueSource.TEXT
            if from_text
            else ClueSource.OCR
            if type_ is ClueType.CODE
            else ClueSource.VLM
        ),
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
            TrashBag(city="八王子市", liters=40, price=75),
            TrashBag(city="三鷹市", liters=40, price=75, color="黄"),
            TrashBag(city="立川市", liters=40, price=80),
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


def test_r4_city_from_trash_bag_compares_the_price_per_bag() -> None:
    # 1枚 75円は八王子市と三鷹市。三鷹市の袋は黄色なので、青い袋なら八王子市
    blue = [_clue("p1", ClueType.LOCAL_ITEM, "指定ゴミ袋 青 40L 10枚 750円")]
    assert [c.value for c in rule_r4(blue, KNOW_GAZ)] == ["八王子市"]
    # 色が分からなければ2つに合うので決めない
    plain = [_clue("p1", ClueType.LOCAL_ITEM, "指定ゴミ袋 40L 10枚 750円")]
    assert rule_r4(plain, KNOW_GAZ) == []
    # 袋に市の名前が書いてあれば、それで決まる
    named = [_clue("p1", ClueType.LOCAL_ITEM, "八王子市指定収集袋 40L 10枚 750円")]
    assert [c.value for c in rule_r4(named, KNOW_GAZ)] == ["八王子市"]
    # 1枚 80円は立川市だけ
    single = [_clue("p1", ClueType.LOCAL_ITEM, "指定収集袋 40L 5枚入 400円")]
    assert [c.value for c in rule_r4(single, KNOW_GAZ)] == ["立川市"]


def test_r4_drops_conflicting_cities() -> None:
    clues = [
        _clue("p1", ClueType.LOCAL_ITEM, "八王子市指定収集袋 40L"),
        _clue("p2", ClueType.NOTICE, "立川市 資源ごみ"),
    ]
    assert rule_r4(clues, KNOW_GAZ) == []


def test_r5_reads_only_the_burnable_days() -> None:
    clues = [_clue("p1", ClueType.NOTICE, "八王子市 燃やさないごみ 月・木 / 燃やすごみ 水・土")]
    r4 = rule_r4(clues, KNOW_GAZ)
    assert [c.value for c in rule_r5(clues, KNOW_GAZ, r4)] == ["八王子市 A地区"]
    assert rule_r5(clues, KNOW_GAZ, []) == []


def test_r5_keeps_districts_with_unknown_days_and_narrows_by_town() -> None:
    gaz = Gazetteer(
        postal=KNOW_GAZ.postal,
        knowledge=Knowledge(
            collection_areas=[
                CollectionArea("八王子市", "地区8", "月木", ["旭町", "南大沢1丁目"]),
                CollectionArea("八王子市", "地区9", "", ["新町", "南大沢2丁目"]),
                CollectionArea("八王子市", "地区10", "火金", ["天神町"]),
            ],
        ),
    )
    notice = _clue("p1", ClueType.NOTICE, "八王子市 燃やすごみ 月・木")
    r4 = [Conclusion("R4", "home_city", "八王子市", [9])]
    # 地区9は曜日が分からないので、まだ候補に残る
    assert [c.value for c in rule_r5([notice], gaz, r4)] == ["八王子市 燃やすごみが月・木の地区"]
    mail = _clue("p2", ClueType.CODE, "カスタマバーコード: 〒192-0083 住所表示番号 9-3")
    district = rule_r5([notice, mail], gaz, r4)[0]
    assert (district.value, district.clue_indices) == ("八王子市 地区8", [0, 1, 9])


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
    clues = [_clue("p1", ClueType.CODE, "カスタマバーコード: 〒192-0083 住所表示番号 9-3")]
    assert [c.value for c in rule_r6(clues, KNOW_GAZ)] == ["八王子市旭町 9-3 付近"]
    unknown = [_clue("p1", ClueType.CODE, "カスタマバーコード: 〒999-9999 住所表示番号 9-3")]
    assert rule_r6(unknown, KNOW_GAZ) == []
    # 宅配伝票の追跡番号は、郵便番号のように見えても使わない
    tracking = [_clue("p1", ClueType.CODE, "Codabar: A1920083000193A")]
    assert rule_r6(tracking, KNOW_GAZ) == []


# 手がかりのない投稿。投稿の日付を3日に散らばらせ、時刻を推理に使えるようにする
OTHER_DAYS = [_post("d1", "2026-10-21 12:00"), _post("d2", "2026-10-23 12:00")]


def test_r7_school_needs_the_timetable_to_fit() -> None:
    posts = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 10:41"), *OTHER_DAYS]
    clues = [
        _clue("p0", ClueType.NOTICE, "八王子市 燃やすごみ 水・土"),
        _clue("p1", ClueType.ROUTINE_TEXT, "歩いて大学行く"),
        _clue("p2", ClueType.ROUTINE_TEXT, "2限ねむい"),
    ]
    r4 = rule_r4(clues, KNOW_GAZ)
    school = rule_r7(clues, posts, KNOW_GAZ, r4)
    assert [c.value for c in school] == ["X大学 本校・歩いて通学"]
    late = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 13:30"), *OTHER_DAYS]
    assert rule_r7(clues, late, KNOW_GAZ, r4) == []
    # 同じ日にまとめて投稿したなら時刻は使わず、市区町村の大学だけで決める
    same_day = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 13:30")]
    school = rule_r7(clues, same_day, KNOW_GAZ, r4)
    assert [(c.value, c.note) for c in school] == [
        ("X大学 本校・歩いて通学", "八王子市にある大学はここだけ")
    ]


def test_r7_school_from_a_name_in_a_photo() -> None:
    gaz = Gazetteer(
        schools=[
            {"name": "東京都立立川高等学校", "kind": "高等学校", "city": "立川市"},
            {"name": "東京都立立川国際中等教育学校", "kind": "中等教育学校", "city": "立川市"},
            {"name": "中央大学", "kind": "大学", "city": "八王子市"},
        ]
    )
    badge = [_clue("p1", ClueType.UNIFORM, "制服の校章と「立川高校」の文字")]
    assert [c.value for c in rule_r7(badge, [], gaz, [])] == ["東京都立立川高等学校（立川市）"]
    # 「立川高島屋」は学校ではない
    shop = [_clue("p1", ClueType.LANDMARK, "立川高島屋")]
    assert rule_r7(shop, [], gaz, []) == []


def test_r7_lists_candidates_when_the_timetable_cannot_decide() -> None:
    gaz = Gazetteer(
        knowledge=KNOW_GAZ.knowledge,
        schools=[
            {"name": "X大学", "kind": "大学", "city": "八王子市"},
            {"name": "Y大学", "kind": "大学", "city": "八王子市"},
        ],
    )
    posts = [_post("p1", "2026-10-19 08:05"), _post("p2", "2026-10-19 10:41")]
    clues = [
        _clue("p1", ClueType.ROUTINE_TEXT, "大学行く"),
        _clue("p2", ClueType.ROUTINE_TEXT, "2限ねむい"),
    ]
    r4 = [Conclusion("R4", "home_city", "八王子市", [])]
    # Y大学は時間割が分からないので候補に残る
    got = rule_r7(clues, posts, gaz, r4)
    assert [c.value for c in got] == ["八王子市内の大学（2校のどれか）"]


def test_r8_name_combines_readings_and_drops_honorifics() -> None:
    weak = _clue("p2", ClueType.NAME_TEXT, "xx ハルキ 様").model_copy(update={"confidence": 0.45})
    clues = [_clue("p1", ClueType.NAME_TEXT, "Happy Birthday"), weak]
    assert rule_r8(clues) == []
    clues.append(_clue("p3", ClueType.NAME_TEXT, "はるきへ"))
    name = rule_r8(clues)[0]
    assert (name.value, name.clue_indices) == ("はるき", [2])


def test_r9_age_from_a_number_or_a_first_legal_drink() -> None:
    posts = [_post("p1", "2026-10-22 21:30"), *OTHER_DAYS]
    drink = [_clue("p1", ClueType.AGE_TEXT, "誕生日、やっと堂々と頼めた🍺")]
    assert [c.value for c in rule_r9(drink, posts)] == ["20歳（誕生日は10月22日ごろ）"]
    # 同じ日にまとめて投稿したなら、投稿日を誕生日にしない
    assert [c.value for c in rule_r9(drink, posts[:1])] == ["20歳"]
    seijin = [_clue("p1", ClueType.AGE_TEXT, "成人式の前撮り")]
    assert [c.value for c in rule_r9(seijin, posts)] == ["19〜20歳"]
    plain = [_clue("p1", ClueType.AGE_TEXT, "30歳の抱負")]
    assert [c.value for c in rule_r9(plain, posts)] == ["30歳"]
    assert rule_r9([_clue("p1", ClueType.AGE_TEXT, "誕生日")], posts) == []


def test_r10_occupation_needs_a_shift_or_two_outfits() -> None:
    boots = _clue("p1", ClueType.UNIFORM, "安全靴")
    assert rule_r10([boots]) == []
    night = _clue("p2", ClueType.ROUTINE_TEXT, "夜勤明け")
    assert [c.value for c in rule_r10([boots, night])] == ["夜勤のある現場仕事"]


DIST_GAZ = Gazetteer(
    stations=[
        {"station_name": "八王子", "mesh_1km": "m-h", "lat": 35.6558, "lon": 139.3389},
        {"station_name": "三鷹", "mesh_1km": "m-m", "lat": 35.7027, "lon": 139.5607},
        {"station_name": "中野", "mesh_1km": "m-n", "lat": 35.7056, "lon": 139.6659},
        {"station_name": "東中野", "mesh_1km": "m-n", "lat": 35.7067, "lon": 139.6826},
    ],
    postal=[
        {"postal_code": "1920083", "muni_code": "13201", "city": "八王子市", "town": "旭町"},
        {"postal_code": "1810013", "muni_code": "13204", "city": "三鷹市", "town": "下連雀"},
    ],
    muni_meshes={"13201": {"m-h"}, "13204": {"m-m"}},
    knowledge=Knowledge(
        trash_bags=[
            TrashBag(city="八王子市", liters=40, price=75),
            TrashBag(city="三鷹市", liters=40, price=75),
        ]
    ),
)


def _with_text(post_id: str, text: str) -> Post:
    return _post(post_id, "2026-10-20 22:05").model_copy(update={"text": text})


def test_r4_far_and_near_hints_pick_one_of_the_bag_cities() -> None:
    bag = _clue("p1", ClueType.LOCAL_ITEM, "指定収集袋 40L 10枚 750円")
    nakano = _clue("p2", ClueType.PLACE_TEXT, "中野")
    assert rule_r4([bag], DIST_GAZ) == []

    far = rule_r4([bag, nakano], DIST_GAZ, [_with_text("p2", "中野とか遠くてだるい")])
    assert [(c.value, c.clue_indices) for c in far] == [("八王子市", [0, 1])]
    assert "三鷹市から約10km" in far[0].note

    near = rule_r4([bag, nakano], DIST_GAZ, [_with_text("p2", "中野ならすぐ行ける")])
    assert [c.value for c in near] == ["三鷹市"]
    # 遠い・近いの言葉がなければ使わない
    plain = rule_r4([bag, nakano], DIST_GAZ, [_with_text("p2", "中野で飲み")])
    assert plain == []


def test_stations_named_in_prefers_the_longer_name() -> None:
    assert DIST_GAZ.stations_named_in("東中野まで遠い") == {"東中野"}
    assert DIST_GAZ.stations_named_in("中野まで遠い") == {"中野"}


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

    got = rule_r11(clues, [_station_conclusion("根津")], LINE_GAZ)

    assert got == [Conclusion("R11", "line", "千代田線", [1], got[0].note)]
    assert "根津駅" in got[0].note


def test_r4_without_station_needs_the_line_in_several_posts() -> None:
    once = [_clue("p1", ClueType.PLACE_TEXT, "中央線")]
    twice = [*once, _clue("p2", ClueType.ROUTINE_TEXT, "中央線止まってる")]
    same_post = [*once, _clue("p1", ClueType.ROUTINE_TEXT, "中央線止まってる")]

    assert rule_r11(once, [], LINE_GAZ) == []
    assert rule_r11(same_post, [], LINE_GAZ) == []
    assert [(c.value, c.clue_indices) for c in rule_r11(twice, [], LINE_GAZ)] == [
        ("中央線", [0, 1])
    ]


def test_r4_ignores_lines_in_clue_types_that_are_not_text_or_signs() -> None:
    clues = [
        _clue("p1", ClueType.SHOP, "千代田線ラーメン"),
        _clue("p2", ClueType.SHOP, "千代田線ラーメン"),
    ]

    assert rule_r11(clues, [_station_conclusion("根津")], LINE_GAZ) == []


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


def test_r8_joins_a_family_name_and_a_given_name_from_different_posts() -> None:
    board = _clue("p1", ClueType.NAME_TEXT, "在室表の名札「内藤」").model_copy(
        update={"confidence": 0.85}
    )
    cake = _clue("p2", ClueType.NAME_TEXT, "ケーキのプレート「大貴くん おめでとう」")
    got = rule_r8([board, cake])
    assert [(c.value, c.clue_indices) for c in got] == [("内藤大貴", [0, 1])]
    assert [c.value for c in rule_r8([cake])] == ["大貴"]


def test_r7_campus_from_a_lab_post_and_its_nearest_station() -> None:
    gaz = Gazetteer(
        stations=[{"station_name": "運河", "mesh_1km": "m-n", "lat": 35.91, "lon": 139.91}],
        knowledge=Knowledge(
            universities=[University("東京理科大学", "野田キャンパス", "野田市", {}, ["運河"])]
        ),
    )
    lab = _clue("p1", ClueType.ROUTINE_TEXT, "研究室に泊まり")
    platform = _clue("p2", ClueType.PLACE_TEXT, "運河")
    got = rule_r7([lab, platform], [], gaz, [])
    assert [(c.value, c.clue_indices) for c in got] == [("東京理科大学 野田キャンパス", [0, 1])]
    # どちらか片方だけでは決まらない
    assert rule_r7([lab], [], gaz, []) == []
    assert rule_r7([platform], [], gaz, []) == []


def test_r9_reads_the_age_from_a_birthday_post() -> None:
    posts = [_post("p1", "2026-10-25 13:00").model_copy(update={"text": "誕生日。今日で22"})]
    assert [c.value for c in rule_r9([_clue("p1", ClueType.AGE_TEXT, "今日で22")], posts)] == [
        "22歳"
    ]


# ---- R5 名前・R6 年齢・R7 学校 ----


def test_r5_reads_a_full_name_from_an_address_label() -> None:
    clues = [
        _clue("p1", ClueType.NAME_TEXT, "内藤 大貴 様"),
        _clue("p2", ClueType.NAME_TEXT, "内藤　大貴さん"),
        _clue("p3", ClueType.NAME_TEXT, "だいき"),
    ]

    got = _by_attribute(rule_r8(clues))

    assert got["full_name"].value == "内藤大貴"
    assert got["full_name"].clue_indices == [0, 1]
    assert got["given_name_or_nickname"].value == "だいき"


def test_r5_treats_three_or_more_kanji_without_a_space_as_a_full_name() -> None:
    assert (
        _by_attribute(rule_r8([_clue("p1", ClueType.NAME_TEXT, "内藤大貴")]))["full_name"].value
        == "内藤大貴"
    )
    assert set(_by_attribute(rule_r8([_clue("p1", ClueType.NAME_TEXT, "大貴")]))) == {
        "given_name_or_nickname"
    }


def test_r5_skips_names_with_unreadable_characters() -> None:
    assert rule_r8([_clue("p1", ClueType.NAME_TEXT, "xx はるき 様")]) == []


def test_r8_skips_birthday_decoration_and_age_even_from_existing_clues() -> None:
    clues = [
        _clue("p1", ClueType.NAME_TEXT, "HAPPY BIRTHDAY"),
        _clue("p1", ClueType.NAME_TEXT, "22"),
        _clue("p2", ClueType.NAME_TEXT, "内藤大貴"),
    ]

    assert [(c.attribute, c.value) for c in rule_r8(clues)] == [("full_name", "内藤大貴")]


def test_r5_does_not_decide_between_names_that_tie() -> None:
    clues = [
        _clue("p1", ClueType.NAME_TEXT, "内藤 大貴"),
        _clue("p2", ClueType.NAME_TEXT, "山田 花子"),
    ]

    assert rule_r8(clues) == []


def test_r6_takes_the_age_from_the_latest_post() -> None:
    posts = [_post("p1", "2025-10-17 21:00"), _post("p2", "2026-10-17 21:00")]
    clues = [
        _clue("p1", ClueType.AGE_TEXT, "24歳になりました"),
        _clue("p2", ClueType.AGE_TEXT, "25歳になりました"),
    ]

    assert rule_r9(clues, posts) == [Conclusion("R9", "age", "25歳", [1], "本文の年齢")]


def test_r6_needs_a_number_of_years() -> None:
    posts = [_post("p1", "2026-10-17 21:00")]

    assert rule_r9([_clue("p1", ClueType.AGE_TEXT, "誕生日")], posts) == []


def test_r7_reads_school_names_only() -> None:
    clues = [
        _clue("p1", ClueType.ORG_TEXT, "東京xx大学"),
        _clue("p2", ClueType.ORG_TEXT, "筑波大学"),
        _clue("p3", ClueType.ORG_TEXT, "筑波大学"),
        _clue("p4", ClueType.ORG_TEXT, "赤札堂"),
    ]

    assert rule_r7(clues, [], GAZ, []) == [
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


# ---- R8 生年月日 ----


def test_r8_takes_the_birthday_and_year_from_an_age_post() -> None:
    posts = [
        _post("p1", "2026-10-17 21:00"),
        _post("p2", "2026-10-18 21:00"),
        _post("p3", "2026-10-19 21:00"),
    ]

    got = rule_birthday([_clue("p1", ClueType.AGE_TEXT, "25歳になりました")], posts)

    assert got == [
        Conclusion("R12", "birthday", "2001年10月17日ごろ", [0], "本文の年齢と、誕生日の投稿の日付")
    ]


def test_r8_prefers_a_written_date_and_counts_a_birthday_not_yet_reached() -> None:
    posts = [_post("p1", "2026-10-17 21:00"), _post("p2", "2026-03-01 09:00")]
    clues = [
        _clue("p1", ClueType.AGE_TEXT, "誕生日"),
        _clue("p2", ClueType.AGE_TEXT, "4/12生まれ、いま24歳"),
    ]

    (got,) = rule_birthday(clues, posts)

    # 3/1 の投稿の時点で 4/12 はまだ来ていないので、いま 24 歳なら 2001 年生まれ
    assert got.value == "2001年4月12日ごろ"
    assert got.clue_indices == [1]


def test_r8_without_age_gives_only_month_and_day() -> None:
    posts = [
        _post("p1", "2026-10-17 21:00"),
        _post("p2", "2026-10-18 21:00"),
        _post("p3", "2026-10-19 21:00"),
    ]

    (got,) = rule_birthday([_clue("p1", ClueType.AGE_TEXT, "誕生日ケーキ")], posts)

    assert got.value == "10月17日ごろ"


def test_r8_ignores_ages_without_a_birthday_and_impossible_dates() -> None:
    posts = [_post("p1", "2026-10-17 21:00")]
    clues = [_clue("p1", ClueType.AGE_TEXT, "25歳"), _clue("p1", ClueType.AGE_TEXT, "13/45")]

    assert rule_birthday(clues, posts) == []


def test_r8_handles_two_clues_for_the_same_birthday_with_and_without_age() -> None:
    posts = [_post("p1", "2026-10-25 12:00")]
    clues = [
        _clue("p1", ClueType.AGE_TEXT, "10/17生まれ"),
        _clue("p1", ClueType.AGE_TEXT, "10/17生まれ、25歳"),
    ]

    assert rule_birthday(clues, posts) == [
        Conclusion("R12", "birthday", "2001年10月17日ごろ", [1], "本文の年齢と、誕生日の投稿の日付")
    ]


def test_r8_does_not_treat_a_same_day_demo_post_as_the_birthday() -> None:
    posts = [_post("p1", "2026-10-25 12:00"), _post("p2", "2026-10-25 12:03")]

    assert rule_birthday([_clue("p1", ClueType.AGE_TEXT, "22歳の誕生日")], posts) == []


def test_x1_joins_station_school_and_commute_from_separate_posts() -> None:
    posts = [
        _post("station1", "2026-10-20 08:00"),
        _post("station2", "2026-10-21 08:00"),
        _post("school", "2026-10-22 08:00"),
        _post("commute", "2026-10-23 08:00"),
    ]
    posts[3] = posts[3].model_copy(update={"text": "家から大学まで毎日通うと疲れる"})
    clues = [
        _clue("station1", ClueType.PLACE_TEXT, "根津駅"),
        _clue("station2", ClueType.PLACE_TEXT, "根津駅"),
        _clue("school", ClueType.ORG_TEXT, "筑波大学"),
        _clue("commute", ClueType.ROUTINE_TEXT, "毎日通学"),
    ]

    conclusions = infer(clues, posts, GAZ)
    cross = [c for c in conclusions if c.attribute == "home_school_commute"]

    assert len(cross) == 1
    assert cross[0].value == "根津駅付近から筑波大学へ通学している可能性"
    assert cross[0].clue_indices == [0, 1, 2, 3]
    for removed in ("station1", "school", "commute"):
        remaining = [c for c in clues if c.post_id != removed]
        assert not [c for c in infer(remaining, posts, GAZ) if c.attribute == "home_school_commute"]


def test_x1_does_not_join_a_school_and_commute_mentioned_only_in_one_post() -> None:
    clues = [
        _clue("station", ClueType.PLACE_TEXT, "根津駅"),
        _clue("same", ClueType.ORG_TEXT, "筑波大学"),
        _clue("same", ClueType.ROUTINE_TEXT, "家から大学に通っている"),
    ]
    conclusions = [
        Conclusion("R1", "station", "根津駅", [0], ""),
        Conclusion("R7", "school", "筑波大学", [1], ""),
    ]

    assert rule_x1(clues, [], conclusions) == []


def test_x1_demo_fixture_matches_the_published_post_texts() -> None:
    doc = json.loads(
        (Path(__file__).resolve().parents[2] / "eval/fixtures/demo_x1.json").read_text()
    )
    plan = json.loads(
        (Path(__file__).resolve().parents[2] / "eval/demo_account/x1_posts.json").read_text()
    )
    posts = [Post.model_validate(post) for post in doc["posts"]]
    clues = [Clue.model_validate(clue) for clue in doc["clues"]]

    assert [post.text for post in posts] == [item["text"] for item in plan["posts"]]
    cross = [c for c in infer(clues, posts, GAZ) if c.attribute == "home_school_commute"]
    assert len(cross) == 1
    assert cross[0].clue_indices == [0, 1, 2, 3]
