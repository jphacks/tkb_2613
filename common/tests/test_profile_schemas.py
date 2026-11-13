from typing import Any

import pytest
from pydantic import ValidationError

from tkb_common.schemas import (
    PROFILE_ATTRIBUTE_CATALOG,
    PROFILE_CATEGORY_LABELS,
    ClaimAssessment,
    EvidenceScope,
    ProfileAttribute,
    ProfileEvidence,
    ProfileItem,
    ProfileStatus,
)

POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx"


def test_profile_catalog_has_all_25_candidate_ids_and_metadata() -> None:
    assert len(ProfileAttribute) == 25
    assert set(PROFILE_ATTRIBUTE_CATALOG) == set(ProfileAttribute)
    assert len(PROFILE_CATEGORY_LABELS) == 4
    assert all(item.label for item in PROFILE_ATTRIBUTE_CATALOG.values())
    assert all(
        item.personal_level is None and item.guessability is None
        for item in PROFILE_ATTRIBUTE_CATALOG.values()
    )
    assert {key.value: item.label for key, item in PROFILE_ATTRIBUTE_CATALOG.items()} == {
        "facial_appearance": "顔貌（自撮り・他撮り・反射）",
        "full_name": "本名（フルネーム）",
        "given_name": "下の名前",
        "nickname": "呼ばれている名前",
        "other_social_account": "別SNSのアカウント / 本垢",
        "realtime_location": "リアルタイムの現在地",
        "home_building": "自宅の建物候補",
        "home_room": "自宅の部屋・階・位置",
        "home_nearest_station": "自宅の最寄り駅",
        "regular_station": "投稿時点の通勤利用駅候補",
        "regular_line": "日常的に利用する路線",
        "residential_area": "居住エリア（市区町村・町域）",
        "announced_long_absence": "予告された長期不在",
        "actual_home_absence": "実際の自宅不在",
        "employer_name": "雇用主名の推定",
        "workplace_building_candidate": "勤務先建物候補",
        "workplace_area": "勤務先エリア（オフィス街）",
        "school": "通学先（大学・キャンパス・学校）",
        "frequent_shop": "行きつけの店（ジム・美容院・カフェ）",
        "vehicle_model": "自家用車の車種",
        "partial_plate": "ナンバーの一部",
        "partner_status": "配偶者・交際相手の有無",
        "partner_attributes": "配偶者・交際相手の属性",
        "child_age": "子どもの年齢",
        "child_school": "子どもの通園・通学先",
    }


def test_profile_catalog_matches_requested_metadata() -> None:
    assert set(PROFILE_ATTRIBUTE_CATALOG) == set(ProfileAttribute)
    assert all(metadata.personal_level is None for metadata in PROFILE_ATTRIBUTE_CATALOG.values())
    assert all(metadata.guessability is None for metadata in PROFILE_ATTRIBUTE_CATALOG.values())


def test_profile_item_matches_documented_shape_and_allows_unknown_value() -> None:
    item = ProfileItem.model_validate(
        {
            "attribute": "realtime_location",
            "value": None,
            "confidence": 0.0,
            "status": "unknown",
            "evidence": [],
        }
    )

    assert item.attribute is ProfileAttribute.REALTIME_LOCATION
    assert item.status is ProfileStatus.UNKNOWN
    assert item.value is None
    assert item.model_dump(mode="json") == {
        "attribute": "realtime_location",
        "value": None,
        "confidence": 0.0,
        "status": "unknown",
        "evidence": [],
        "evidence_paths": [],
        "assessment": {
            "minimal_scope": None,
            "offline_subtype": None,
            "psychological_resistance": None,
            "persona_context": None,
            "inference_ease": None,
            "inference_ease_basis": None,
            "harm_severity": None,
            "harm_scenario": None,
            "harm_prerequisites": [],
            "harm_status": "unknown",
        },
    }


def test_profile_item_accepts_existing_evidence_shape() -> None:
    item = ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value="サンプル会社",
        confidence=0.6,
        status=ProfileStatus.WEAK,
        evidence=[ProfileEvidence(post_id=POST_ID, clue_index=2, required=True)],
    )

    assert item.evidence[0].post_id == POST_ID
    assert item.evidence[0].clue_index == 2
    assert item.evidence[0].required is True


def test_profile_evidence_can_reference_profile_text_separately() -> None:
    evidence = ProfileEvidence(source="profile_text", excerpt="自宅近くの青葉商店街", required=True)
    assert evidence.post_id is None
    assert evidence.clue_index is None


def test_claim_assessment_enforces_conditional_score_context() -> None:
    with pytest.raises(ValidationError):
        ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY_OFFLINE)
    with pytest.raises(ValidationError):
        ClaimAssessment(psychological_resistance=3)
    with pytest.raises(ValidationError):
        ClaimAssessment(inference_ease=3)
    with pytest.raises(ValidationError):
        ClaimAssessment(harm_status="applicable", harm_severity=4)
    unmet = ClaimAssessment(
        harm_status="prerequisites_unmet",
        harm_scenario="訪問者が不在を把握する",
        harm_prerequisites=["同一人物と特定される", "訪問する"],
    )
    assert unmet.harm_severity is None


@pytest.mark.parametrize(
    "data",
    [
        {"attribute": "not_a_profile_attribute"},
        {
            "attribute": "employer_name",
            "value": None,
            "confidence": 1.01,
            "status": "found",
            "evidence": [],
        },
        {
            "attribute": "employer_name",
            "value": None,
            "confidence": 0.5,
            "status": "missing",
            "evidence": [],
        },
        {
            "attribute": "employer_name",
            "value": None,
            "confidence": 0.5,
            "status": "found",
            "evidence": [],
        },
        {
            "attribute": "employer_name",
            "value": "会社",
            "confidence": 0.5,
            "status": "unknown",
            "evidence": [],
        },
        {
            "attribute": "employer_name",
            "value": "  ",
            "confidence": 0.5,
            "status": "weak",
            "evidence": [],
        },
        {
            "attribute": "employer_name",
            "value": None,
            "confidence": 0.5,
            "status": "found",
            "evidence": [{"post_id": POST_ID, "clue_index": -1, "required": True}],
        },
    ],
)
def test_profile_item_rejects_invalid_values(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProfileItem.model_validate(data)
