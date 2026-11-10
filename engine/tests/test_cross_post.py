from datetime import datetime
from datetime import date

from tkb_common.schemas import Clue, ClueSource, ClueType, Post, PostImage, ProfileAttribute, ProfileStatus
from tkb_engine.cross_post import infer_child_age_claim, infer_owner_claims, recalculate_after_deletion
from tkb_engine.gazetteer import Gazetteer


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


def test_employer_claim_is_not_inferred_from_company_possessive_bridge() -> None:
    anchor = post("a", "うちの会社の青空研修")
    value = post("b", "青空社の青空研修")
    claims = infer_owner_claims([anchor, value], [typed_clue(value, "青空社", ClueType.ORG_TEXT)])
    assert all(c.attribute is not ProfileAttribute.EMPLOYER_NAME for c in claims)


def test_residence_claim_survives_rejected_employer_possessive_pattern() -> None:
    home_a, home_b = post("ha", "自宅近くの青葉商店街"), post("hb", "青葉商店街は文京区")
    work_a, work_b = post("wa", "うちの会社の青空研修"), post("wb", "青空社の青空研修")
    claims = infer_owner_claims([home_a, home_b, work_a, work_b], [
        typed_clue(home_b, "文京区", ClueType.PLACE_TEXT), typed_clue(work_b, "青空社", ClueType.ORG_TEXT),
    ])
    assert {item.attribute for item in claims} == {ProfileAttribute.RESIDENTIAL_AREA}


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


def test_profile_text_and_post_possessive_phrase_do_not_infer_employer() -> None:
    anchor = post("anchor", "うちの会社の青空研修")
    bridge = post("bridge", "青空研修の資料")
    profile_text = "青空社の青空研修"
    claim = infer_owner_claims([anchor, bridge], [], profile_text, [profile_clue("青空社", ClueType.ORG_TEXT)])
    assert all(item.attribute is not ProfileAttribute.EMPLOYER_NAME for item in claim)


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
    anchor = post("a", "自宅近くの青葉商店街")
    value = post("b", "青葉商店街は文京区")
    item = infer_owner_claims([anchor, value], [typed_clue(value, "文京区", ClueType.PLACE_TEXT)])[0]
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


def test_child_age_requires_two_posts_and_either_deletion_breaks_exact_claim() -> None:
    birth = post("birth", "息子のたろうは2019年生まれ")
    birthday = post("birthday", "息子のたろう、今日は誕生日")
    birthday = birthday.model_copy(update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")})
    claim = infer_child_age_claim([birth, birthday], diagnosis_date=date(2026, 11, 10))

    assert claim is not None
    assert claim.attribute is ProfileAttribute.CHILD_AGE
    assert claim.value == "7歳"
    assert claim.status is ProfileStatus.WEAK
    assert {ref.post_id for ref in claim.evidence_paths[0].evidence} == {birth.post_id, birthday.post_id}
    assert recalculate_after_deletion(claim, {birth.post_id}) is None
    assert recalculate_after_deletion(claim, {birthday.post_id}) is None


def test_child_age_uses_japan_calendar_date_for_birthday_post() -> None:
    birth = post("birth-jst", "息子のたろうは2019年生まれ")
    birthday = post("birthday-jst", "息子のたろう、今日は誕生日").model_copy(
        update={"created_at": datetime.fromisoformat("2019-12-31T16:00:00+00:00")})

    claim = infer_child_age_claim([birth, birthday], diagnosis_date=date(2026, 1, 2))

    assert claim is not None
    assert claim.value == "6歳"


def test_child_age_rejects_third_party_quotes_ambiguity_and_implausible_dates() -> None:
    year = post("birth", "息子のたろうは2019年生まれ")
    birthday = post("birthday", "息子のたろう、今日は誕生日").model_copy(
        update={"created_at": datetime.fromisoformat("2025-10-20T08:31:00+09:00")})
    cases = [
        [post("niece", "甥のたろうは2019年生まれ"), birthday],
        [post("quoted", "「息子のたろうは2019年生まれ」"), birthday],
        [year, post("no-today", "息子のたろう、誕生日")],
        [year, birthday, post("second", "息子のたろうは2020年生まれ")],
        [year, birthday, post("second-birthday", "息子のたろうは今日は誕生日")],
        [year, birthday, post("already-public", "息子のたろうは7歳")],
        [year, birthday, post("already-public-unnamed", "息子は今年で7歳")],
        [post("future", "息子のたろうは2027年生まれ"), birthday],
        [post("adult", "息子のたろうは1990年生まれ"), birthday],
        [post("eighteen", "息子のたろうは2008年生まれ"), birthday],
    ]
    for posts in cases:
        assert infer_child_age_claim(posts, diagnosis_date=date(2026, 11, 10)) is None


STATIONS = Gazetteer(stations=[{"station_name": "根津", "mesh_1km": "m1"},
                                {"station_name": "湯島", "mesh_1km": "m2"}])


def photo_post(key: str, text: str) -> Post:
    base = post(key, text)
    return base.model_copy(update={"images": [PostImage(
        index=0, url="https://cdn.bsky.app/img/feed_fullsize/example", alt="",
        width=640, height=480,
    )]})


def station_ocr(p: Post, value: str, *, confidence: float = 0.93,
                source: ClueSource = ClueSource.OCR) -> Clue:
    return Clue(post_id=p.post_id, image_index=0, type=ClueType.STATION_SIGN, value=value,
                region=(10, 20, 180, 60), confidence=confidence, source=source)


def station_vlm(p: Post, value: str, *, confidence: float = 0.91,
                region: tuple[int, int, int, int] | None = (12, 22, 178, 58),
                image_index: int = 0) -> Clue:
    return Clue(post_id=p.post_id, image_index=image_index, type=ClueType.STATION_SIGN,
                value=value, region=region, confidence=confidence, source=ClueSource.VLM)


def test_regular_station_requires_habit_post_and_separate_usual_station_photo() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
             station_ocr(photo, "根津"), station_vlm(photo, "根津")]

    claim = next(item for item in infer_owner_claims([habit, photo], clues, gazetteer=STATIONS)
                 if item.attribute is ProfileAttribute.REGULAR_STATION)

    assert claim.value == "根津駅"
    assert claim.status is ProfileStatus.WEAK
    path = claim.evidence_paths[0].evidence
    assert {ref.post_id for ref in path} == {habit.post_id, photo.post_id}
    assert {ref.clue_index for ref in path if ref.clue_index is not None} == {0, 1, 2}
    assert any(ref.source == "post_text" and "いつもの通勤駅" in (ref.excerpt or "") for ref in path)
    assert recalculate_after_deletion(claim, {habit.post_id}) is None
    assert recalculate_after_deletion(claim, {photo.post_id}) is None


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
        [station_ocr(photo, "根津"), station_vlm(photo, "根津"),
         station_ocr(photo, "湯島", confidence=0.91),
         station_vlm(photo, "湯島", region=(10, 80, 180, 120))],
        [station_ocr(photo, "根津"), station_vlm(photo, "根津", region=None)],
        [station_ocr(photo, "根津"), station_vlm(photo, "根津", region=(400, 400, 500, 500))],
        [station_ocr(photo, "根津"), station_vlm(photo, "湯島")],
    ]
    for signs in invalid_sets:
        assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
                   for item in infer_owner_claims([habit, photo], [clue, *signs], gazetteer=STATIONS))


