from datetime import UTC, date, datetime, timedelta

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    EvidencePathProvenance,
    PhotoPlaceCandidate,
    PhotoPlaceEvidence,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceRelation,
    PhotoPlaceResult,
    PhotoPlaceSource,
    PhotoPlaceStatus,
    PhotoPlaceType,
    Post,
    PostImage,
    ProfileAttribute,
    ProfileCandidateSetStatus,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileRelation,
    ProfileRelationEndpoint,
    ProfileRelationEndpointKind,
    ProfileRelationKind,
    ProfileStatus,
)
from tkb_engine.cross_post import (
    evaluate_profile_candidates,
    infer_child_age_claim,
    infer_child_age_claims,
    infer_combined_regular_line_claims,
    infer_explicit_observation_claims,
    infer_home_nearest_station_claims,
    infer_owner_candidate_sets_with_web,
    infer_owner_claims,
    infer_owner_profile_relations,
    infer_realtime_location_claim,
    infer_regular_station_from_home_origin,
    infer_rule_and_link_claims,
    plan_profile_candidate_deletion,
    plan_profile_claim_deletion,
    profile_relations_after_deletion,
    recalculate_after_deletion,
    recalculate_profile_candidate_sets,
)
from tkb_engine.gazetteer import Gazetteer


def post(key: str, text: str) -> Post:
    return Post(
        post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}",
        text=text,
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )


def typed_clue(p: Post, value: str, kind: ClueType) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=None,
        type=kind,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def profile_clue(value: str, kind: ClueType) -> Clue:
    return Clue(
        post_id="profile:did:plc:owner",
        image_index=None,
        type=kind,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.PROFILE_TEXT,
    )


def photo_area_result(
    p: Post, clue_index: int, *, area: str = "\u6587\u4eac\u533a"
) -> PhotoPlaceResult:
    return PhotoPlaceResult(
        post_id=p.post_id,
        image_index=0,
        status=PhotoPlaceStatus.CANDIDATE,
        granularity=PhotoPlaceGranularity.FACILITY,
        lookup_status=PhotoPlaceLookupStatus.LOCAL_ONLY,
        candidates=[
            PhotoPlaceCandidate(
                place_id="poi:blue-market",
                label="\u9752\u8449\u5e02\u5834",
                place_type=PhotoPlaceType.LANDMARK,
                photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
                area_label=area,
                evidence=[PhotoPlaceEvidence(kind="clue", clue_index=clue_index)],
                source_ids=["local:poi:blue-market"],
                sources=[
                    PhotoPlaceSource(
                        source_id="local:poi",
                        provider="local",
                        dataset="licensed-poi",
                        license_id="CC-BY-4.0",
                    )
                ],
            )
        ],
    )


def shop_sign_clue(p: Post, value: str, *, confidence: float = 0.9) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=0,
        type=ClueType.SHOP,
        value=value,
        region=(10, 10, 200, 80),
        confidence=confidence,
        source=ClueSource.VLM,
    )


def frequent_shop_fixture(
    *,
    shop_a: str = "青葉珈琲 神保町店",
    shop_b: str | None = None,
    habit_text: str = "私は毎週神保町のこの店で昼食をとる",
    observation_text: str = "私は今日も神保町のこの店で休憩した",
    same_day: bool = False,
) -> tuple[list[Post], list[Clue]]:
    habit = photo_post("shop-habit", habit_text)
    observed = photo_post("shop-observed", observation_text)
    habit_date = datetime.fromisoformat("2026-10-18T12:00:00+09:00")
    observed_date = habit_date if same_day else datetime.fromisoformat("2026-10-20T12:00:00+09:00")
    habit = habit.model_copy(update={"created_at": habit_date})
    observed = observed.model_copy(update={"created_at": observed_date})
    clues = [
        typed_clue(habit, "私は毎週神保町のこの店で昼食をとる", ClueType.ROUTINE_TEXT),
        typed_clue(habit, "神保町", ClueType.PLACE_TEXT),
        shop_sign_clue(habit, shop_a),
        typed_clue(observed, "神保町", ClueType.PLACE_TEXT),
        shop_sign_clue(observed, shop_b or shop_a),
    ]
    return [habit, observed], clues


def school_org_clue(p: Post, value: str, *, confidence: float = 0.92) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=0,
        type=ClueType.ORG_TEXT,
        value=value,
        region=(20, 30, 220, 90),
        confidence=confidence,
        source=ClueSource.VLM,
    )


def workplace_photo_clues(
    p: Post, area: str = "文京区", *, with_area: bool = True, with_site: bool = True
) -> list[Clue]:
    clues = []
    if with_area:
        clues.append(
            Clue(
                post_id=p.post_id,
                image_index=0,
                type=ClueType.PLACE_TEXT,
                value=area,
                region=(10, 55, 150, 95),
                confidence=0.9,
                source=ClueSource.OCR,
            )
        )
    if with_site:
        clues.append(
            Clue(
                post_id=p.post_id,
                image_index=0,
                type=ClueType.ORG_TEXT,
                value="青空社 本社",
                region=(10, 10, 220, 50),
                confidence=0.9,
                source=ClueSource.VLM,
            )
        )
    return clues


def workplace_posts(
    anchor_text: str = "私は青空社の本社で働いている",
    attendance_text: str = "私は青空社の本社に出勤した",
) -> list[Post]:
    owner = post("work-owner", anchor_text)
    attendance = post("work-photo", attendance_text).model_copy(
        update={
            "images": [
                PostImage(
                    index=0,
                    url="https://cdn.bsky.app/img/feed_fullsize/example",
                    alt="",
                    width=640,
                    height=480,
                )
            ]
        }
    )
    return [owner, attendance]


def test_workplace_area_combines_explicit_employment_site_and_photo_area() -> None:
    posts = workplace_posts()
    claims = infer_owner_claims(posts, workplace_photo_clues(posts[1]))
    claim = next(item for item in claims if item.attribute is ProfileAttribute.WORKPLACE_AREA)
    assert claim.value == "文京区" and claim.status is ProfileStatus.WEAK
    path = claim.evidence_paths[0]
    assert path.provenance is EvidencePathProvenance.COMBINED_INFERENCE
    assert {ref.post_id for ref in path.evidence} == {item.post_id for item in posts}
    assert all(ref.required for ref in path.evidence)
    assert recalculate_after_deletion(claim, {posts[0].post_id}) is None
    assert recalculate_after_deletion(claim, {posts[1].post_id}) is None


def test_workplace_area_rejects_unbridged_visitors_third_party_quotes_and_direct_text() -> None:
    cases = [
        workplace_posts(attendance_text="私は青葉社の本社に出勤した"),
        workplace_posts(attendance_text="私は青空社の本社を訪問した"),
        workplace_posts(attendance_text="私は青空社の本社勤務で会議に出席した"),
        workplace_posts(attendance_text="友人は青空社の本社に出勤した"),
        workplace_posts(attendance_text="『私は青空社の本社に出勤した』"),
        workplace_posts(attendance_text="私は職場は文京区と投稿した。青空社の本社に出勤した"),
    ]
    for posts in cases:
        assert all(
            item.attribute is not ProfileAttribute.WORKPLACE_AREA
            for item in infer_owner_claims(posts, workplace_photo_clues(posts[1]))
        )


def test_workplace_area_rejects_employment_phrase_inside_visitor_relative_clause() -> None:
    posts = workplace_posts(
        anchor_text="私は青空社の本社で働く友人を訪ねた",
        attendance_text="私は青空社の本社に出勤した",
    )
    assert all(
        item.attribute is not ProfileAttribute.WORKPLACE_AREA
        for item in infer_owner_claims(posts, workplace_photo_clues(posts[1]))
    )


def test_workplace_area_requires_image_linked_area_and_same_image_org_site_clue() -> None:
    for with_area, with_site in ((False, True), (True, False)):
        posts = workplace_posts()
        assert all(
            item.attribute is not ProfileAttribute.WORKPLACE_AREA
            for item in infer_owner_claims(
                posts, workplace_photo_clues(posts[1], with_area=with_area, with_site=with_site)
            )
        )
    posts = workplace_posts()
    unrelated = workplace_photo_clues(posts[1])
    unrelated[0] = unrelated[0].model_copy(update={"image_index": 1})
    assert all(
        item.attribute is not ProfileAttribute.WORKPLACE_AREA
        for item in infer_owner_claims(posts, unrelated)
    )
    posts = workplace_posts()
    opposite_corners = workplace_photo_clues(posts[1])
    opposite_corners[0] = opposite_corners[0].model_copy(update={"region": (500, 400, 630, 450)})
    assert all(
        item.attribute is not ProfileAttribute.WORKPLACE_AREA
        for item in infer_owner_claims(posts, opposite_corners)
    )


def test_residential_claim_uses_landmark_bridge_across_two_posts() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    area = post("b", "青葉商店街は文京区")
    claims = infer_owner_claims([anchor, area], [typed_clue(area, "文京区", ClueType.PLACE_TEXT)])
    claim = next(c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert claim.value == "文京区"
    assert claim.status is ProfileStatus.WEAK
    assert len(claim.evidence_paths) == 1
    assert claim.evidence_paths[0].provenance is EvidencePathProvenance.COMBINED_INFERENCE
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path} == {anchor.post_id, area.post_id}
    assert {ref.source for ref in path} == {"post_text", "clue"}


def test_frequent_shop_requires_habit_and_same_distinctive_shop_branch_in_two_posts() -> None:
    posts, clues = frequent_shop_fixture()
    claims = infer_owner_claims(posts, clues)
    claim = next(item for item in claims if item.attribute is ProfileAttribute.FREQUENT_SHOP)
    assert claim.value == "青葉珈琲 神保町店"
    assert claim.status is ProfileStatus.WEAK
    assert claim.evidence_paths[0].provenance is EvidencePathProvenance.COMBINED_INFERENCE
    path = claim.evidence_paths[0].evidence
    assert {item.post_id for item in path} == {item.post_id for item in posts}
    assert len([item for item in path if item.source == "clue"]) == 5
    assert all(item.required for item in path)


def test_frequent_shop_rejects_insufficient_or_same_day_visits() -> None:
    one_shop_post, one_shop_clues = frequent_shop_fixture()
    assert all(
        item.attribute is not ProfileAttribute.FREQUENT_SHOP
        for item in infer_owner_claims(one_shop_post[:1], one_shop_clues[:3])
    )
    same_day_posts, same_day_clues = frequent_shop_fixture(same_day=True)
    assert all(
        item.attribute is not ProfileAttribute.FREQUENT_SHOP
        for item in infer_owner_claims(same_day_posts, same_day_clues)
    )


def test_frequent_shop_rejects_chain_ambiguous_and_unidentified_branches() -> None:
    chain_posts, chain_clues = frequent_shop_fixture(
        shop_a="スターバックス神保町店", shop_b="スターバックス神保町店"
    )
    no_branch_posts, no_branch_clues = frequent_shop_fixture(shop_a="青葉珈琲", shop_b="青葉珈琲")
    for posts, clues in ((chain_posts, chain_clues), (no_branch_posts, no_branch_clues)):
        assert all(
            item.attribute is not ProfileAttribute.FREQUENT_SHOP
            for item in infer_owner_claims(posts, clues)
        )


def test_frequent_shop_rejects_third_party_and_direct_shop_self_report() -> None:
    third_party_posts, third_party_clues = frequent_shop_fixture(
        habit_text="友人は毎週神保町で昼食をとる"
    )
    trailing_friend_posts, trailing_friend_clues = frequent_shop_fixture(
        habit_text="私は毎週神保町のこの店で昼食をとるのは友人です"
    )
    intervening_friend_posts, intervening_friend_clues = frequent_shop_fixture(
        habit_text="私は友人が毎週神保町のこの店で昼食をとる"
    )
    direct_posts, direct_clues = frequent_shop_fixture(habit_text="私は毎週青葉珈琲 神保町店に通う")
    direct_observation_posts, direct_observation_clues = frequent_shop_fixture(
        observation_text="神保町で青葉珈琲 神保町店へ"
    )
    photo_only_posts, photo_only_clues = frequent_shop_fixture(observation_text="神保町で撮影")
    for posts, clues in (
        (third_party_posts, third_party_clues),
        (trailing_friend_posts, trailing_friend_clues),
        (intervening_friend_posts, intervening_friend_clues),
        (direct_posts, direct_clues),
        (direct_observation_posts, direct_observation_clues),
        (photo_only_posts, photo_only_clues),
    ):
        assert all(
            item.attribute is not ProfileAttribute.FREQUENT_SHOP
            for item in infer_owner_claims(posts, clues)
        )


def test_frequent_shop_rejects_conflicting_shop_values_at_same_location() -> None:
    posts, clues = frequent_shop_fixture(shop_b="別の珈琲 神保町店")
    assert all(
        item.attribute is not ProfileAttribute.FREQUENT_SHOP
        for item in infer_owner_claims(posts, clues)
    )


