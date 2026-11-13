from datetime import datetime

from tkb_common.schemas import (
    Clue, ClueSource, ClueType, EvidencePathProvenance, Post, ProfileStatus, WebFact,
)
from tkb_engine.cross_post import (
    evaluate_profile_candidates,
    infer_owner_claims,
    infer_owner_claims_with_web,
    infer_web_employer_claim,
    recalculate_after_deletion,
)


def post(key: str, text: str) -> Post:
    return Post(
        post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}",
        text=text,
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )


def web_fact(key: str = "a", company: str = "青空社", status: str = "verified") -> WebFact:
    return WebFact.model_validate(
        {
            "id": key,
            "subject": "青空社",
            "relation": "legal_name_of",
            "object": company,
            "source_url": "https://example.org/company/training",
            "source_title": "架空の公式会社案内",
            "source_kind": "official_organization",
            "excerpt": f"青空社の正式名称は{company}です",
            "retrieved_at": "2026-11-10T10:00:00+09:00",
            "verification_status": status,
        }
    )


def test_web_employer_requires_two_posts_and_verified_entity_fact() -> None:
    anchor = post("a", "勤務先は青空社")
    bridge = post("b", "青空社の資料を整理")
    item = infer_web_employer_claim([anchor, bridge], [web_fact(company="株式会社青空")])
    assert item is not None and item.value == "株式会社青空"
    assert item.status is ProfileStatus.FOUND
    assert item.evidence_paths[0].provenance is EvidencePathProvenance.DIRECT_DISCLOSURE
    assert item.assessment.minimal_scope == "bluesky_plus_public_web"
    refs = item.evidence_paths[0].evidence
    assert {ref.post_id for ref in refs if ref.post_id} == {anchor.post_id, bridge.post_id}
    assert [ref.web_fact_id for ref in refs if ref.source == "public_web"] == ["a"]
    assert recalculate_after_deletion(item, {bridge.post_id}) is None
    assert infer_web_employer_claim([anchor], [web_fact()]) is None
    assert (
        infer_web_employer_claim(
            [anchor, bridge], [web_fact(company="株式会社青空", status="unverified")]
        )
        is None
    )


def test_web_employer_rejects_ambiguous_sources_and_visit_only() -> None:
    anchor = post("a", "勤務先は青空社")
    bridge = post("b", "青空社の資料を整理")
    assert (
        infer_web_employer_claim(
            [anchor, bridge],
            [
                web_fact(company="株式会社青空"),
                web_fact("b", company="合同会社青空"),
            ],
        )
        is None
    )
    assert infer_web_employer_claim([post("v", "青空社を訪問"), bridge], [web_fact()]) is None
    assert (
        infer_web_employer_claim(
            [post("g", "うちの会社の研修"), post("h", "研修の資料")], [web_fact()]
        )
        is None
    )


def test_web_employer_profile_anchor_still_needs_two_posts() -> None:
    first, second = post("a", "青空社の資料"), post("b", "青空社の案内")
    item = infer_web_employer_claim(
        [first, second], [web_fact(company="株式会社青空")], "勤務先は青空社"
    )
    assert item is not None
    assert {ref.post_id for ref in item.evidence_paths[0].evidence if ref.post_id} == {
        first.post_id,
        second.post_id,
    }
    assert (
        infer_web_employer_claim([first], [web_fact(company="株式会社青空")], "勤務先は青空社")
        is None
    )


