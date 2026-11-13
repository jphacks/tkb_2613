"""公開データ（事前に取得した手元の表）を「X は Y」の知識として使う推定経路。"""

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    Post,
    ProfileAttribute,
    ProfileCandidateSetStatus,
    ProfileItem,
    ProfileStatus,
)
from tkb_engine.cross_post import (
    evaluate_profile_candidates,
    infer_owner_claims,
    recalculate_after_deletion,
)
from tkb_engine.gazetteer import Gazetteer, shelter_name_variants


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


def shelter(name: str, city: str, muni: str) -> dict[str, object]:
    return {
        "name": name,
        "kind": "指定緊急避難場所・指定避難所",
        "muni_code": muni,
        "city": city,
        "lat": 35.72,
        "lon": 139.76,
        "mesh_1km": "53394640",
    }


GAZ = Gazetteer(
    shelters=[
        shelter("文京区立根津小学校", "文京区", "13105"),
        shelter("西小学校", "八王子市", "13201"),
        shelter("西小学校", "立川市", "13202"),
    ]
)


def residence(claims: list[ProfileItem]) -> ProfileItem | None:
    return next((c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA), None)


def test_shelter_name_variants_drop_the_municipal_prefix_and_the_building() -> None:
    assert "根津小学校" in shelter_name_variants("文京区立根津小学校体育館")
    assert "根津小学校" in shelter_name_variants("根津小学校（校庭）")
    # 短すぎる名前は手がかりの文字に合わせない
    assert not any(len(v) < 4 for v in shelter_name_variants("中央公園"))


def test_gazetteer_finds_the_shelter_named_at_the_start_of_a_text() -> None:
    found = GAZ.shelters_named_at("根津小学校が避難所になってる")
    assert {name: {r["city"] for r in rows} for name, rows in found.items()} == {
        "根津小学校": {"文京区"}
    }
    assert set(GAZ.shelters_named_at("文京区立根津小学校体育館")) == {"根津小学校"}
    assert set(GAZ.shelters_named_at("指定避難所 根津小学校")) == {"根津小学校"}
    assert GAZ.shelters_named_at("根津の小学校") == {}
    # 長い名前の一部（「新宿中央公園」の「中央公園」）には合わせない
    assert (
        Gazetteer(shelters=[shelter("中央公園", "小平市", "13211")]).shelters_named_at(
            "新宿中央公園"
        )
        == {}
    )


def test_a_shorter_shelter_name_inside_a_longer_place_name_is_not_used() -> None:
    gaz = Gazetteer(shelters=[shelter("中央公園", "小平市", "13211")])
    anchor = post("a", "家の前の新宿中央公園、桜がきれい")
    seen = post("b", "新宿中央公園で散歩")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "新宿中央公園")], gazetteer=gaz)
    assert residence(claims) is None


def test_shelter_and_owner_relation_in_two_posts_give_the_city() -> None:
    anchor = post("a", "自宅近くの根津小学校が避難所になってる。いざというときはここ")
    seen = post("b", "根津小学校の運動会、にぎやかだった")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "根津小学校")], gazetteer=GAZ)

    claim = residence(claims)
    assert claim is not None
    assert claim.value == "文京区"
    assert claim.status is ProfileStatus.WEAK
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path if ref.post_id} == {anchor.post_id, seen.post_id}
    cited = [ref for ref in path if ref.source == "open_data"]
    assert len(cited) == 1
    assert "国土地理院" in (cited[0].excerpt or "")
    assert "最新でない場合" in (cited[0].excerpt or "")
    # 座標や番地は出さない
    assert "35.72" not in (cited[0].excerpt or "")


def test_either_post_alone_gives_nothing() -> None:
    anchor = post("a", "自宅近くの根津小学校が避難所になってる")
    seen = post("b", "根津小学校の運動会")
    assert residence(infer_owner_claims([anchor], [], gazetteer=GAZ)) is None
    assert residence(infer_owner_claims([seen], [clue(seen, "根津小学校")], gazetteer=GAZ)) is None
    # 同じ投稿の中の手がかりは、別の投稿の代わりにならない
    both = post("c", "自宅近くの根津小学校が避難所")
    assert residence(infer_owner_claims([both], [clue(both, "根津小学校")], gazetteer=GAZ)) is None