def test_frequent_shop_candidate_is_removed_when_either_required_post_is_deleted() -> None:
    posts, clues = frequent_shop_fixture()
    claims = [
        item
        for item in infer_owner_claims(posts, clues)
        if item.attribute is ProfileAttribute.FREQUENT_SHOP
    ]
    claim = claims[0]
    assert recalculate_after_deletion(claim, {posts[0].post_id}) is None
    assert recalculate_after_deletion(claim, {posts[1].post_id}) is None


def test_school_candidate_needs_independent_sign_class_and_festival_posts() -> None:
    campus = post("school-campus", "大学も秋を感じる")
    class_day = post("school-class", "授業終わりに学食へ")
    festival = post("school-festival", "文化祭ちかづいてきた")
    clue = school_org_clue(campus, "東京外国語大学")
    irrelevant = typed_clue(class_day, "授業終わり", ClueType.ROUTINE_TEXT)

    claim = next(
        item
        for item in infer_owner_claims([campus, class_day, festival], [irrelevant, clue])
        if item.attribute is ProfileAttribute.SCHOOL
    )

    assert claim.value == "東京外国語大学"
    assert claim.status is ProfileStatus.WEAK
    assert claim.confidence == 0.55
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path} == {campus.post_id, class_day.post_id, festival.post_id}
    assert {ref.clue_index for ref in path if ref.clue_index is not None} == {1}
    assert all(ref.required for ref in path)
    assert any(
        ref.post_id == campus.post_id and ref.source == "post_text" and ref.excerpt == "大学"
        for ref in path
    )
    required_posts = {campus.post_id, class_day.post_id, festival.post_id}
    assert all(recalculate_after_deletion(claim, {post_id}) is None for post_id in required_posts)


def test_school_candidate_rejects_single_sign_incomplete_and_non_owner_contexts() -> None:
    campus = post("school-campus", "大学も秋を感じる")
    class_day = post("school-class", "授業終わりに学食へ")
    festival = post("school-festival", "文化祭ちかづいてきた")
    clue = school_org_clue(campus, "東京外国語大学")
    cases = [
        ([campus], [clue]),
        ([campus, class_day], [clue]),
        ([campus, class_day, post("visit", "文化祭ちかづいてきた。見学に行く")], [clue]),
        ([campus.model_copy(update={"text": "大学の説明会を見学"}), class_day, festival], [clue]),
        ([campus, post("teacher-class", "先生として授業終わり"), festival], [clue]),
        ([campus, post("other-class", "東京大学の授業終わり"), festival], [clue]),
        (
            [campus, class_day, festival],
            [school_org_clue(campus, "東京外国語大学", confidence=0.8)],
        ),
    ]
    for posts, clues in cases:
        assert all(
            item.attribute is not ProfileAttribute.SCHOOL
            for item in infer_owner_claims(posts, clues)
        )


def test_school_rule_retains_separately_supported_school_candidates() -> None:
    first = photo_post("school-one", "大学のキャンパスで撮影")
    second = photo_post("school-two", "大学のキャンパスで撮影")
    class_day = post("school-class", "授業終わりに学食へ")
    festival = post("school-festival", "文化祭が来週開催")
    clues = [school_org_clue(first, "東京外国語大学"), school_org_clue(second, "架空青空大学")]
    claims = [
        item
        for item in infer_owner_claims([first, second, class_day, festival], clues)
        if item.attribute is ProfileAttribute.SCHOOL
    ]
    assert {item.value for item in claims} == {"東京外国語大学", "架空青空大学"}
    sets = evaluate_profile_candidates(claims, [first, second, class_day, festival], clues=clues)
    school_set = next(item for item in sets if item.attribute is ProfileAttribute.SCHOOL)
    assert school_set.status is ProfileCandidateSetStatus.AMBIGUOUS


def test_school_same_name_signs_across_anchor_posts_merge_independent_evidence_paths() -> None:
    first = photo_post("school-sign-one", "大学のキャンパスで撮影")
    second = photo_post("school-sign-two", "大学のキャンパスで撮影")
    class_day, festival = (
        post("school-class-merge", "授業終わりに学食へ"),
        post("school-festival-merge", "文化祭が来週開催"),
    )
    clues = [school_org_clue(first, "東京外国語大学"), school_org_clue(second, "東京外国語大学")]
    claims = [
        item
        for item in infer_owner_claims([first, second, class_day, festival], clues)
        if item.attribute is ProfileAttribute.SCHOOL
    ]
    assert len(claims) == 1
    assert len(claims[0].evidence_paths) == 2


def test_employer_claim_is_not_inferred_from_company_possessive_bridge() -> None:
    anchor = post("a", "うちの会社の青空研修")
    value = post("b", "青空社の青空研修")
    claims = infer_owner_claims([anchor, value], [typed_clue(value, "青空社", ClueType.ORG_TEXT)])
    assert all(c.attribute is not ProfileAttribute.EMPLOYER_NAME for c in claims)


def test_residence_claim_survives_rejected_employer_possessive_pattern() -> None:
    home_a, home_b = post("ha", "自宅近くの青葉商店街"), post("hb", "青葉商店街は文京区")
    work_a, work_b = post("wa", "うちの会社の青空研修"), post("wb", "青空社の青空研修")
    claims = infer_owner_claims(
        [home_a, home_b, work_a, work_b],
        [
            typed_clue(home_b, "文京区", ClueType.PLACE_TEXT),
            typed_clue(work_b, "青空社", ClueType.ORG_TEXT),
        ],
    )
    assert {item.attribute for item in claims} == {ProfileAttribute.RESIDENTIAL_AREA}


def test_photo_place_residence_needs_home_context_and_independent_local_post() -> None:
    photo = post("photo-home", "\u81ea\u5b85\u306e\u8fd1\u304f\u306e \u9752\u8449\u5e02\u5834")
    area_post = post(
        "area-local", "\u6587\u4eac\u533a\u304c\u8fd1\u6240\u3067\u6bce\u65e5\u901a\u308b"
    )
    photo_clue = Clue(
        post_id=photo.post_id,
        image_index=0,
        type=ClueType.LANDMARK,
        value="\u9752\u8449 \u5e02\u5834",
        region=None,
        confidence=0.9,
        source=ClueSource.VLM,
    )
    area_clue = typed_clue(area_post, "\u6587\u4eac\u533a", ClueType.PLACE_TEXT)
    result = photo_area_result(photo, 0)
    claim = next(
        item
        for item in infer_owner_claims(
            [photo, area_post], [photo_clue, area_clue], photo_place_results=[result]
        )
        if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert claim.value == "\u6587\u4eac\u533a"
    candidate_sets = infer_owner_candidate_sets_with_web(
        [photo, area_post],
        [photo_clue, area_clue],
        [],
        photo_place_results=[result],
    )
    residence_set = next(
        item for item in candidate_sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert [candidate.value for candidate in residence_set.candidates] == ["\u6587\u4eac\u533a"]
    for lookup_status in (
        PhotoPlaceLookupStatus.REFERENCE_CHECKED,
        PhotoPlaceLookupStatus.UNAVAILABLE,
    ):
        checked = result.model_copy(update={"lookup_status": lookup_status})
        assert any(
            item.attribute is ProfileAttribute.RESIDENTIAL_AREA
            for item in infer_owner_claims(
                [photo, area_post], [photo_clue, area_clue], photo_place_results=[checked]
            )
        )
    web_searched = result.model_copy(update={"lookup_status": PhotoPlaceLookupStatus.WEB_SEARCHED})
    assert all(
        item.attribute is not ProfileAttribute.RESIDENTIAL_AREA
        for item in infer_owner_claims(
            [photo, area_post], [photo_clue, area_clue], photo_place_results=[web_searched]
        )
    )
    camera_location = result.model_copy(
        update={
            "candidates": [
                result.candidates[0].model_copy(
                    update={"photo_relation": PhotoPlaceRelation.CAMERA_AT}
                )
            ]
        }
    )
    assert all(
        item.attribute is not ProfileAttribute.RESIDENTIAL_AREA
        for item in infer_owner_claims(
            [photo, area_post], [photo_clue, area_clue], photo_place_results=[camera_location]
        )
    )
    assert claim.status is ProfileStatus.WEAK
    assert claim.confidence <= 0.65
    path = claim.evidence_paths[0]
    assert {ref.post_id for ref in path.evidence if ref.post_id} == {
        photo.post_id,
        area_post.post_id,
    }
    assert any(ref.post_id == photo.post_id and ref.clue_index == 0 for ref in path.evidence)
    assert recalculate_after_deletion(claim, {photo.post_id}) is None
    assert recalculate_after_deletion(claim, {area_post.post_id}) is None


def test_photo_place_residence_rejects_result_alone_and_plain_area_mention() -> None:
    photo = post("photo-only", "\u81ea\u5b85\u8fd1\u304f\u306e\u9752\u8449\u5e02\u5834")
    photo_clue = Clue(
        post_id=photo.post_id,
        image_index=0,
        type=ClueType.LANDMARK,
        value="\u9752\u8449\u5e02\u5834",
        region=None,
        confidence=0.9,
        source=ClueSource.VLM,
    )
    result = photo_area_result(photo, 0)
    assert infer_owner_claims([photo], [photo_clue], photo_place_results=[result]) == []

    mention = post("mention", "\u6587\u4eac\u533a\u3067\u30e9\u30f3\u30c1")
    area_clue = typed_clue(mention, "\u6587\u4eac\u533a", ClueType.PLACE_TEXT)
    assert (
        infer_owner_claims([photo, mention], [photo_clue, area_clue], photo_place_results=[result])
        == []
    )

    unrelated = post("unrelated-home", "\u81ea\u5b85\u8fd1\u304f\u306e\u5225\u306e\u770b\u677f")
    unrelated_clue = photo_clue.model_copy(update={"post_id": unrelated.post_id})
    unrelated_result = photo_area_result(unrelated, 0)
    wrong_candidate = unrelated_result.model_copy(
        update={
            "candidates": [
                unrelated_result.candidates[0].model_copy(
                    update={"label": "\u5225\u306e\u770b\u677f"}
                )
            ]
        }
    )
    local = post(
        "unrelated-area", "\u6587\u4eac\u533a\u304c\u8fd1\u6240\u3067\u6bce\u65e5\u901a\u308b"
    )
    local_clue = typed_clue(local, "\u6587\u4eac\u533a", ClueType.PLACE_TEXT)
    assert (
        infer_owner_claims(
            [unrelated, local],
            [unrelated_clue, local_clue],
            photo_place_results=[wrong_candidate],
        )
        == []
    )
    assert (
        infer_owner_claims(
            [unrelated, local],
            [unrelated_clue, local_clue],
            photo_place_results=[unrelated_result],
        )
        == []
    )


def test_photo_place_residence_rejects_trip_quote_and_negated_home_context() -> None:
    for key, text in (
        ("trip-photo", "\u65c5\u884cで\u81ea\u5b85\u8fd1\u304f\u306e\u9752\u8449\u5e02\u5834"),
        ("quote-photo", "\u300e\u81ea\u5b85\u8fd1\u304f\u306e\u9752\u8449\u5e02\u5834\u300f"),
        (
            "deny-photo",
            "\u81ea\u5b85\u8fd1\u304f\u306e\u9752\u8449\u5e02\u5834\u3067\u306f\u306a\u3044",
        ),
    ):
        photo = post(key, text)
        area_post = post(
            f"{key}-area", "\u6587\u4eac\u533a\u304c\u8fd1\u6240\u3067\u6bce\u65e5\u901a\u308b"
        )
        photo_clue = Clue(
            post_id=photo.post_id,
            image_index=0,
            type=ClueType.LANDMARK,
            value="\u9752\u8449\u5e02\u5834",
            region=None,
            confidence=0.9,
            source=ClueSource.VLM,
        )
        clues = [photo_clue, typed_clue(area_post, "\u6587\u4eac\u533a", ClueType.PLACE_TEXT)]
        result = photo_area_result(photo, 0)
        assert infer_owner_claims([photo, area_post], clues, photo_place_results=[result]) == []


def test_profile_text_owner_anchor_uses_two_posts_and_has_profile_evidence() -> None:
    bridge = post("bridge", "青葉商店街で買い物")
    value = post("value", "青葉商店街は文京区")
    claims = infer_owner_claims(
        [bridge, value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)], "自宅近くの青葉商店街"
    )
    item = next(c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    refs = item.evidence_paths[0].evidence
    assert any(ref.source == "profile_text" and "自宅近く" in (ref.excerpt or "") for ref in refs)
    assert {ref.post_id for ref in refs if ref.post_id} == {bridge.post_id, value.post_id}
    assert recalculate_after_deletion(item, {bridge.post_id}) is None
    assert (
        infer_owner_claims(
            [value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)], "自宅近くの青葉商店街"
        )
        == []
    )


def test_profile_text_and_post_possessive_phrase_do_not_infer_employer() -> None:
    anchor = post("anchor", "うちの会社の青空研修")
    bridge = post("bridge", "青空研修の資料")
    profile_text = "青空社の青空研修"
    claim = infer_owner_claims(
        [anchor, bridge], [], profile_text, [profile_clue("青空社", ClueType.ORG_TEXT)]
    )
    assert all(item.attribute is not ProfileAttribute.EMPLOYER_NAME for item in claim)


def test_single_post_station_visit_or_logo_never_proves_sensitive_claim() -> None:
    only = post("one", "自宅近くの根津駅。青葉商事を訪問")
    image = Clue(
        post_id=only.post_id,
        image_index=0,
        type=ClueType.ORG_TEXT,
        value="青葉商事",
        region=None,
        confidence=0.99,
        source=ClueSource.VLM,
    )
    assert infer_owner_claims([only], [image]) == []
    station_only = post("station", "根津駅に行った")
    assert infer_owner_claims([station_only], []) == []


def test_two_clues_or_two_phrases_in_one_post_are_not_independent_posts() -> None:
    only = post("one", "自宅近くの青葉商店街。青葉商店街は文京区")
    assert infer_owner_claims([only], [typed_clue(only, "文京区", ClueType.PLACE_TEXT)]) == []


def test_conflicting_values_on_same_bridge_are_kept_as_separate_candidates() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    one = post("b", "青葉商店街は文京区")
    two = post("c", "青葉商店街は台東区")
    claims = infer_owner_claims(
        [anchor, one, two],
        [
            typed_clue(one, "文京区", ClueType.PLACE_TEXT),
            typed_clue(two, "台東区", ClueType.PLACE_TEXT),
        ],
    )
    assert {claim.value for claim in claims} == {"文京区", "台東区"}


def test_generic_or_untyped_values_are_not_residential_or_employer_claims() -> None:
    home_a = post("ha", "自宅近くの青葉商店街")
    home_b = post("hb", "青葉商店街は楽しい")
    work_a = post("wa", "うちの会社の青空研修")
    work_b = post("wb", "友人の青空研修")
    assert (
        infer_owner_claims(
            [home_a, home_b, work_a, work_b],
            [
                typed_clue(home_b, "楽しい", ClueType.PLACE_TEXT),
                typed_clue(work_b, "友人", ClueType.ORG_TEXT),
            ],
        )
        == []
    )


def test_generic_bridges_are_not_distinctive_names() -> None:
    employer_a = post("ga", "うちの会社の研修")
    employer_b = post("gb", "青空社の研修")
    home_a = post("ha", "自宅近くの商店街")
    home_b = post("hb", "商店街は文京区")
    assert infer_owner_claims([employer_a, employer_b, home_a, home_b], []) == []


def test_removing_a_required_post_breaks_the_path() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    value = post("b", "青葉商店街は文京区")
    item = infer_owner_claims([anchor, value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)])[
        0
    ]
    assert recalculate_after_deletion(item, {anchor.post_id}) is None


