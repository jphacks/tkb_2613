"""子どもの学校の推定（child_school）から、国土数値情報の学区で居住地域の経路を足す。"""

from tkb_common.schemas import (
    ClaimAssessment,
    EvidenceScope,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
)
from tkb_engine.cross_post import recalculate_after_deletion
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.open_data_school import add_school_district_residence

A = "at://did:plc:owner/app.bsky.feed.post/a"
B = "at://did:plc:owner/app.bsky.feed.post/b"
C = "at://did:plc:owner/app.bsky.feed.post/c"
NOTE = "地図データは参考情報とし、教育指導課へお問い合わせください。"


def district(
    name: str, city: str, kind: str = "小学校", terms: str = "オープンデータ公開", note: str = ""
) -> dict[str, object]:
    return {"kind": kind, "name": name, "city": city, "terms": terms, "note": note}


GAZ = Gazetteer(
    school_districts=[
        district("根津小学校", "文京区"),
        district("第一小学校", "八王子市"),
        district("第一小学校", "立川市"),
        district("篠津小学校", "白岡市", terms="条件公開", note=NOTE),
    ]
)


def item(attribute: ProfileAttribute, value: str, *posts: str) -> ProfileItem:
    refs = [
        ProfileEvidence(post_id=p, clue_index=None, required=True, source="post_text", excerpt="x")
        for p in posts
    ]
    return ProfileItem(
        attribute=attribute,
        value=value,
        confidence=0.65,
        status=ProfileStatus.WEAK,
        evidence=refs,
        evidence_paths=[ProfileEvidencePath(evidence=refs, confidence=0.65)],
        assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY),
    )


def residence(claims: list[ProfileItem]) -> ProfileItem | None:
    return next((c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA), None)


def test_gazetteer_finds_the_district_by_the_school_name() -> None:
    assert [r["city"] for r in GAZ.districts_of_school("文京区立根津小学校")] == ["文京区"]
    assert [r["city"] for r in GAZ.districts_of_school("根津小")] == ["文京区"]
    assert GAZ.districts_of_school("根津中学校") == []


def test_child_school_adds_the_district_city_as_a_residential_path() -> None:
    school = item(ProfileAttribute.CHILD_SCHOOL, "根津小学校", A, B)

    claims = add_school_district_residence([school], GAZ)

    claim = residence(claims)
    assert claim is not None
    assert claim.value == "文京区"
    path = claim.evidence_paths[0].evidence
    assert {r.post_id for r in path if r.post_id} == {A, B}
    cited = [r for r in path if r.source == "open_data"]
    assert len(cited) == 1
    assert "国土数値情報（小学校区データ）" in (cited[0].excerpt or "")
    assert "公式な資料ではありません" in (cited[0].excerpt or "")
    # 子どもの学校の推定そのものは残す
    assert any(c.attribute is ProfileAttribute.CHILD_SCHOOL for c in claims)


def test_the_municipal_condition_is_shown_with_the_citation() -> None:
    claims = add_school_district_residence(
        [item(ProfileAttribute.CHILD_SCHOOL, "篠津小学校", A, B)], GAZ
    )
    claim = residence(claims)
    assert claim is not None
    assert NOTE in (claim.evidence_paths[0].evidence[-1].excerpt or "")


def test_no_child_school_or_no_district_adds_nothing() -> None:
    assert add_school_district_residence([], GAZ) == []
    other = [item(ProfileAttribute.CHILD_SCHOOL, "どこかの小学校", A, B)]
    assert add_school_district_residence(other, GAZ) == other
    assert add_school_district_residence(other, Gazetteer()) == other


def test_same_school_name_in_two_cities_adds_nothing() -> None:
    claims = [item(ProfileAttribute.CHILD_SCHOOL, "第一小学校", A, B)]
    assert residence(add_school_district_residence(claims, GAZ)) is None


def test_it_merges_with_the_same_residence_and_drops_a_conflicting_one() -> None:
    school = item(ProfileAttribute.CHILD_SCHOOL, "根津小学校", A, B)
    same = item(ProfileAttribute.RESIDENTIAL_AREA, "文京区", C, A)
    merged = residence(add_school_district_residence([same, school], GAZ))
    assert merged is not None
    assert len(merged.evidence_paths) == 2

    other = item(ProfileAttribute.RESIDENTIAL_AREA, "台東区", C, A)
    assert residence(add_school_district_residence([other, school], GAZ)) is None


def test_deleting_a_child_school_post_breaks_the_district_path() -> None:
    claims = add_school_district_residence(
        [item(ProfileAttribute.CHILD_SCHOOL, "根津小学校", A, B)], GAZ
    )
    claim = residence(claims)
    assert claim is not None
    assert recalculate_after_deletion(claim, {A}) is None
