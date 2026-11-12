"""国土数値情報のバス停留所（令和4年度版）を「X は Y にある」の知識として使う、居住地域の経路。"""

from datetime import datetime

from tkb_common.schemas import Clue, ClueSource, ClueType, Post, ProfileAttribute, ProfileItem
from tkb_engine.cross_post import infer_owner_claims, recalculate_after_deletion
from tkb_engine.gazetteer import Gazetteer


def post(key: str, text: str) -> Post:
    return Post(
        post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}",
        text=text,
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )


def clue(p: Post, value: str, kind: ClueType = ClueType.PLACE_TEXT) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=None,
        type=kind,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def stop(name: str, operator: str, *cities: str) -> dict[str, object]:
    return {
        "name": name,
        "operator": operator,
        "muni_codes": [f"m{i}" for i, _ in enumerate(cities)],
        "cities": list(cities),
        "lat": 35.7,
        "lon": 139.7,
        "mesh_1km": "53394640",
    }


GAZ = Gazetteer(
    bus_stops=[
        stop("根津一丁目", "東京都", "文京区"),
        stop("根津一丁目", "京成バス（株）", "松戸市"),
        stop("境目坂上", "京王バス（株）", "新宿区", "渋谷区"),
    ]
)


def residence(claims: list[ProfileItem]) -> ProfileItem | None:
    return next((c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA), None)


def test_gazetteer_finds_the_bus_stop_named_at_the_start() -> None:
    assert set(GAZ.bus_stops_named_at("根津一丁目バス停")) == {"根津一丁目"}
    assert len(GAZ.bus_stops_named_at("根津一丁目")["根津一丁目"]) == 2
    assert GAZ.bus_stops_named_at("西根津一丁目") == {}


def test_owner_stop_and_operator_in_another_post_give_the_city() -> None:
    anchor = post("a", "家の前のバス停、根津一丁目。雨の日は助かる")
    ride = post("b", "都営バスの根津一丁目から乗った")
    claims = infer_owner_claims([anchor, ride], [clue(ride, "都営バス 根津一丁目")], gazetteer=GAZ)

    claim = residence(claims)
    assert claim is not None
    assert claim.value == "文京区"
    cited = [r for r in claim.evidence_paths[0].evidence if r.source == "open_data"]
    assert len(cited) == 1
    excerpt = cited[0].excerpt or ""
    assert "国土数値情報（バス停留所データ）" in excerpt
    assert "令和4年度" in excerpt
    assert "根津一丁目（都営バス）は文京区" in excerpt
    assert "35.7" not in excerpt


def test_daily_ride_phrase_is_an_owner_relation() -> None:
    anchor = post("a", "毎朝、根津一丁目バス停からバスに乗る")
    sign = post("b", "根津一丁目の時刻表が変わってた。都バス不便")
    claims = infer_owner_claims([anchor, sign], [clue(sign, "根津一丁目")], gazetteer=GAZ)
    claim = residence(claims)
    assert claim is not None
    assert claim.value == "文京区"


def test_same_name_without_operator_or_city_gives_nothing() -> None:
    anchor = post("a", "家の前のバス停、根津一丁目")
    ride = post("b", "根津一丁目から乗った")
    claims = infer_owner_claims([anchor, ride], [clue(ride, "根津一丁目")], gazetteer=GAZ)
    assert residence(claims) is None


def test_a_city_named_in_the_clues_also_narrows_the_stop() -> None:
    anchor = post("a", "家の前のバス停、境目坂上")
    ride = post("b", "境目坂上のバス、渋谷区のコミュニティバスと間違えた")
    claims = infer_owner_claims(
        [anchor, ride], [clue(ride, "境目坂上"), clue(ride, "渋谷区")], gazetteer=GAZ
    )
    claim = residence(claims)
    assert claim is not None
    assert claim.value == "渋谷区"


def test_a_stop_on_a_municipal_border_needs_more_than_the_operator() -> None:
    anchor = post("a", "家の前のバス停、境目坂上。京王バス")
    ride = post("b", "境目坂上から乗った")
    claims = infer_owner_claims([anchor, ride], [clue(ride, "境目坂上")], gazetteer=GAZ)
    assert residence(claims) is None


def test_either_post_alone_gives_nothing_and_deletion_breaks_it() -> None:
    anchor = post("a", "家の前のバス停、根津一丁目。都営バス")
    ride = post("b", "根津一丁目から乗った")
    assert residence(infer_owner_claims([anchor], [], gazetteer=GAZ)) is None
    claim = residence(infer_owner_claims([anchor, ride], [clue(ride, "根津一丁目")], gazetteer=GAZ))
    assert claim is not None
    assert recalculate_after_deletion(claim, {ride.post_id}) is None


def test_a_visit_is_not_an_owner_relation() -> None:
    anchor = post("a", "友達の家に遊びに行った。家の前のバス停、根津一丁目。都営バス")
    ride = post("b", "根津一丁目から乗った")
    claims = infer_owner_claims([anchor, ride], [clue(ride, "根津一丁目")], gazetteer=GAZ)
    assert residence(claims) is None


def test_without_the_bus_stop_table_nothing_changes() -> None:
    anchor = post("a", "家の前のバス停、根津一丁目。都営バス")
    ride = post("b", "根津一丁目から乗った")
    claims = infer_owner_claims([anchor, ride], [clue(ride, "根津一丁目")], gazetteer=Gazetteer())
    assert residence(claims) is None