def test_alternative_evidence_paths_survive_partial_deletion_only() -> None:
    anchor = post("a", "自宅近くの青葉商店街")
    b, c = post("b", "青葉商店街は文京区"), post("c", "青葉商店街は文京区")
    clues = [
        typed_clue(b, "文京区", ClueType.PLACE_TEXT),
        typed_clue(c, "文京区", ClueType.PLACE_TEXT),
    ]
    item = infer_owner_claims([anchor, b, c], clues)[0]
    assert len(item.evidence_paths) == 2
    after_one = recalculate_after_deletion(item, {b.post_id})
    assert after_one is not None and len(after_one.evidence_paths) == 1
    assert recalculate_after_deletion(item, {anchor.post_id}) is None


def _claim_with_paths(
    attribute: ProfileAttribute,
    paths: list[list[Post]],
    confidences: list[float] | None = None,
) -> ProfileItem:
    confidences = confidences or [0.65] * len(paths)
    evidence_paths = [
        ProfileEvidencePath(
            evidence=[
                ProfileEvidence(
                    post_id=post.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt=f"根拠 {post.post_id}",
                )
                for post in path
            ],
            confidence=confidence,
        )
        for path, confidence in zip(paths, confidences, strict=True)
    ]
    return ProfileItem(
        attribute=attribute,
        value="架空の候補",
        confidence=max(confidences),
        status=ProfileStatus.WEAK,
        evidence=[reference for path in evidence_paths for reference in path.evidence],
        evidence_paths=evidence_paths,
    )


def test_profile_plan_finds_combination_that_breaks_alternative_paths() -> None:
    a, b, c, d = [post(key, "架空の根拠") for key in "abcd"]
    claim = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, b], [c, d]])

    # No single post breaks the OR of two AND paths. The stable first 2-post set does.
    assert plan_profile_claim_deletion([claim], [a, b, c, d]) == [a.post_id, c.post_id]


def test_profile_plan_maximizes_lost_claims_then_minimizes_and_stably_orders_posts() -> None:
    a, b, c, d, e = [post(key, "架空の根拠") for key in "abcde"]
    alternate = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, b], [c, d]])
    direct = _claim_with_paths(ProfileAttribute.EMPLOYER_NAME, [[a, c]])
    independent = _claim_with_paths(ProfileAttribute.CHILD_AGE, [[d, e]])

    # A+D breaks all three claims. No severity weights are used.
    assert plan_profile_claim_deletion([alternate, direct, independent], [a, b, c, d, e]) == [
        a.post_id,
        d.post_id,
    ]


def test_profile_plan_uses_only_confidence_supported_paths_and_caps_at_three() -> None:
    posts = [post(str(index), "架空の根拠") for index in range(8)]
    weak_only = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA,
        [[posts[0], posts[1]], [posts[2], posts[3]]],
        [0.4, 0.65],
    )
    assert plan_profile_claim_deletion([weak_only], posts) == [posts[2].post_id]

    four_path_claim = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA,
        [[posts[0], posts[1]], [posts[2], posts[3]], [posts[4], posts[5]], [posts[6], posts[7]]],
    )
    assert plan_profile_claim_deletion([four_path_claim], posts) == []


def test_child_age_requires_two_posts_and_either_deletion_breaks_exact_claim() -> None:
    birth = post("birth", "息子のたろうは2019年生まれ")
    birthday = post("birthday", "息子のたろう、今日は誕生日")
    birthday = birthday.model_copy(
        update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")}
    )
    claim = infer_child_age_claim([birth, birthday], diagnosis_date=date(2026, 11, 10))

    assert claim is not None
    assert claim.attribute is ProfileAttribute.CHILD_AGE
    assert claim.value == "7歳"
    assert claim.status is ProfileStatus.WEAK
    assert {ref.post_id for ref in claim.evidence_paths[0].evidence} == {
        birth.post_id,
        birthday.post_id,
    }
    assert recalculate_after_deletion(claim, {birth.post_id}) is None
    assert recalculate_after_deletion(claim, {birthday.post_id}) is None


def test_child_age_uses_japan_calendar_date_for_birthday_post() -> None:
    birth = post("birth-jst", "息子のたろうは2019年生まれ")
    birthday = post("birthday-jst", "息子のたろう、今日は誕生日").model_copy(
        update={"created_at": datetime.fromisoformat("2019-12-31T16:00:00+00:00")}
    )

    claim = infer_child_age_claim([birth, birthday], diagnosis_date=date(2026, 1, 2))

    assert claim is not None
    # The child's JST birthday is January 1, so the 2026 anniversary has passed.
    assert claim.value == "7歳"


def test_child_age_rejects_third_party_quotes_ambiguity_and_implausible_dates() -> None:
    year = post("birth", "息子のたろうは2019年生まれ")
    birthday = post("birthday", "息子のたろう、今日は誕生日").model_copy(
        update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")}
    )
    cases = [
        [post("niece", "甥のたろうは2019年生まれ"), birthday],
        [post("quoted", "「息子のたろうは2019年生まれ」"), birthday],
        [year, post("no-today", "息子のたろう、誕生日")],
        [year, birthday, post("second", "息子のたろうは2020年生まれ")],
        [year, birthday, post("already-public", "息子のたろうは7歳")],
        [year, birthday, post("already-public-unnamed", "息子は今年で7歳")],
        [post("future", "息子のたろうは2027年生まれ"), birthday],
        [post("adult", "息子のたろうは1990年生まれ"), birthday],
        [post("eighteen", "息子のたろうは2008年生まれ"), birthday],
    ]
    for posts in cases:
        assert infer_child_age_claim(posts, diagnosis_date=date(2026, 11, 10)) is None

    # A repeated birthday report that supports the same calculated age is
    # corroboration, not a second competing value.
    corroborated = infer_child_age_claim(
        [year, birthday, post("second-birthday", "息子のたろうは今日は誕生日")],
        diagnosis_date=date(2026, 11, 10),
    )
    assert corroborated is not None and corroborated.value == "7歳"


def test_child_age_keeps_multiple_grounded_minor_candidates_without_naming_them_as_facts() -> None:
    posts = [
        post("birth-a", "息子のたろうは2019年生まれ"),
        post("birthday-a", "息子のたろう、今日は誕生日").model_copy(
            update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")}
        ),
        post("birth-b", "娘のはなこは2020年生まれ"),
        post("birthday-b", "娘のはなこ、今日は誕生日").model_copy(
            update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")}
        ),
    ]
    claims = infer_child_age_claims(posts, diagnosis_date=date(2026, 11, 10))
    assert {claim.value for claim in claims} == {"7歳", "6歳"}
    sets = evaluate_profile_candidates(claims, posts)
    ages = next(item for item in sets if item.attribute is ProfileAttribute.CHILD_AGE)
    assert ages.status is ProfileCandidateSetStatus.AMBIGUOUS


STATIONS = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": "m1"},
        {"station_name": "湯島", "mesh_1km": "m2"},
    ]
)


def photo_post(key: str, text: str) -> Post:
    base = post(key, text)
    return base.model_copy(
        update={
            "images": [
                PostImage(
                    index=0,
                    url="https://cdn.bsky.app/img/feed_fullsize/example",
                    alt="",
                    width=640,
                    height=480,
                )
            ]
        }
    )


def station_ocr(
    p: Post, value: str, *, confidence: float = 0.93, source: ClueSource = ClueSource.OCR
) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=0,
        type=ClueType.STATION_SIGN,
        value=value,
        region=(10, 20, 180, 60),
        confidence=confidence,
        source=source,
    )


def station_vlm(
    p: Post,
    value: str,
    *,
    confidence: float = 0.91,
    region: tuple[int, int, int, int] | None = (12, 22, 178, 58),
    image_index: int = 0,
) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=image_index,
        type=ClueType.STATION_SIGN,
        value=value,
        region=region,
        confidence=confidence,
        source=ClueSource.VLM,
    )


def test_combined_regular_line_requires_repeated_owner_commute_and_unique_gazetteer_line() -> None:
    first = post("line-a", "私は毎朝根津駅から湯島駅まで通勤する")
    second = post("line-b", "私は平日は根津駅から湯島駅まで通勤している")
    gaz = Gazetteer(
        stations=[
            {"station_name": "根津", "line_name": "千代田線", "operator": "東京メトロ"},
            {"station_name": "湯島", "line_name": "千代田線", "operator": "東京メトロ"},
            {"station_name": "根津", "line_name": "別線", "operator": "別会社"},
        ]
    )
    clues = [
        typed_clue(p, name, ClueType.PLACE_TEXT)
        for p in (first, second)
        for name in ("根津駅", "湯島駅")
    ]
    claims = infer_combined_regular_line_claims([first, second], clues, gaz)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.attribute is ProfileAttribute.REGULAR_LINE
    assert claim.value == "千代田線" and claim.status is ProfileStatus.WEAK
    assert claim.evidence_paths[0].provenance is EvidencePathProvenance.COMBINED_INFERENCE
    assert {ref.post_id for ref in claim.evidence} == {first.post_id, second.post_id}
    assert recalculate_after_deletion(claim, {first.post_id}) is None
    assert recalculate_after_deletion(claim, {second.post_id}) is None