def test_web_employer_path_remains_when_possessive_path_is_rejected() -> None:
    anchor = post("a", "うちの会社の青空社")
    bridge = post("b", "株式会社青空の青空社")
    web_anchor = post("c", "勤務先は青空社")
    web_support = post("d", "青空社の資料を整理")
    clue = Clue(
        post_id=bridge.post_id,
        image_index=None,
        type=ClueType.ORG_TEXT,
        value="株式会社青空",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    posts = [anchor, bridge, web_anchor, web_support]
    claims = infer_owner_claims_with_web(posts, [clue], [web_fact(company="株式会社青空")])
    item = next(claim for claim in claims if claim.attribute.value == "employer_name")
    assert infer_owner_claims(posts, [clue]) == []
    expected_post_sets = {
        frozenset({web_anchor.post_id, support.post_id})
        for support in (anchor, bridge, web_support)
    }
    actual_post_sets = {
        frozenset(ref.post_id for ref in path.evidence if ref.post_id is not None)
        for path in item.evidence_paths
    }
    assert actual_post_sets == expected_post_sets
    assert all(
        all(ref.required for ref in path.evidence)
        and sum(ref.source.value == "public_web" for ref in path.evidence) == 1
        for path in item.evidence_paths
    )
    assert item.assessment.minimal_scope == "bluesky_plus_public_web"
    surviving = recalculate_after_deletion(item, {bridge.post_id})
    assert surviving is not None
    assert surviving.assessment.minimal_scope == "bluesky_plus_public_web"
    assert len(surviving.evidence_paths) == 2
    assert all(
        bridge.post_id not in {ref.post_id for ref in path.evidence}
        for path in surviving.evidence_paths
    )
    assert recalculate_after_deletion(item, {web_anchor.post_id}) is None
    assert any(ref.web_fact_id for ref in item.evidence_paths[0].evidence)
    different_legal_name = infer_owner_claims_with_web(
        posts, [clue], [web_fact(company="別会社社")]
    )
    assert different_legal_name[0].value == "別会社社"


def test_web_employer_rejects_program_or_visit_relations_and_japanese_visit_context() -> None:
    anchor = post("a", "勤務先は青空社")
    bridge = post("b", "青空社の資料を整理")
    valid_fact = web_fact(company="株式会社青空")
    program_fact = valid_fact.model_copy(update={"relation": "organizes_program"})
    assert infer_web_employer_claim([anchor, bridge], [program_fact]) is None
    visiting_anchor = post("v", "うちの会社の青空社を見学しました")
    assert infer_web_employer_claim([visiting_anchor, bridge], [web_fact()]) is None
    assert infer_owner_claims([visiting_anchor, bridge], []) == []
    # A possessive phrase can name a subsidiary, program, or venue rather than the employer.
    assert infer_web_employer_claim([post("p", "うちの会社の青空社"), bridge], [web_fact()]) is None
    ordinary_anchor = post("a2", "うちの会社の青空研修")
    visiting_support = post("b2", "青空社の青空研修を見学しました")
    clue = Clue(
        post_id=visiting_support.post_id,
        image_index=None,
        type=ClueType.ORG_TEXT,
        value="青空社",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    assert infer_owner_claims([ordinary_anchor, visiting_support], [clue]) == []


def test_web_path_survives_deletion_of_rejected_possessive_support_post() -> None:
    direct_anchor = post("direct-anchor", "うちの会社の青空社")
    direct_support = post("direct-support", "株式会社青空の青空社")
    web_anchor = post("web-anchor", "勤務先は青空社")
    web_support = post("web-support", "青空社の採用情報を読む")
    clue = Clue(
        post_id=direct_support.post_id,
        image_index=None,
        type=ClueType.ORG_TEXT,
        value="株式会社青空",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    item = infer_owner_claims_with_web(
        [direct_anchor, direct_support, web_anchor, web_support],
        [clue],
        [web_fact(company="株式会社青空")],
    )[0]
    assert any(
        any(ref.source == "public_web" for ref in path.evidence) for path in item.evidence_paths
    )

    surviving = recalculate_after_deletion(item, {direct_support.post_id})
    assert surviving is not None
    assert surviving.value == "株式会社青空"
    assert surviving.assessment.minimal_scope == "bluesky_plus_public_web"
    assert all(
        direct_support.post_id not in {ref.post_id for ref in path.evidence}
        for path in surviving.evidence_paths
    )


def test_company_possessive_bridge_does_not_establish_owner_employment() -> None:
    anchor = post("anchor", "うちの会社の青空物流センター")
    photo = post("photo", "")
    ocr = Clue(
        post_id=photo.post_id,
        image_index=0,
        type=ClueType.ORG_TEXT,
        value="株式会社青空の青空物流センター",
        region=(12, 24, 360, 72),
        confidence=0.95,
        source=ClueSource.OCR,
    )

    assert infer_owner_claims([anchor, photo], [ocr]) == []


def test_multiple_independently_verified_employers_are_retained_as_candidates() -> None:
    blue_anchor, blue_bridge = post("blue-anchor", "勤務先は青空社"), post("blue-bridge", "青空社の資料")
    water_anchor, water_bridge = post("water-anchor", "勤務先は水色社"), post("water-bridge", "水色社の資料")
    water_fact = web_fact(key="water", company="株式会社水色").model_copy(update={"subject": "水色社"})
    claims = infer_owner_claims_with_web(
        [blue_anchor, blue_bridge, water_anchor, water_bridge], [],
        [web_fact(company="株式会社青空"), water_fact],
    )
    employer_claims = [claim for claim in claims if claim.attribute.value == "employer_name"]
    assert {claim.value for claim in employer_claims} == {"株式会社青空", "株式会社水色"}
    sets = evaluate_profile_candidates(claims, [blue_anchor, blue_bridge, water_anchor, water_bridge])
    employers = next(item for item in sets if item.attribute.value == "employer_name")
    assert employers.status.value == "ambiguous"
    assert [candidate.rank for candidate in employers.candidates] == [1, 2]