def test_a_shelter_name_in_two_municipalities_is_not_used() -> None:
    anchor = post("a", "家の近くの西小学校が避難所")
    seen = post("b", "西小学校の前を通った")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "西小学校")], gazetteer=GAZ)
    assert residence(claims) is None


def test_a_visit_or_photo_without_owner_relation_is_not_used() -> None:
    visit = post("a", "根津小学校を見学した。近所の人が多かった")
    seen = post("b", "根津小学校の運動会")
    claims = infer_owner_claims(
        [visit, seen], [clue(visit, "根津小学校"), clue(seen, "根津小学校")], gazetteer=GAZ
    )
    assert residence(claims) is None
    # 関係を示す投稿が「訪問」の文脈なら使わない
    anchor = post("c", "近所の根津小学校に遊びに行った")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "根津小学校")], gazetteer=GAZ)
    assert residence(claims) is None


def test_without_the_shelter_table_nothing_changes() -> None:
    anchor = post("a", "自宅近くの根津小学校が避難所")
    seen = post("b", "根津小学校の運動会")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "根津小学校")], gazetteer=Gazetteer())
    assert residence(claims) is None


def test_deleting_either_post_breaks_the_claim() -> None:
    anchor = post("a", "自宅近くの根津小学校が避難所")
    seen = post("b", "根津小学校の運動会")
    claim = residence(infer_owner_claims([anchor, seen], [clue(seen, "根津小学校")], gazetteer=GAZ))
    assert claim is not None
    assert recalculate_after_deletion(claim, {anchor.post_id}) is None
    assert recalculate_after_deletion(claim, {seen.post_id}) is None


def test_a_conflicting_residential_value_remains_ambiguous() -> None:
    anchor = post("a", "自宅近くの根津小学校が避難所")
    seen = post("b", "根津小学校の運動会")
    street = post("c", "自宅近くの青葉商店街")
    other = post("d", "青葉商店街は台東区")
    posts = [anchor, seen, street, other]
    clues = [clue(seen, "根津小学校"), clue(other, "台東区")]
    claims = infer_owner_claims(posts, clues, gazetteer=GAZ)
    candidate_set = next(
        item
        for item in evaluate_profile_candidates(claims, posts, clues=clues)
        if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert candidate_set.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert {candidate.value for candidate in candidate_set.candidates} == {"文京区", "台東区"}


def test_load_reads_the_shelter_table_only_when_it_exists(tmp_path: Path) -> None:
    pq.write_table(
        pa.table({"muni_code": ["13105"], "mesh_1km": ["53394640"]}), tmp_path / "muni_mesh.parquet"
    )
    pq.write_table(
        pa.table({"station_name": ["根津"], "mesh_1km": ["53394640"]}),
        tmp_path / "stations.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "postal_code": ["1130031"],
                "muni_code": ["13105"],
                "city": ["文京区"],
                "town": ["根津"],
            }
        ),
        tmp_path / "postal.parquet",
    )
    assert Gazetteer.load(tmp_path).shelters == []

    pq.write_table(
        pa.Table.from_pylist([shelter("根津小学校", "文京区", "13105")]),
        tmp_path / "shelters.parquet",
    )
    assert [r["name"] for r in Gazetteer.load(tmp_path).shelters] == ["根津小学校"]


def test_different_spellings_of_the_same_shelter_still_bridge() -> None:
    anchor = post("a", "近所の文京区立根津小学校体育館が避難所")
    seen = post("b", "根津小学校の運動会")
    claims = infer_owner_claims([anchor, seen], [clue(seen, "根津小学校")], gazetteer=GAZ)
    claim = residence(claims)
    assert claim is not None
    assert claim.value == "文京区"