def test_combined_regular_line_rejects_direct_disclosure_third_party_and_missing_clues() -> None:
    a = post("line-bad-a", "私は毎朝根津駅から湯島駅まで通勤する")
    b = post("line-bad-b", "私は平日は根津駅から湯島駅まで通勤する")
    clues = [
        typed_clue(p, name, ClueType.PLACE_TEXT) for p in (a, b) for name in ("根津駅", "湯島駅")
    ]
    gaz = Gazetteer(
        stations=[
            {"station_name": "根津", "line_name": "千代田線", "operator": "東京メトロ"},
            {"station_name": "湯島", "line_name": "千代田線", "operator": "東京メトロ"},
        ]
    )
    for invalid in (
        a.model_copy(update={"text": "私は毎朝根津駅から湯島駅まで千代田線で通勤する"}),
        a.model_copy(update={"text": "私は毎朝根津駅から湯島駅まで通勤しない"}),
        a.model_copy(update={"text": "『私は毎朝根津駅から湯島駅まで通勤する』"}),
        a.model_copy(update={"text": "友人は毎朝根津駅から湯島駅まで通勤する"}),
        a.model_copy(update={"text": "私は先週根津駅から湯島駅まで通勤した"}),
    ):
        assert infer_combined_regular_line_claims([invalid, b], clues, gaz) == []
    assert infer_combined_regular_line_claims([a], clues, gaz) == []
    assert infer_combined_regular_line_claims([a, b], clues[:-1], gaz) == []


def test_combined_regular_line_rejects_relative_clause_describing_another_commuter() -> None:
    first = post("line-relative-a", "私は毎朝根津駅から湯島駅まで通勤する人の投稿を見る")
    second = post("line-relative-b", "私は平日は根津駅から湯島駅まで通勤する人の投稿を見る")
    clues = [
        typed_clue(p, name, ClueType.PLACE_TEXT)
        for p in (first, second)
        for name in ("根津駅", "湯島駅")
    ]
    gaz = Gazetteer(
        stations=[
            {"station_name": "根津", "line_name": "千代田線", "operator": "東京メトロ"},
            {"station_name": "湯島", "line_name": "千代田線", "operator": "東京メトロ"},
        ]
    )
    assert infer_combined_regular_line_claims([first, second], clues, gaz) == []


def test_combined_regular_line_rejects_ambiguous_or_unavailable_station_table() -> None:
    a = post("line-gaz-a", "私は毎朝根津駅から湯島駅まで通勤する")
    b = post("line-gaz-b", "私は平日は根津駅から湯島駅まで通勤する")
    clues = [
        typed_clue(p, name, ClueType.PLACE_TEXT) for p in (a, b) for name in ("根津駅", "湯島駅")
    ]
    base = [
        {"station_name": "根津", "line_name": "千代田線", "operator": "東京メトロ"},
        {"station_name": "湯島", "line_name": "千代田線", "operator": "東京メトロ"},
    ]
    assert infer_combined_regular_line_claims([a, b], clues, Gazetteer()) == []
    assert (
        infer_combined_regular_line_claims(
            [a, b],
            clues,
            Gazetteer(
                stations=[
                    *base,
                    {"station_name": "根津", "line_name": "別線", "operator": "別会社"},
                    {"station_name": "湯島", "line_name": "別線", "operator": "別会社"},
                ]
            ),
        )
        == []
    )
    assert (
        infer_combined_regular_line_claims(
            [a, b],
            clues,
            Gazetteer(
                stations=[
                    *base,
                    {"station_name": "根津", "line_name": "別線", "operator": "別会社"},
                    {"station_name": "湯島", "line_name": "別線", "operator": "別会社"},
                ]
            ),
        )
        == []
    )


def test_regular_station_requires_habit_post_and_separate_usual_station_photo() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [
        typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
        station_ocr(photo, "根津"),
        station_vlm(photo, "根津"),
    ]

    claim = next(
        item
        for item in infer_owner_claims([habit, photo], clues, gazetteer=STATIONS)
        if item.attribute is ProfileAttribute.REGULAR_STATION
    )

    assert claim.value == "根津駅"
    assert claim.status is ProfileStatus.WEAK
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path} == {habit.post_id, photo.post_id}
    assert {ref.clue_index for ref in path if ref.clue_index is not None} == {0, 1, 2}
    assert any(
        ref.source == "post_text" and "いつもの通勤駅" in (ref.excerpt or "") for ref in path
    )
    assert recalculate_after_deletion(claim, {habit.post_id}) is None
    assert recalculate_after_deletion(claim, {photo.post_id}) is None


