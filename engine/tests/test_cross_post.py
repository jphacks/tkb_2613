from datetime import datetime

from tkb_common.schemas import Clue, ClueSource, ClueType, Post, ProfileAttribute, ProfileStatus
from tkb_engine.cross_post import infer_owner_claims, recalculate_after_deletion


def post(key: str, text: str) -> Post:
    return Post(post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}", text=text,
                created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"), images=[])


def typed_clue(p: Post, value: str, kind: ClueType) -> Clue:
    return Clue(post_id=p.post_id, image_index=None, type=kind, value=value,
                region=None, confidence=0.9, source=ClueSource.TEXT)


def profile_clue(value: str, kind: ClueType) -> Clue:
    return Clue(post_id="profile:did:plc:owner", image_index=None, type=kind, value=value,
                region=None, confidence=0.9, source=ClueSource.PROFILE_TEXT)


def test_residential_claim_uses_landmark_bridge_across_two_posts() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    area = post("b", "青葉商店街は文京区")
    claims = infer_owner_claims([anchor, area], [typed_clue(area, "文京区", ClueType.PLACE_TEXT)])
    claim = next(c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert claim.value == "文京区"
    assert claim.status is ProfileStatus.WEAK
    assert len(claim.evidence_paths) == 1
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path} == {anchor.post_id, area.post_id}
    assert {ref.source for ref in path} == {"post_text", "clue"}


def test_employer_claim_uses_explicit_company_training_bridge() -> None:
    anchor = post("a", "うちの会社の青空研修")
    value = post("b", "青空社の青空研修")
    claims = infer_owner_claims([anchor, value], [typed_clue(value, "青空社", ClueType.ORG_TEXT)])
    claim = next(c for c in claims if c.attribute is ProfileAttribute.EMPLOYER_NAME)
    assert claim.value == "青空社"
    assert {ref.post_id for ref in claim.evidence_paths[0].evidence} == {anchor.post_id, value.post_id}


def test_residence_and_employer_claims_can_coexist() -> None:
    home_a, home_b = post("ha", "自宅近くの青葉商店街"), post("hb", "青葉商店街は文京区")
    work_a, work_b = post("wa", "うちの会社の青空研修"), post("wb", "青空社の青空研修")
    claims = infer_owner_claims([home_a, home_b, work_a, work_b], [
        typed_clue(home_b, "文京区", ClueType.PLACE_TEXT), typed_clue(work_b, "青空社", ClueType.ORG_TEXT),
    ])
    assert {item.attribute for item in claims} == {ProfileAttribute.RESIDENTIAL_AREA, ProfileAttribute.EMPLOYER_NAME}


def test_profile_text_owner_anchor_uses_two_posts_and_has_profile_evidence() -> None:
    bridge = post("bridge", "青葉商店街で買い物")
    value = post("value", "青葉商店街は文京区")
    claims = infer_owner_claims([bridge, value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)],
                               "自宅近くの青葉商店街")
    item = next(c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    refs = item.evidence_paths[0].evidence
    assert any(ref.source == "profile_text" and "自宅近く" in (ref.excerpt or "") for ref in refs)
    assert {ref.post_id for ref in refs if ref.post_id} == {bridge.post_id, value.post_id}
    assert recalculate_after_deletion(item, {bridge.post_id}) is None
    assert infer_owner_claims([value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)],
                              "自宅近くの青葉商店街") == []


def test_profile_text_typed_value_requires_two_post_supports() -> None:
    anchor = post("anchor", "うちの会社の青空研修")
    bridge = post("bridge", "青空研修の資料")
    profile_text = "青空社の青空研修"
    claim = infer_owner_claims([anchor, bridge], [], profile_text, [profile_clue("青空社", ClueType.ORG_TEXT)])
    item = next(c for c in claim if c.attribute is ProfileAttribute.EMPLOYER_NAME)
    assert any(ref.source == "profile_text" for ref in item.evidence_paths[0].evidence)
    assert {ref.post_id for ref in item.evidence_paths[0].evidence if ref.post_id} == {anchor.post_id, bridge.post_id}
    assert infer_owner_claims([anchor], [], profile_text, [profile_clue("青空社", ClueType.ORG_TEXT)]) == []


def test_single_post_station_visit_or_logo_never_proves_sensitive_claim() -> None:
    only = post("one", "自宅近くの根津駅。青葉商事を訪問")
    image = Clue(post_id=only.post_id, image_index=0, type=ClueType.ORG_TEXT,
                 value="青葉商事", region=None, confidence=0.99, source=ClueSource.VLM)
    assert infer_owner_claims([only], [image]) == []
    station_only = post("station", "根津駅に行った")
    assert infer_owner_claims([station_only], []) == []


def test_two_clues_or_two_phrases_in_one_post_are_not_independent_posts() -> None:
    only = post("one", "自宅近くの青葉商店街。青葉商店街は文京区")
    assert infer_owner_claims([only], [typed_clue(only, "文京区", ClueType.PLACE_TEXT)]) == []


def test_conflicting_values_on_same_bridge_are_rejected() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    one = post("b", "青葉商店街は文京区")
    two = post("c", "青葉商店街は台東区")
    assert infer_owner_claims([anchor, one, two], [typed_clue(one, "文京区", ClueType.PLACE_TEXT), typed_clue(two, "台東区", ClueType.PLACE_TEXT)]) == []


def test_generic_or_untyped_values_are_not_residential_or_employer_claims() -> None:
    home_a = post("ha", "自宅近くの青葉商店街")
    home_b = post("hb", "青葉商店街は楽しい")
    work_a = post("wa", "うちの会社の青空研修")
    work_b = post("wb", "友人の青空研修")
    assert infer_owner_claims([home_a, home_b, work_a, work_b], [
        typed_clue(home_b, "楽しい", ClueType.PLACE_TEXT),
        typed_clue(work_b, "友人", ClueType.ORG_TEXT),
    ]) == []


def test_generic_bridges_are_not_distinctive_names() -> None:
    employer_a = post("ga", "うちの会社の研修")
    employer_b = post("gb", "青空社の研修")
    home_a = post("ha", "自宅近くの商店街")
    home_b = post("hb", "商店街は文京区")
    assert infer_owner_claims([employer_a, employer_b, home_a, home_b], []) == []


def test_removing_a_required_post_breaks_the_path() -> None:
    anchor = post("a", "うちの会社の青空研修")
    value = post("b", "青空社の青空研修")
    item = infer_owner_claims([anchor, value], [typed_clue(value, "青空社", ClueType.ORG_TEXT)])[0]
    assert recalculate_after_deletion(item, {anchor.post_id}) is None


def test_alternative_evidence_paths_survive_partial_deletion_only() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    b, c = post("b", "青葉商店街は文京区"), post("c", "青葉商店街は文京区")
    clues = [typed_clue(b, "文京区", ClueType.PLACE_TEXT), typed_clue(c, "文京区", ClueType.PLACE_TEXT)]
    item = infer_owner_claims([anchor, b, c], clues)[0]
    assert len(item.evidence_paths) == 2
    after_one = recalculate_after_deletion(item, {b.post_id})
    assert after_one is not None and len(after_one.evidence_paths) == 1
    assert recalculate_after_deletion(item, {anchor.post_id}) is None