def test_regular_station_rejects_visit_missing_context_same_post_and_missing_habit() -> None:
    photo = photo_post("photo", "いつもの通勤駅から見学に来た")
    sign = station_ocr(photo, "根津")
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    routine = typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT)
    assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
               for item in infer_owner_claims([habit, photo], [routine, sign, station_vlm(photo, "根津")],
                                              gazetteer=STATIONS))

    same_post = photo_post("same", "毎朝いつもの通勤駅を使う。今日はいつもの通勤駅から出勤")
    same_clues = [typed_clue(same_post, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
                  station_ocr(same_post, "根津"), station_vlm(same_post, "根津")]
    assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
               for item in infer_owner_claims([same_post], same_clues, gazetteer=STATIONS))

    for text in ("根津駅の写真", "いつもの通勤駅から出勤"):
        unsupported = photo_post("unsupported", text)
        clues = [sign.model_copy(update={"post_id": unsupported.post_id})]
        clues.append(station_vlm(unsupported, "根津"))
        if text != "いつもの通勤駅から出勤":
            clues.append(routine)
        assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
                   for item in infer_owner_claims([unsupported], clues, gazetteer=STATIONS))


def test_regular_station_requires_a_gazetteer_entry() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
             station_ocr(photo, "根津"), station_vlm(photo, "根津")]
    assert infer_owner_claims([habit, photo], clues, gazetteer=Gazetteer()) == []


def test_regular_station_rejects_a_different_station_concept_in_anchor() -> None:
    habit = post("habit", "毎朝最寄り駅を使う")
    photo = photo_post("photo", "いつもの通勤駅から出勤")
    clues = [typed_clue(habit, "毎朝最寄り駅を使う", ClueType.ROUTINE_TEXT),
             station_ocr(photo, "根津"), station_vlm(photo, "根津")]

    assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
               for item in infer_owner_claims([habit, photo], clues, gazetteer=STATIONS))


def test_regular_station_rejects_conflicting_candidates_from_multiple_photo_posts() -> None:
    habit = post("habit", "毎朝いつもの通勤駅を使う")
    first = photo_post("first-photo", "いつもの通勤駅から出勤")
    second = photo_post("second-photo", "いつもの通勤駅で待ち合わせ")
    clues = [typed_clue(habit, "毎朝いつもの通勤駅を使う", ClueType.ROUTINE_TEXT),
             station_ocr(first, "根津"), station_vlm(first, "根津"),
             station_ocr(second, "湯島"), station_vlm(second, "湯島")]

    assert all(item.attribute is not ProfileAttribute.REGULAR_STATION
               for item in infer_owner_claims([habit, first, second], clues, gazetteer=STATIONS))