def test_home_nearest_origin_plus_independent_routine_makes_weak_regular_station_path() -> None:
    origin = post("origin", "私の自宅最寄り駅は根津駅です").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-20T08:31:00+09:00")}
    )
    routine = post("routine-origin", "私は毎朝、自宅最寄りから通勤しています").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-21T08:31:00+09:00")}
    )
    clues = [
        typed_clue(origin, "根津駅", ClueType.PLACE_TEXT),
        typed_clue(routine, routine.text, ClueType.ROUTINE_TEXT),
    ]
    claims = infer_regular_station_from_home_origin([origin, routine], clues, STATIONS)
    assert len(claims) == 1
    claim = claims[0]
    assert (
        claim.value == "根津駅" and claim.confidence == 0.55 and claim.status is ProfileStatus.WEAK
    )
    path = claim.evidence_paths[0]
    assert path.provenance is EvidencePathProvenance.COMBINED_INFERENCE
    assert {ref.post_id for ref in path.evidence} == {origin.post_id, routine.post_id}
    assert {ref.clue_index for ref in path.evidence if ref.clue_index is not None} == {0, 1}
    duplicated = infer_regular_station_from_home_origin(
        [origin, routine], [*clues, *clues], STATIONS
    )
    assert len(duplicated) == 1 and duplicated[0].confidence == claim.confidence
    assert recalculate_after_deletion(claim, {origin.post_id}) is None
    assert recalculate_after_deletion(claim, {routine.post_id}) is None
    ambiguous_origin = [*clues, typed_clue(origin, "湯島駅", ClueType.PLACE_TEXT)]
    assert (
        infer_regular_station_from_home_origin([origin, routine], ambiguous_origin, STATIONS) == []
    )
    pronoun_home = origin.model_copy(update={"text": "私は自宅最寄り駅は根津駅です"})
    pronoun_clues = [typed_clue(pronoun_home, "根津駅", ClueType.PLACE_TEXT), clues[1]]
    assert infer_regular_station_from_home_origin([pronoun_home, routine], pronoun_clues, STATIONS)
    assert infer_regular_station_from_home_origin([origin], clues, STATIONS) == []
    missing_time = routine.model_copy(update={"created_at": None})
    assert (
        infer_regular_station_from_home_origin(
            [origin, missing_time], [clues[0], clues[1]], STATIONS
        )
        == []
    )
    naive_origin = origin.model_copy(update={"created_at": datetime(2026, 10, 20, 8, 31)})
    assert infer_regular_station_from_home_origin([naive_origin, routine], clues, STATIONS) == []
    naive_routine = routine.model_copy(update={"created_at": datetime(2026, 10, 21, 8, 31)})
    assert infer_regular_station_from_home_origin([origin, naive_routine], clues, STATIONS) == []
    intervening_move = post("intervening-move", "転居しました").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-20T20:00:00+09:00")}
    )
    assert (
        infer_regular_station_from_home_origin([origin, intervening_move, routine], clues, STATIONS)
        == []
    )
    naive_intervening_move = intervening_move.model_copy(
        update={"created_at": datetime(2026, 10, 20, 20, 0)}
    )
    assert (
        infer_regular_station_from_home_origin(
            [origin, naive_intervening_move, routine], clues, STATIONS
        )
        == []
    )
    distant = routine.model_copy(
        update={"created_at": datetime.fromisoformat("2027-02-01T08:31:00+09:00")}
    )
    assert infer_regular_station_from_home_origin([origin, distant], clues, STATIONS) == []
    moved = routine.model_copy(update={"text": "私は毎朝、自宅最寄りから通勤。転居しました"})
    assert (
        infer_regular_station_from_home_origin(
            [origin, moved],
            [clues[0], typed_clue(moved, moved.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    quoted = routine.model_copy(update={"text": "『私は毎朝、自宅最寄りから通勤しています』"})
    assert (
        infer_regular_station_from_home_origin(
            [origin, quoted],
            [clues[0], typed_clue(quoted, quoted.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    friend_a = origin.model_copy(update={"text": "友人の自宅最寄り駅は根津駅です"})
    assert (
        infer_regular_station_from_home_origin(
            [friend_a, routine],
            [typed_clue(friend_a, "根津駅", ClueType.PLACE_TEXT), clues[1]],
            STATIONS,
        )
        == []
    )
    friend_b = routine.model_copy(update={"text": "彼は毎朝、自宅最寄りから通勤しています"})
    assert (
        infer_regular_station_from_home_origin(
            [origin, friend_b],
            [clues[0], typed_clue(friend_b, friend_b.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    friend_home = routine.model_copy(
        update={"text": "私は毎朝、友人の自宅最寄りから通勤しています"}
    )
    assert (
        infer_regular_station_from_home_origin(
            [origin, friend_home],
            [clues[0], typed_clue(friend_home, friend_home.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    partner_home = routine.model_copy(update={"text": "私は毎朝、彼の自宅最寄りから通勤しています"})
    assert (
        infer_regular_station_from_home_origin(
            [origin, partner_home],
            [clues[0], typed_clue(partner_home, partner_home.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    denied = routine.model_copy(update={"text": "私は毎朝、自宅最寄りから通勤しません"})
    assert (
        infer_regular_station_from_home_origin(
            [origin, denied],
            [clues[0], typed_clue(denied, denied.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
        )
        == []
    )
    same_post = origin.model_copy(
        update={"text": "私の自宅最寄り駅は根津駅です。私は毎朝、自宅最寄りから通勤しています"}
    )
    same_clues = [
        typed_clue(same_post, "根津駅", ClueType.PLACE_TEXT),
        typed_clue(same_post, same_post.text, ClueType.ROUTINE_TEXT),
    ]
    assert infer_regular_station_from_home_origin([same_post], same_clues, STATIONS) == []
    future = routine.model_copy(
        update={"created_at": datetime.fromisoformat("2027-01-01T08:31:00+09:00")}
    )
    fixed_now = datetime.fromisoformat("2026-11-13T12:00:00+09:00")
    assert (
        infer_regular_station_from_home_origin(
            [origin, future],
            [clues[0], typed_clue(future, future.text, ClueType.ROUTINE_TEXT)],
            STATIONS,
            diagnosis_at=fixed_now,
        )
        == []
    )
    assert (
        infer_regular_station_from_home_origin(
            [origin, routine], clues, STATIONS, diagnosis_at=datetime(2026, 11, 13, 12, 0, 0)
        )
        == []
    )


def test_profile_relations_require_independent_candidates_and_keep_complete_paths() -> None:
    relation_posts = [
        post("home-a", "私の自宅最寄り駅は根津駅です"),
        post("routine-b", "私は毎朝、自宅最寄りから通勤しています"),
        post("commute-dest", "私は毎朝通勤先は架空大学"),
    ]
    home_refs = [
        ProfileEvidence(
            post_id=relation_posts[0].post_id,
            clue_index=None,
            required=True,
            source="post_text",
            excerpt="私の自宅最寄り駅は根津駅です",
        ),
        ProfileEvidence(post_id=relation_posts[0].post_id, clue_index=0, required=True),
    ]
    regular_refs = [
        *home_refs,
        ProfileEvidence(
            post_id=relation_posts[1].post_id,
            clue_index=None,
            required=True,
            source="post_text",
            excerpt="私は毎朝、自宅最寄りから通勤しています",
        ),
        ProfileEvidence(post_id=relation_posts[1].post_id, clue_index=1, required=True),
    ]
    home_path = ProfileEvidencePath(
        evidence=home_refs, confidence=0.55, provenance=EvidencePathProvenance.DIRECT_DISCLOSURE
    )
    regular_path = ProfileEvidencePath(
        evidence=regular_refs, confidence=0.55, provenance=EvidencePathProvenance.COMBINED_INFERENCE
    )
    home_candidate = ProfileItem(
        attribute=ProfileAttribute.HOME_NEAREST_STATION,
        value="根津駅",
        confidence=0.55,
        status=ProfileStatus.WEAK,
        evidence=home_refs,
        evidence_paths=[home_path],
    )
    regular_candidate = ProfileItem(
        attribute=ProfileAttribute.REGULAR_STATION,
        value="根津駅",
        confidence=0.55,
        status=ProfileStatus.WEAK,
        evidence=regular_refs,
        evidence_paths=[regular_path],
    )
    claims = evaluate_profile_candidates([home_candidate, regular_candidate], [], clues=[])
    relations = infer_owner_profile_relations(relation_posts, claims)
    assert len(relations) == 1
    edge = relations[0]
    assert edge.kind.value == "home_nearest_is_commute_origin"
    assert {ref.post_id for ref in edge.evidence_paths[0].evidence} == {
        relation_posts[0].post_id,
        relation_posts[1].post_id,
    }
    unsupported_regular = regular_candidate.model_copy(
        update={"evidence_paths": [home_path], "evidence": home_refs}
    )
    unsupported_claims = evaluate_profile_candidates(
        [home_candidate, unsupported_regular], [], clues=[]
    )
    assert infer_owner_profile_relations(relation_posts, unsupported_claims) == []


def test_destination_relations_require_matching_independent_school_observation() -> None:
    observation = post("school-observation", "私は架空大学に通っています")
    destination = post("school-destination", "私は通学先は架空大学です")
    evidence = [
        ProfileEvidence(
            post_id=observation.post_id,
            clue_index=None,
            required=True,
            source="post_text",
            excerpt=observation.text,
        ),
        ProfileEvidence(post_id=observation.post_id, clue_index=0, required=True),
    ]
    path = ProfileEvidencePath(
        evidence=evidence, confidence=0.65, provenance=EvidencePathProvenance.DIRECT_DISCLOSURE
    )
    school = ProfileItem(
        attribute=ProfileAttribute.SCHOOL,
        value="架空大学",
        confidence=0.65,
        status=ProfileStatus.WEAK,
        evidence=evidence,
        evidence_paths=[path],
    )
    claims = evaluate_profile_candidates([school], [observation])
    relations = infer_owner_profile_relations([observation, destination], claims)
    assert len(relations) == 1
    assert relations[0].kind.value == "commute_destination_is_school"
    assert {ref.post_id for ref in relations[0].evidence_paths[0].evidence} == {
        observation.post_id,
        destination.post_id,
    }
    commuting = post("commuting-to-school", "私は通勤先は架空大学")
    assert infer_owner_profile_relations([observation, commuting], claims) == []
    same_post_claims = evaluate_profile_candidates([school], [observation])
    assert infer_owner_profile_relations([observation], same_post_claims) == []


def test_employer_destination_does_not_trim_name_ending_in_hiragana_su() -> None:
    observation = post("employer-observation", "私は架空バス社の社員です")
    destination = post("employer-destination", "私は勤務先は架空バスです")
    evidence = [
        ProfileEvidence(
            post_id=observation.post_id,
            clue_index=None,
            required=True,
            source="post_text",
            excerpt=observation.text,
        ),
        ProfileEvidence(post_id=observation.post_id, clue_index=0, required=True),
    ]
    path = ProfileEvidencePath(
        evidence=evidence, confidence=0.65, provenance=EvidencePathProvenance.DIRECT_DISCLOSURE
    )
    employer = ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value="架空バス",
        confidence=0.65,
        status=ProfileStatus.WEAK,
        evidence=evidence,
        evidence_paths=[path],
    )
    claims = evaluate_profile_candidates([employer], [observation])
    relations = infer_owner_profile_relations([observation, destination], claims)
    assert len(relations) == 1
    assert relations[0].right.value == "架空バス"


def test_home_nearest_station_requires_owner_relation_routine_and_corroborated_sign() -> None:
    relation = photo_post("home-relation", "私の自宅の最寄り駅の写真です")
    habit = post("home-routine", "私は自宅から駅まで毎朝歩いている")
    habit_clue = typed_clue(habit, "私は自宅から駅まで毎朝歩いている", ClueType.ROUTINE_TEXT)
    clues = [habit_clue, station_ocr(relation, "根津"), station_vlm(relation, "根津")]
    claims = infer_home_nearest_station_claims([relation, habit], clues, STATIONS)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.attribute is ProfileAttribute.HOME_NEAREST_STATION
    assert claim.value == "根津駅" and claim.status is ProfileStatus.WEAK
    assert claim.evidence_paths[0].provenance is EvidencePathProvenance.COMBINED_INFERENCE
    assert {ref.post_id for ref in claim.evidence_paths[0].evidence} == {
        relation.post_id,
        habit.post_id,
    }
    assert recalculate_after_deletion(claim, {relation.post_id}) is None
    assert recalculate_after_deletion(claim, {habit.post_id}) is None
    assert infer_home_nearest_station_claims([relation, habit], clues[1:], STATIONS) == []


def test_home_nearest_station_rejects_commute_visit_quotes_partial_and_single_detector() -> None:
    relation = photo_post("home-relation-bad", "私の自宅の最寄り駅の写真です")
    habit = post("home-routine-bad", "私は自宅から駅まで毎朝歩いている")
    routine = typed_clue(habit, habit.text, ClueType.ROUTINE_TEXT)
    valid = [routine, station_ocr(relation, "根津"), station_vlm(relation, "根津")]
    assert infer_home_nearest_station_claims([relation, habit], valid, STATIONS)
    bad_signs = [
        [station_ocr(relation, "根津")],
        [station_vlm(relation, "根津")],
        [station_ocr(relation, "根x"), station_vlm(relation, "根x")],
        [station_ocr(relation, "未登録"), station_vlm(relation, "未登録")],
        [station_ocr(relation, "根津"), station_vlm(relation, "根津", region=(400, 400, 500, 500))],
        [station_ocr(relation, "根津", confidence=0.79), station_vlm(relation, "根津")],
    ]
    for signs in bad_signs:
        assert (
            infer_home_nearest_station_claims([relation, habit], [routine, *signs], STATIONS) == []
        )
    for text in (
        "友人の自宅の最寄り駅の写真です",
        "『私の自宅の最寄り駅の写真です』",
        "私の自宅の最寄り駅は根津駅です",
        "私は自宅から駅まで毎朝歩いている。友人の話です",
    ):
        candidate_post = relation.model_copy(update={"text": text})
        assert (
            infer_home_nearest_station_claims(
                [candidate_post, habit],
                [routine, station_ocr(candidate_post, "根津"), station_vlm(candidate_post, "根津")],
                STATIONS,
            )
            == []
        )


def test_home_nearest_station_keeps_competing_qualified_signs_as_weak_candidates() -> None:
    habit = post("home-routine-ties", "私は自宅から駅まで毎朝歩いている")
    first = photo_post("home-sign-one", "私の自宅の最寄り駅の写真です")
    second = photo_post("home-sign-two", "私の自宅の最寄り駅の写真です")
    clues = [
        typed_clue(habit, habit.text, ClueType.ROUTINE_TEXT),
        station_ocr(first, "根津"),
        station_vlm(first, "根津"),
        station_ocr(second, "湯島"),
        station_vlm(second, "湯島"),
    ]
    claims = infer_home_nearest_station_claims([habit, first, second], clues, STATIONS)
    assert {item.value for item in claims} == {"根津駅", "湯島駅"}
    assert all(item.status is ProfileStatus.WEAK for item in claims)
    candidate_set = next(
        item
        for item in evaluate_profile_candidates(claims, [habit, first, second], clues=clues)
        if item.attribute is ProfileAttribute.HOME_NEAREST_STATION
    )
    assert candidate_set.status is ProfileCandidateSetStatus.AMBIGUOUS


def test_regular_station_rejects_non_ocr_partial_weak_unknown_and_ambiguous_signs() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    clue = typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT)
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    invalid_sets = [
        [station_ocr(photo, "根津")],  # OCR exact text without VLM sign context
        [station_ocr(photo, "根津", source=ClueSource.VLM)],
        [station_ocr(photo, "根x")],
        [station_ocr(photo, "根津", confidence=0.79)],
        [station_ocr(photo, "未登録")],
        [station_ocr(photo, "根津"), station_ocr(photo, "湯島")],
        [
            station_ocr(photo, "根津"),
            station_vlm(photo, "根津"),
            station_ocr(photo, "湯島", confidence=0.91),
            station_vlm(photo, "湯島", region=(10, 80, 180, 120)),
        ],
        [station_ocr(photo, "根津"), station_vlm(photo, "根津", region=None)],
        [station_ocr(photo, "根津"), station_vlm(photo, "根津", region=(400, 400, 500, 500))],
        [station_ocr(photo, "根津"), station_vlm(photo, "湯島")],
    ]
    for signs in invalid_sets:
        assert all(
            item.attribute is not ProfileAttribute.REGULAR_STATION
            for item in infer_owner_claims([habit, photo], [clue, *signs], gazetteer=STATIONS)
        )


def test_regular_station_rejects_visit_missing_context_same_post_and_missing_habit() -> None:
    photo = photo_post("photo", "いつもの通勤駅から見学に来た")
    sign = station_ocr(photo, "根津")
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    routine = typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT)
    assert all(
        item.attribute is not ProfileAttribute.REGULAR_STATION
        for item in infer_owner_claims(
            [habit, photo], [routine, sign, station_vlm(photo, "根津")], gazetteer=STATIONS
        )
    )

    same_post = photo_post("same", "毎朝いつもの通勤駅を使う。今日はいつもの通勤駅から出勤")
    same_clues = [
        typed_clue(same_post, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
        station_ocr(same_post, "根津"),
        station_vlm(same_post, "根津"),
    ]
    assert all(
        item.attribute is not ProfileAttribute.REGULAR_STATION
        for item in infer_owner_claims([same_post], same_clues, gazetteer=STATIONS)
    )

    for text in ("根津駅の写真", "いつもの通勤駅から出勤"):
        unsupported = photo_post("unsupported", text)
        clues = [sign.model_copy(update={"post_id": unsupported.post_id})]
        clues.append(station_vlm(unsupported, "根津"))
        if text != "いつもの通勤駅から出勤":
            clues.append(routine)
        assert all(
            item.attribute is not ProfileAttribute.REGULAR_STATION
            for item in infer_owner_claims([unsupported], clues, gazetteer=STATIONS)
        )


def test_regular_station_requires_a_gazetteer_entry() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [
        typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
        station_ocr(photo, "根津"),
        station_vlm(photo, "根津"),
    ]
    assert infer_owner_claims([habit, photo], clues, gazetteer=Gazetteer()) == []


def test_regular_station_rejects_a_different_station_concept_in_anchor() -> None:
    habit = post("habit", "毎朝最寄り駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [
        typed_clue(habit, "毎朝最寄り駅を使う", ClueType.ROUTINE_TEXT),
        station_ocr(photo, "根津"),
        station_vlm(photo, "根津"),
    ]

    assert all(
        item.attribute is not ProfileAttribute.REGULAR_STATION
        for item in infer_owner_claims([habit, photo], clues, gazetteer=STATIONS)
    )


def test_regular_station_retains_two_equally_grounded_station_candidates() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    first = photo_post("first-photo", "いつもの通勤駅から出勤")
    second = photo_post("second-photo", "いつもの通勤駅で待ち合わせ")
    clues = [
        typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
        station_ocr(first, "根津"),
        station_vlm(first, "根津"),
        station_ocr(second, "湯島"),
        station_vlm(second, "湯島"),
    ]

    claims = [
        item
        for item in infer_owner_claims([habit, first, second], clues, gazetteer=STATIONS)
        if item.attribute is ProfileAttribute.REGULAR_STATION
    ]
    assert {item.value for item in claims} == {"根津駅", "湯島駅"}
    sets = evaluate_profile_candidates(claims, [habit, first, second], clues=clues)
    station_set = next(item for item in sets if item.attribute is ProfileAttribute.REGULAR_STATION)
    assert station_set.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert [item.rank for item in station_set.candidates] == [1, 2]


def _explicit_rule_input(attribute: ProfileAttribute) -> tuple[Post, Clue, str]:
    cases = {
        ProfileAttribute.FULL_NAME: ("本名は山田太郎です", ClueType.NAME_TEXT, "山田太郎"),
        ProfileAttribute.GIVEN_NAME: ("下の名前は太郎です", ClueType.NAME_TEXT, "太郎"),
        ProfileAttribute.NICKNAME: ("ニックネームははるです", ClueType.NAME_TEXT, "はる"),
        ProfileAttribute.OTHER_SOCIAL_ACCOUNT: (
            "私の別垢は@haru.example",
            ClueType.HANDLE_TEXT,
            "@haru.example",
        ),
        ProfileAttribute.HOME_BUILDING: (
            "自宅は青葉マンションです",
            ClueType.LANDMARK,
            "青葉マンション",
        ),
        ProfileAttribute.HOME_NEAREST_STATION: (
            "自宅の最寄り駅は根津駅です",
            ClueType.PLACE_TEXT,
            "根津駅",
        ),
        ProfileAttribute.REGULAR_LINE: ("通勤路線は千代田線です", ClueType.PLACE_TEXT, "千代田線"),
        ProfileAttribute.ANNOUNCED_LONG_ABSENCE: (
            "来週は自宅を空ける予定",
            ClueType.ROUTINE_TEXT,
            "来週は自宅を空ける予定",
        ),
        ProfileAttribute.ACTUAL_HOME_ABSENCE: (
            "今は自宅にいません",
            ClueType.ROUTINE_TEXT,
            "今は自宅にいません",
        ),
        ProfileAttribute.EMPLOYER_NAME: ("勤務先は青空社です", ClueType.ORG_TEXT, "青空社"),
        ProfileAttribute.WORKPLACE_BUILDING_CANDIDATE: (
            "勤務先のビルは青空ビルです",
            ClueType.ORG_TEXT,
            "青空ビル",
        ),
        ProfileAttribute.WORKPLACE_AREA: (
            "職場のエリアは文京区です",
            ClueType.PLACE_TEXT,
            "文京区",
        ),
        ProfileAttribute.FREQUENT_SHOP: ("毎週青葉カフェに行く", ClueType.SHOP, "青葉カフェ"),
        ProfileAttribute.VEHICLE_MODEL: (
            "自分の車はホンダフィットです",
            ClueType.VEHICLE_MODEL,
            "ホンダフィット",
        ),
        ProfileAttribute.PARTIAL_PLATE: (
            "私の車のナンバーは品川300あ12-34",
            ClueType.PLATE,
            "品川300あ12-34",
        ),
        ProfileAttribute.PARTNER_STATUS: ("私は既婚です", ClueType.RELATION_TEXT, "既婚"),
        ProfileAttribute.PARTNER_ATTRIBUTES: ("私の妻は35歳です", ClueType.AGE_TEXT, "35歳"),
        ProfileAttribute.CHILD_SCHOOL: (
            "私の息子の学校は青葉高校です",
            ClueType.ORG_TEXT,
            "青葉高校",
        ),
    }
    text, clue_type, value = cases[attribute]
    source = (
        ClueSource.VLM
        if clue_type in {ClueType.LANDMARK, ClueType.SHOP, ClueType.PLATE}
        else ClueSource.TEXT
    )
    p = post(f"explicit-{attribute.value}", text)
    image_index = None
    if source is ClueSource.VLM:
        p = p.model_copy(
            update={
                "images": [
                    PostImage(
                        index=0,
                        url="https://cdn.bsky.app/img/feed_fullsize/example",
                        alt="",
                        width=640,
                        height=480,
                    )
                ]
            }
        )
        image_index = 0
    clue = Clue(
        post_id=p.post_id,
        image_index=image_index,
        type=clue_type,
        value=value,
        region=None,
        confidence=0.95,
        source=source,
    )
    return p, clue, text


def test_explicit_self_report_rules_emit_candidates_with_matching_typed_observations() -> None:
    now = datetime.fromisoformat("2026-10-20T08:31:00+09:00")
    generic_attributes = [
        attribute
        for attribute in ProfileAttribute
        if attribute
        not in {
            ProfileAttribute.FACIAL_APPEARANCE,
            ProfileAttribute.HOME_ROOM,
            ProfileAttribute.RESIDENTIAL_AREA,
            ProfileAttribute.REGULAR_STATION,
            ProfileAttribute.SCHOOL,
            ProfileAttribute.CHILD_AGE,
            ProfileAttribute.REALTIME_LOCATION,
            ProfileAttribute.FREQUENT_SHOP,
            ProfileAttribute.AGE,
            ProfileAttribute.BIRTHDAY,
            ProfileAttribute.OCCUPATION,
            ProfileAttribute.ACTIVE_TIME,
            ProfileAttribute.ROUTINE,
        }
    ]
    for attribute in generic_attributes:
        p, clue, _ = _explicit_rule_input(attribute)
        claims = infer_explicit_observation_claims([p], [clue], diagnosis_at=now)
        assert any(claim.attribute is attribute for claim in claims), attribute

    p, clue, _ = _explicit_rule_input(ProfileAttribute.FULL_NAME)
    low_confidence = clue.model_copy(update={"confidence": 0.49})
    assert infer_explicit_observation_claims([p], [low_confidence], diagnosis_at=now) == []


def test_explicit_rules_reject_denial_quotes_visits_and_third_party_statements() -> None:
    cases = [
        ("本名は山田太郎ではありません", ProfileAttribute.FULL_NAME, "山田太郎"),
        ("『本名は山田太郎です』", ProfileAttribute.FULL_NAME, "山田太郎"),
        ('"本名は山田太郎です"', ProfileAttribute.FULL_NAME, "山田太郎"),
        ("友人の勤務先は青空社です", ProfileAttribute.EMPLOYER_NAME, "青空社"),
        ("青空カフェを訪問。毎週行くのは友人です", ProfileAttribute.FREQUENT_SHOP, "青空カフェ"),
    ]
    for index, (text, attribute, value) in enumerate(cases):
        _, template, _ = _explicit_rule_input(attribute)
        p = post(f"reject-{index}", text)
        clue = template.model_copy(update={"post_id": p.post_id, "value": value})
        if clue.image_index is not None:
            p = p.model_copy(
                update={
                    "images": [
                        PostImage(
                            index=0,
                            url="https://cdn.bsky.app/img/feed_fullsize/example",
                            alt="",
                            width=640,
                            height=480,
                        )
                    ]
                }
            )
        assert all(
            claim.attribute is not attribute
            for claim in infer_explicit_observation_claims([p], [clue])
        )


def test_explicit_self_name_clause_does_not_capture_later_third_party_name() -> None:
    p = post(
        "mixed-names",
        "本名は山田太郎です。友達の名前は佐藤花子です。詳しい話はまた別の投稿で共有する予定です。",
    )
    owner_name = typed_clue(p, "山田太郎", ClueType.NAME_TEXT)
    friend_name = typed_clue(p, "佐藤花子", ClueType.NAME_TEXT)
    claims = infer_explicit_observation_claims([p], [owner_name, friend_name])
    names = [claim.value for claim in claims if claim.attribute is ProfileAttribute.FULL_NAME]
    assert names == ["山田太郎"]


def test_family_attribute_rules_reject_friend_subject_even_with_long_trailing_text() -> None:
    school_post = post(
        "friend-child-school",
        "友人の息子の学校は架空高校です。文化祭の写真を見せてもらい、詳しい話は別の投稿で紹介します。",
    )
    school_clue = typed_clue(school_post, "架空高校", ClueType.ORG_TEXT)
    partner_post = post(
        "friend-spouse-attribute",
        "友人の妻は35歳です。仕事や趣味についても話してくれました。長い近況報告を続けます。",
    )
    partner_clue = typed_clue(partner_post, "35歳", ClueType.AGE_TEXT)
    claims = infer_explicit_observation_claims(
        [school_post, partner_post], [school_clue, partner_clue]
    )
    assert all(claim.attribute is not ProfileAttribute.CHILD_SCHOOL for claim in claims)
    assert all(claim.attribute is not ProfileAttribute.PARTNER_ATTRIBUTES for claim in claims)


def test_family_attribute_rules_require_positive_owner_relation() -> None:
    cousin_school = post(
        "cousin-school", "いとこの息子の学校は架空高校です。詳しい話はまた別の投稿に書く予定です。"
    )
    cousin_clue = typed_clue(cousin_school, "架空高校", ClueType.ORG_TEXT)
    brother_spouse = post(
        "brother-spouse", "兄の妻は35歳です。仕事や趣味のことも話してくれました。"
    )
    spouse_clue = typed_clue(brother_spouse, "35歳", ClueType.AGE_TEXT)
    claims = infer_explicit_observation_claims(
        [cousin_school, brother_spouse], [cousin_clue, spouse_clue]
    )
    assert all(claim.attribute is not ProfileAttribute.CHILD_SCHOOL for claim in claims)
    assert all(claim.attribute is not ProfileAttribute.PARTNER_ATTRIBUTES for claim in claims)


def test_facial_appearance_requires_self_reference_and_same_post_face_clue() -> None:
    p = post("self-face", "私の顔が写っている写真です").model_copy(
        update={
            "images": [
                PostImage(
                    index=0,
                    url="https://cdn.bsky.app/img/feed_fullsize/example",
                    alt="",
                    width=640,
                    height=480,
                )
            ]
        }
    )
    face = Clue(
        post_id=p.post_id,
        image_index=0,
        type=ClueType.FACE,
        value="1人",
        region=(10, 10, 100, 100),
        confidence=0.9,
        source=ClueSource.VLM,
    )
    claims = infer_explicit_observation_claims([p], [face])
    candidate = next(
        item for item in claims if item.attribute is ProfileAttribute.FACIAL_APPEARANCE
    )
    assert candidate.value == "本人が自分の顔と書いた写真あり"
    assert "person" not in candidate.value.lower()
    assert {ref.source for ref in candidate.evidence} == {"post_text", "clue"}
    positive_set = next(
        item
        for item in evaluate_profile_candidates(claims, [p], clues=[face])
        if item.attribute is ProfileAttribute.FACIAL_APPEARANCE
    )
    assert positive_set.status is ProfileCandidateSetStatus.CANDIDATE

    missing = infer_explicit_observation_claims([p], [])
    assert all(item.attribute is not ProfileAttribute.FACIAL_APPEARANCE for item in missing)
    unknown_set = next(
        item
        for item in evaluate_profile_candidates(missing, [p])
        if item.attribute is ProfileAttribute.FACIAL_APPEARANCE
    )
    assert unknown_set.status is ProfileCandidateSetStatus.UNKNOWN
    for key, text in [
        ("friend-face", "友人の顔が写っている写真です"),
        ("quoted-face", "『私の顔が写っている写真』です"),
    ]:
        other = p.model_copy(
            update={"post_id": f"at://did:plc:owner/app.bsky.feed.post/{key}", "text": text}
        )
        other_clue = face.model_copy(update={"post_id": other.post_id})
        assert all(
            item.attribute is not ProfileAttribute.FACIAL_APPEARANCE
            for item in infer_explicit_observation_claims([other], [other_clue])
        )


def test_explicit_denial_evidence_is_retained_for_unknown_and_matching_candidates() -> None:
    positive = post("name-positive", "本名は山田太郎です")
    negative = post("name-negative", "本名は山田太郎ではありません")
    positive_clue = Clue(
        post_id=positive.post_id,
        image_index=None,
        type=ClueType.NAME_TEXT,
        value="山田太郎",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    negative_clue = positive_clue.model_copy(update={"post_id": negative.post_id})
    all_posts, all_clues = [positive, negative], [positive_clue, negative_clue]
    claims = infer_explicit_observation_claims(all_posts, all_clues)
    sets = evaluate_profile_candidates(claims, all_posts, clues=all_clues)
    full_name = next(item for item in sets if item.attribute is ProfileAttribute.FULL_NAME)
    assert full_name.status is ProfileCandidateSetStatus.CANDIDATE
    assert len(full_name.candidates[0].counter_evidence) == 2

    only_negative = evaluate_profile_candidates([], [negative], clues=[negative_clue])
    rejected = next(item for item in only_negative if item.attribute is ProfileAttribute.FULL_NAME)
    assert rejected.status is ProfileCandidateSetStatus.UNKNOWN
    assert rejected.reason == "explicit_negation"
    assert len(rejected.conflicting_evidence) == 2


def test_candidate_sets_cover_24_items_and_keep_equal_grounded_values_ambiguous() -> None:
    a = post("candidate-a", "自宅近くの青葉商店街")
    b = post("candidate-b", "青葉商店街は文京区")
    c = post("candidate-c", "青葉商店街は台東区")
    claims = infer_owner_claims(
        [a, b, c],
        [
            typed_clue(b, "文京区", ClueType.PLACE_TEXT),
            typed_clue(c, "台東区", ClueType.PLACE_TEXT),
        ],
    )
    sets = evaluate_profile_candidates(claims, [a, b, c])
    assert len(sets) == 29
    assert all(item.attribute is not ProfileAttribute.HOME_ROOM for item in sets)
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert residence.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert {candidate.value for candidate in residence.candidates} == {"文京区", "台東区"}
    plan = plan_profile_candidate_deletion(sets, [a, b, c])
    assert plan


def test_realtime_location_requires_recent_first_person_post_and_matching_place_clue() -> None:
    now = datetime(2026, 10, 20, 8, 31, tzinfo=UTC)
    current = post("current", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=10)}
    )
    clue = typed_clue(current, "根津駅", ClueType.PLACE_TEXT)
    claim = infer_realtime_location_claim([current], [clue], diagnosis_at=now)
    assert claim is not None and claim.value == "根津駅"

    for created_at in (None, now + timedelta(minutes=1), now - timedelta(minutes=16)):
        stale = current.model_copy(update={"created_at": created_at})
        assert infer_realtime_location_claim([stale], [clue], diagnosis_at=now) is None
    third_party = post("third-party", "友人が今は根津駅にいる").model_copy(
        update={"created_at": now}
    )
    assert (
        infer_realtime_location_claim(
            [third_party],
            [typed_clue(third_party, "根津駅", ClueType.PLACE_TEXT)],
            diagnosis_at=now,
        )
        is None
    )
    quoted_report = post("quoted-report", "「今は根津駅にいる」と友人から連絡が来た").model_copy(
        update={"created_at": now}
    )
    assert (
        infer_realtime_location_claim(
            [quoted_report],
            [typed_clue(quoted_report, "根津駅", ClueType.PLACE_TEXT)],
            diagnosis_at=now,
        )
        is None
    )
    ascii_quoted = post("ascii-quoted", '"今は根津駅にいる"').model_copy(update={"created_at": now})
    assert (
        infer_realtime_location_claim(
            [ascii_quoted],
            [typed_clue(ascii_quoted, "根津駅", ClueType.PLACE_TEXT)],
            diagnosis_at=now,
        )
        is None
    )


def test_candidate_singleton_is_not_a_truth_label_and_realtime_carries_observed_at() -> None:
    now = datetime(2026, 10, 20, 8, 31, tzinfo=UTC)
    current = post("candidate-current", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=2)}
    )
    clue = typed_clue(current, "根津駅", ClueType.PLACE_TEXT)
    claims = [infer_realtime_location_claim([current], [clue], diagnosis_at=now)]
    sets = evaluate_profile_candidates([claim for claim in claims if claim is not None], [current])
    realtime = next(item for item in sets if item.attribute is ProfileAttribute.REALTIME_LOCATION)
    assert realtime.status is ProfileCandidateSetStatus.CANDIDATE
    assert realtime.candidates[0].observed_at == current.created_at
    assert realtime.candidates[0].status is ProfileStatus.FOUND
    assert (
        realtime.candidates[0].evidence_paths[0].provenance
        is EvidencePathProvenance.DIRECT_DISCLOSURE
    )


def test_realtime_candidate_uses_freshest_complete_path_and_drops_stale_alternatives() -> None:
    now = datetime(2026, 10, 20, 8, 31, tzinfo=UTC)
    stale = post("candidate-stale", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=40)}
    )
    stale_support = post("candidate-stale-support", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=40)}
    )
    current = post("candidate-live", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=2)}
    )
    current_support = post("candidate-live-support", "今は根津駅にいる").model_copy(
        update={"created_at": now - timedelta(minutes=2)}
    )
    claims = [
        _claim_with_paths(ProfileAttribute.REALTIME_LOCATION, [[stale, stale_support]]).model_copy(
            update={"value": "根津駅"}
        ),
        _claim_with_paths(
            ProfileAttribute.REALTIME_LOCATION, [[current, current_support]]
        ).model_copy(update={"value": "根津駅"}),
    ]
    sets = evaluate_profile_candidates(claims, [stale, stale_support, current, current_support])
    realtime = next(item for item in sets if item.attribute is ProfileAttribute.REALTIME_LOCATION)
    assert realtime.candidates[0].observed_at == current.created_at

    after = recalculate_profile_candidate_sets(
        sets, {current.post_id}, [stale, stale_support], diagnosis_at=now
    )
    recalculated = next(
        item for item in after if item.attribute is ProfileAttribute.REALTIME_LOCATION
    )
    assert recalculated.status is ProfileCandidateSetStatus.UNKNOWN
    assert recalculated.candidate_pool == []


def test_candidate_normalization_matches_javascript_unicode_lowercase() -> None:
    a, b = post("unicode-a", "根拠A"), post("unicode-b", "根拠B")
    first = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, b]]).model_copy(
        update={"value": "Straße"}
    )
    second = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, b]]).model_copy(
        update={"value": "STRASSE"}
    )
    sets = evaluate_profile_candidates([first, second], [a, b])
    result = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert result.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert {candidate.value for candidate in result.candidates} == {"Straße", "STRASSE"}


def test_explicit_conflict_is_unknown_and_weak_values_show_even_with_large_score_gap() -> None:
    a, b = post("score-a", "自宅近くの青葉商店街"), post("score-b", "青葉商店街は文京区")
    strong = infer_owner_claims([a, b], [typed_clue(b, "文京区", ClueType.PLACE_TEXT)])[0]
    weaker = strong.model_copy(
        update={
            "value": "台東区",
            "confidence": 0.54,
            "evidence_paths": [strong.evidence_paths[0].model_copy(update={"confidence": 0.54})],
        }
    )
    sets = evaluate_profile_candidates([strong, weaker], [a, b])
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert residence.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert [candidate.value for candidate in residence.candidates] == ["文京区", "台東区"]
    conflict_sets = evaluate_profile_candidates(
        [strong],
        [a, b],
        {
            ProfileAttribute.RESIDENTIAL_AREA: "directly_conflicting_self_reports",
        },
    )
    residence_conflict = next(
        item for item in conflict_sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert residence_conflict.status is ProfileCandidateSetStatus.UNKNOWN
    assert residence_conflict.candidates == []


def test_weak_leader_shows_three_qualifying_values_across_large_score_gaps() -> None:
    posts = [post(f"weak-{index}", "根拠") for index in range(6)]
    claims = [
        _claim_with_paths(
            ProfileAttribute.RESIDENTIAL_AREA, [[posts[index], posts[index + 3]]], [score]
        ).model_copy(update={"value": f"候補{index}"})
        for index, score in enumerate((0.91, 0.74, 0.53))
    ]
    sets = evaluate_profile_candidates(claims, posts)
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert residence.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert [candidate.confidence for candidate in residence.candidates] == [0.91, 0.74, 0.53]


def test_found_leader_uses_same_grade_and_relative_margin_without_score_grade_cutoff() -> None:
    a, b, c, d = [post(f"found-{index}", "根拠") for index in range(4)]
    strong = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, b]], [0.71]).model_copy(
        update={"value": "直接値", "status": ProfileStatus.FOUND}
    )
    close_found = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[b, c]], [0.60]).model_copy(
        update={"value": "近い直接値", "status": ProfileStatus.FOUND}
    )
    close_weak = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[c, d]], [0.70]).model_copy(
        update={"value": "弱い値"}
    )
    outside = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[a, d]], [0.55]).model_copy(
        update={"value": "遠い直接値", "status": ProfileStatus.FOUND}
    )
    sets = evaluate_profile_candidates([strong, close_found, close_weak, outside], [a, b, c, d])
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert [candidate.value for candidate in residence.candidates] == ["直接値", "近い直接値"]
    assert [candidate.value for candidate in residence.candidate_pool] == [
        "直接値",
        "弱い値",
        "近い直接値",
        "遠い直接値",
    ]


def test_mixed_direct_and_combined_paths_stay_one_candidate_and_deletion_reclassifies() -> None:
    direct_a, direct_b, combined_a, combined_b = [post(f"mixed-{i}", "根拠") for i in range(4)]
    direct = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA, [[direct_a, direct_b]], [0.8]
    ).model_copy(update={"value": "同じ候補", "status": ProfileStatus.FOUND})
    direct = direct.model_copy(
        update={
            "evidence_paths": [
                direct.evidence_paths[0].model_copy(
                    update={"provenance": EvidencePathProvenance.DIRECT_DISCLOSURE}
                )
            ]
        }
    )
    combined = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA, [[combined_a, combined_b]], [0.7]
    ).model_copy(update={"value": "同じ候補"})
    combined = combined.model_copy(
        update={
            "evidence_paths": [
                combined.evidence_paths[0].model_copy(
                    update={"provenance": EvidencePathProvenance.COMBINED_INFERENCE}
                )
            ]
        }
    )
    sets = evaluate_profile_candidates(
        [direct, combined], [direct_a, direct_b, combined_a, combined_b]
    )
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert len(residence.candidate_pool) == 1
    assert {path.provenance for path in residence.candidate_pool[0].evidence_paths} == {
        EvidencePathProvenance.DIRECT_DISCLOSURE,
        EvidencePathProvenance.COMBINED_INFERENCE,
    }
    after = recalculate_profile_candidate_sets(
        sets, {direct_a.post_id, direct_b.post_id}, [combined_a, combined_b]
    )
    remaining = next(item for item in after if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert remaining.candidate_pool[0].status is ProfileStatus.WEAK
    assert {path.provenance for path in remaining.candidate_pool[0].evidence_paths} == {
        EvidencePathProvenance.COMBINED_INFERENCE
    }


def test_missing_claims_remain_unknown_and_do_not_enter_candidate_pool() -> None:
    sets = evaluate_profile_candidates([], [])
    assert len(sets) == 29
    assert all(item.status is ProfileCandidateSetStatus.UNKNOWN for item in sets)
    assert all(not item.candidates and not item.candidate_pool for item in sets)


def test_full_candidate_pool_promotes_rank_four_after_top_candidate_is_excluded() -> None:
    posts = [post(f"pool-{index}", "架空の根拠") for index in range(5)]
    claims = []
    for index in range(4):
        item = _claim_with_paths(ProfileAttribute.RESIDENTIAL_AREA, [[posts[index], posts[4]]])
        claims.append(item.model_copy(update={"value": f"架空区{index}"}))
    sets = evaluate_profile_candidates(claims, posts)
    no_op = recalculate_profile_candidate_sets(sets, set(), posts, diagnosis_at=datetime.now(UTC))
    before = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    after_no_op = next(
        item for item in no_op if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert [candidate.value for candidate in after_no_op.candidate_pool] == [
        candidate.value for candidate in before.candidate_pool
    ]
    assert [candidate.confidence for candidate in after_no_op.candidate_pool] == [
        candidate.confidence for candidate in before.candidate_pool
    ]
    residence = next(item for item in sets if item.attribute is ProfileAttribute.RESIDENTIAL_AREA)
    assert [item.value for item in residence.candidates] == ["架空区0", "架空区1", "架空区2"]
    assert [item.rank for item in residence.candidate_pool] == [1, 2, 3, 4]

    remaining_posts = posts[1:]
    recalculated = recalculate_profile_candidate_sets(sets, {posts[0].post_id}, remaining_posts)
    updated = next(
        item for item in recalculated if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert updated.status is ProfileCandidateSetStatus.AMBIGUOUS
    assert [item.value for item in updated.candidates] == ["架空区1", "架空区2", "架空区3"]
    assert [item.rank for item in updated.candidate_pool] == [1, 2, 3]


def test_profile_relations_keep_alternative_paths_and_drop_missing_endpoints() -> None:
    home_a, home_b = (
        post("relation-home-a", "自宅駅の写真"),
        post("relation-home-b", "自宅駅の写真"),
    )
    home_a_support, home_b_support = (
        post("relation-home-a-support", "自宅駅の記録"),
        post("relation-home-b-support", "自宅駅の記録"),
    )
    regular_a, regular_b = (
        post("relation-regular-a", "通勤駅の写真"),
        post("relation-regular-b", "通勤駅の写真"),
    )
    regular_a_support, regular_b_support = (
        post("relation-regular-a-support", "通勤駅の記録"),
        post("relation-regular-b-support", "通勤駅の記録"),
    )
    home = _claim_with_paths(
        ProfileAttribute.HOME_NEAREST_STATION,
        [[home_a, home_a_support], [home_b, home_b_support]],
    ).model_copy(update={"value": "根津駅"})
    regular = _claim_with_paths(
        ProfileAttribute.REGULAR_STATION,
        [[regular_a, regular_a_support], [regular_b, regular_b_support]],
    ).model_copy(update={"value": "根津駅"})
    claims = evaluate_profile_candidates(
        [home, regular],
        [
            home_a,
            home_a_support,
            home_b,
            home_b_support,
            regular_a,
            regular_a_support,
            regular_b,
            regular_b_support,
        ],
    )
    relation_paths = [
        ProfileEvidencePath(
            evidence=[
                ProfileEvidence(
                    post_id=home_a.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt="自宅駅",
                ),
                ProfileEvidence(
                    post_id=regular_a.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt="通勤駅",
                ),
            ],
            confidence=0.65,
        ),
        ProfileEvidencePath(
            evidence=[
                ProfileEvidence(
                    post_id=home_b.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt="自宅駅",
                ),
                ProfileEvidence(
                    post_id=regular_b.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt="通勤駅",
                ),
            ],
            confidence=0.6,
        ),
    ]
    relation = ProfileRelation(
        kind=ProfileRelationKind.HOME_NEAREST_IS_COMMUTE_ORIGIN,
        left=ProfileRelationEndpoint(
            kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
            attribute=ProfileAttribute.HOME_NEAREST_STATION,
            value="根津駅",
        ),
        right=ProfileRelationEndpoint(
            kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
            attribute=ProfileAttribute.REGULAR_STATION,
            value="根津駅",
        ),
        evidence_paths=relation_paths,
    )

    after_one = profile_relations_after_deletion([relation], {home_a.post_id}, claims)
    assert len(after_one) == 1
    assert after_one[0].evidence_paths == [relation_paths[1]]

    after_both = recalculate_profile_candidate_sets(
        claims,
        {home_a.post_id, home_b.post_id, regular_a.post_id, regular_b.post_id},
        [],
    )
    assert (
        profile_relations_after_deletion(
            [relation],
            {home_a.post_id, home_b.post_id, regular_a.post_id, regular_b.post_id},
            after_both,
        )
        == []
    )


def test_planner_does_not_count_top_rank_change_as_broken_when_alternatives_survive() -> None:
    top, second, collapse, shared = [
        post(key, "明示された根拠") for key in ("top", "second", "collapse", "shared")
    ]
    top_candidate = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA, [[top, shared]]
    ).model_copy(update={"value": "候補A"})
    second_candidate = _claim_with_paths(
        ProfileAttribute.RESIDENTIAL_AREA, [[second, shared]]
    ).model_copy(update={"value": "候補B"})
    separate = _claim_with_paths(ProfileAttribute.EMPLOYER_NAME, [[collapse, shared]]).model_copy(
        update={"value": "勤務先候補"}
    )
    sets = evaluate_profile_candidates(
        [top_candidate, second_candidate, separate], [top, second, collapse, shared]
    )

    plan = plan_profile_candidate_deletion(sets, [top, second, collapse, shared])
    assert plan != [top.post_id]
    after_top = recalculate_profile_candidate_sets(sets, {top.post_id}, [second, collapse, shared])
    residence = next(
        item for item in after_top if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    )
    assert residence.status is ProfileCandidateSetStatus.CANDIDATE
    assert [item.value for item in residence.candidates] == ["候補B"]


def test_rules_and_links_integrate_into_candidate_sets_and_collapse_on_deletion() -> None:
    p1 = post("rx-1", "茗荷谷駅の近く").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-05T08:10:00+09:00")}
    )
    p2 = post("rx-2", "10月5日が誕生日です。ケーキのプレートありがとう！").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-05T19:00:00+09:00")}
    )
    p3 = post("rx-3", "25歳、コーヒーが好き").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-12T12:00:00+09:00")}
    )
    p4 = post("rx-4", "夜勤終わり。火曜のジムに毎週通ってます").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-19T08:15:00+09:00")}
    )
    p5 = post("rx-5", "青空カフェでバイトのシフト終わり").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-21T20:00:00+09:00")}
    )
    p6 = post("rx-6", "来週から3泊で旅行に行くので家を空ける").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-22T20:00:00+09:00")}
    )
    p7 = post("rx-7", "青空カフェのテラス席").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-23T15:00:00+09:00")}
    )
    p8 = post("rx-8", "茗荷谷駅へ").model_copy(
        update={"created_at": datetime.fromisoformat("2026-10-23T08:15:00+09:00")}
    )
    posts = [p1, p2, p3, p4, p5, p6, p7, p8]
    clues = [
        Clue(
            post_id=p1.post_id,
            image_index=0,
            type=ClueType.ADDRESS_TEXT,
            value="東京都文京区小日向",
            region=(0, 0, 50, 50),
            confidence=0.9,
            source=ClueSource.OCR,
        ),
        Clue(
            post_id=p1.post_id,
            image_index=0,
            type=ClueType.STATION_SIGN,
            value="茗荷谷",
            region=(60, 0, 120, 50),
            confidence=0.9,
            source=ClueSource.VLM,
        ),
        typed_clue(p8, "茗荷谷駅", ClueType.PLACE_TEXT),
        Clue(
            post_id=p2.post_id,
            image_index=0,
            type=ClueType.NAME_TEXT,
            value="Happy Birthday さくら",
            region=(0, 0, 50, 50),
            confidence=0.9,
            source=ClueSource.VLM,
        ),
        typed_clue(p2, "10月5日が誕生日", ClueType.AGE_TEXT),
        typed_clue(p3, "25歳", ClueType.AGE_TEXT),
        typed_clue(p4, "夜勤", ClueType.ROUTINE_TEXT),
        typed_clue(p4, "毎週火曜はジム", ClueType.ROUTINE_TEXT),
        Clue(
            post_id=p4.post_id,
            image_index=0,
            type=ClueType.UNIFORM,
            value="スクラブ",
            region=(0, 0, 50, 50),
            confidence=0.9,
            source=ClueSource.VLM,
        ),
        typed_clue(p5, "青空カフェ", ClueType.PLACE_TEXT),
        typed_clue(p5, "バイトのシフト", ClueType.ROUTINE_TEXT),
        typed_clue(p6, "来週から3泊で旅行", ClueType.ROUTINE_TEXT),
        typed_clue(p7, "青空カフェ", ClueType.PLACE_TEXT),
    ]
    gaz = Gazetteer(
        stations=[{"station_name": "茗荷谷", "mesh_1km": "m-bunkyo"}],
        postal=[
            {"postal_code": "1120006", "muni_code": "13105", "city": "文京区", "town": "小日向"}
        ],
        muni_meshes={"13105": {"m-bunkyo"}},
    )

    claims = infer_rule_and_link_claims(posts, clues, gazetteer=gaz)
    assert claims
    assert all(len(path.evidence) >= 2 for claim in claims for path in claim.evidence_paths)

    sets = infer_owner_candidate_sets_with_web(posts, clues, [], gazetteer=gaz)
    assert len(sets) == 29
    by_attr = {candidate_set.attribute: candidate_set for candidate_set in sets}

    assert by_attr[ProfileAttribute.RESIDENTIAL_AREA].candidates[0].value == "小日向"
    assert by_attr[ProfileAttribute.HOME_NEAREST_STATION].candidates[0].value == "茗荷谷駅"
    assert by_attr[ProfileAttribute.ACTIVE_TIME].candidates
    assert by_attr[ProfileAttribute.ROUTINE].candidates
    assert by_attr[ProfileAttribute.GIVEN_NAME].candidates[0].value == "さくら"
    assert by_attr[ProfileAttribute.AGE].candidates[0].value == "25歳"
    assert by_attr[ProfileAttribute.BIRTHDAY].candidates[0].value == "2001年10月5日ごろ"
    assert by_attr[ProfileAttribute.OCCUPATION].candidates[0].value == "シフトのある医療の仕事"
    assert by_attr[ProfileAttribute.ANNOUNCED_LONG_ABSENCE].candidates
    assert by_attr[ProfileAttribute.FREQUENT_SHOP].candidates[0].value == "青空カフェ"
    assert (
        by_attr[ProfileAttribute.EMPLOYER_NAME].candidates[0].value
        == "青空カフェ（勤務先・バイト先の可能性）"
    )

    for candidate_set in by_attr.values():
        for candidate in candidate_set.candidates:
            for path in candidate.evidence_paths:
                assert path.provenance is EvidencePathProvenance.COMBINED_INFERENCE
                assert len(path.evidence) >= 2

    suggested = plan_profile_candidate_deletion(sets, posts)
    assert suggested
    after = recalculate_profile_candidate_sets(
        sets,
        {p4.post_id},
        [p for p in posts if p.post_id != p4.post_id],
        clues=clues,
    )
    after_by_attr = {candidate_set.attribute: candidate_set for candidate_set in after}
    assert after_by_attr[ProfileAttribute.OCCUPATION].status is ProfileCandidateSetStatus.UNKNOWN


def test_rules_x1_emits_commute_destination_is_school_relation() -> None:
    p_home = post("x1-home", "茗荷谷に住んでる")
    p_home2 = post("x1-home2", "茗荷谷駅のホーム")
    p_school = post("x1-school", "文京大学に通学")
    p_commute = post("x1-commute", "自宅から大学まで通学してる")
    posts = [p_home, p_home2, p_school, p_commute]
    clues = [
        Clue(
            post_id=p_home.post_id,
            image_index=0,
            type=ClueType.ADDRESS_TEXT,
            value="東京都文京区小日向",
            region=(0, 0, 50, 50),
            confidence=0.9,
            source=ClueSource.OCR,
        ),
        Clue(
            post_id=p_home2.post_id,
            image_index=0,
            type=ClueType.STATION_SIGN,
            value="茗荷谷",
            region=(60, 0, 120, 50),
            confidence=0.9,
            source=ClueSource.VLM,
        ),
        typed_clue(p_school, "文京大学", ClueType.ORG_TEXT),
        typed_clue(p_commute, "自宅から大学まで通学", ClueType.ROUTINE_TEXT),
    ]
    gaz = Gazetteer(
        stations=[{"station_name": "茗荷谷", "mesh_1km": "m-bunkyo"}],
        postal=[
            {"postal_code": "1120006", "muni_code": "13105", "city": "文京区", "town": "小日向"}
        ],
        muni_meshes={"13105": {"m-bunkyo"}},
        schools=[{"name": "文京大学", "kind": "大学", "city": "文京区"}],
    )

    candidate_sets = infer_owner_candidate_sets_with_web(posts, clues, [], gazetteer=gaz)
    relations = infer_owner_profile_relations(posts, candidate_sets, clues=clues, gazetteer=gaz)

    assert len(relations) == 1
    relation = relations[0]
    assert relation.kind is ProfileRelationKind.COMMUTE_DESTINATION_IS_SCHOOL
    assert relation.left.kind is ProfileRelationEndpointKind.COMMUTE_DESTINATION
    assert relation.left.value == "文京大学（文京区）"
    assert relation.right.kind is ProfileRelationEndpointKind.PROFILE_CANDIDATE
    assert relation.right.attribute is ProfileAttribute.SCHOOL
    assert relation.right.value == "文京大学（文京区）"
    assert len(relation.evidence_paths[0].evidence) >= 2


def brave_area_result(p: Post, clue_index: int, *, area: str | None = "文京区") -> PhotoPlaceResult:
    candidate = PhotoPlaceCandidate(
        place_id="brave-place:abc",
        label="青葉市場",
        place_type=PhotoPlaceType.FACILITY,
        photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
        area_label=area,
        evidence=[PhotoPlaceEvidence(kind="clue", clue_index=clue_index)],
        source_ids=["brave-place-search:abc"],
        sources=[
            PhotoPlaceSource(
                source_id="brave-place-search:abc",
                provider="Brave Search Place Search",
                dataset="unverified external place result",
                license_id="brave-search-api-terms",
                source_url="https://example.org/place",
            )
        ],
    )
    return PhotoPlaceResult(
        post_id=p.post_id,
        image_index=0,
        status=PhotoPlaceStatus.CANDIDATE,
        granularity=PhotoPlaceGranularity.FACILITY,
        lookup_status=PhotoPlaceLookupStatus.WEB_SEARCHED,
        candidates=[candidate],
    )


def _brave_fixture(
    photo_text: str = "自宅の近くの 青葉市場",
    area_text: str | None = "文京区が近所で毎日通る",
) -> tuple[list[Post], list[Clue], Post, Post | None]:
    photo = post("brave-photo", photo_text)
    photo_clue = Clue(
        post_id=photo.post_id,
        image_index=0,
        type=ClueType.LANDMARK,
        value="青葉 市場",
        region=None,
        confidence=0.9,
        source=ClueSource.VLM,
    )
    posts = [photo]
    clues = [photo_clue]
    area_post = None
    if area_text is not None:
        area_post = post("brave-area", area_text)
        posts.append(area_post)
        clues.append(typed_clue(area_post, "文京区", ClueType.PLACE_TEXT))
    return posts, clues, photo, area_post


def _residence(
    posts: list[Post], clues: list[Clue], results: list[PhotoPlaceResult]
) -> list[ProfileItem]:
    return [
        item
        for item in infer_owner_claims(posts, clues, photo_place_results=results)
        if item.attribute is ProfileAttribute.RESIDENTIAL_AREA
    ]


def test_single_brave_result_with_locality_gives_weak_residential_area() -> None:
    posts, clues, photo, area_post = _brave_fixture()
    assert area_post is not None
    [claim] = _residence(posts, clues, [brave_area_result(photo, 0)])
    assert claim.value == "文京区"
    assert claim.status is ProfileStatus.WEAK
    assert claim.confidence <= 0.65
    assert recalculate_after_deletion(claim, {photo.post_id}) is None
    assert recalculate_after_deletion(claim, {area_post.post_id}) is None


def test_brave_residential_area_rejects_weak_inputs() -> None:
    posts, clues, photo, _ = _brave_fixture()
    result = brave_area_result(photo, 0)
    extra = result.candidates[0].model_copy(update={"place_id": "brave-place:def"})
    local = photo_area_result(photo, 0).candidates[0]
    for bad in (
        result.model_copy(update={"candidates": [result.candidates[0], extra]}),
        result.model_copy(update={"candidates": [result.candidates[0], local]}),
        brave_area_result(photo, 0, area=None),
        brave_area_result(photo, 0, area="東京都"),
    ):
        assert _residence(posts, clues, [bad]) == []
    # 別の投稿の根拠がない
    no_area_posts, no_area_clues, no_area_photo, _ = _brave_fixture(area_text=None)
    assert _residence(no_area_posts, no_area_clues, [brave_area_result(no_area_photo, 0)]) == []
    # 写真の投稿の本文に自宅近くがない
    plain_posts, plain_clues, plain_photo, _ = _brave_fixture(photo_text="青葉市場に行った")
    assert _residence(plain_posts, plain_clues, [brave_area_result(plain_photo, 0)]) == []
