from typing import Any

import pytest
from pydantic import ValidationError

from tkb_common.schemas import (
    PROFILE_ATTRIBUTE_CATALOG,
    PROFILE_CATEGORY_LABELS,
    Guessability,
    PersonalLevel,
    ProfileAttribute,
    ProfileEvidence,
    ProfileItem,
    ProfileStatus,
)

POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx"


def test_profile_catalog_has_all_16_stable_ids_and_metadata() -> None:
    assert len(ProfileAttribute) == 16
    assert set(PROFILE_ATTRIBUTE_CATALOG) == set(ProfileAttribute)
    assert len(PROFILE_CATEGORY_LABELS) == 4
    assert all(item.label for item in PROFILE_ATTRIBUTE_CATALOG.values())
    assert {item.personal_level for item in PROFILE_ATTRIBUTE_CATALOG.values()} == {
        PersonalLevel.LEVEL_4,
        PersonalLevel.LEVEL_5,
    }
    assert {item.guessability for item in PROFILE_ATTRIBUTE_CATALOG.values()} == {
        Guessability.A,
        Guessability.A_TO_B,
        Guessability.B,
    }
    assert {key.value: item.label for key, item in PROFILE_ATTRIBUTE_CATALOG.items()} == {
        "facial_appearance": "顔貌（自撮り・他撮り・反射）",
        "full_name": "本名（フルネーム）",
        "given_name_or_nickname": "下の名前 / 呼ばれている名前",
        "other_social_account": "別SNSのアカウント / 本垢",
        "realtime_location": "リアルタイムの現在地",
        "home_building_or_room": "自宅の建物外観・部屋の位置",
        "commute_station_or_line": "最寄り駅 / 日常の利用路線",
        "residential_area": "居住エリア（市区町村・町域）",
        "long_term_home_absence": "自宅の長期不在（旅行・帰省中）",
        "workplace": "勤務先（企業名・店舗・ビル）",
        "workplace_area": "勤務先エリア（オフィス街）",
        "school": "通学先（大学・キャンパス・学校）",
        "frequent_shop": "行きつけの店（ジム・美容院・カフェ）",
        "vehicle_model_or_partial_plate": "自家用車の車種・ナンバー（一部）",
        "partner_status_and_attributes": "配偶者・交際相手の有無と属性",
        "children_age_and_school": "子どもの有無・年齢・通園通学先",
    }


def test_profile_catalog_matches_requested_metadata() -> None:
    expected = {
        "facial_appearance": ("identity_and_face", 5, "A"),
        "full_name": ("identity_and_face", 5, "B"),
        "given_name_or_nickname": ("identity_and_face", 4, "A〜B"),
        "other_social_account": ("identity_and_face", 4, "A"),
        "realtime_location": ("home_and_location", 5, "A"),
        "home_building_or_room": ("home_and_location", 5, "B"),
        "commute_station_or_line": ("home_and_location", 4, "A〜B"),
        "residential_area": ("home_and_location", 4, "B"),
        "long_term_home_absence": ("home_and_location", 4, "A〜B"),
        "workplace": ("affiliation_and_work", 4, "B"),
        "workplace_area": ("affiliation_and_work", 4, "A〜B"),
        "school": ("affiliation_and_work", 4, "B"),
        "frequent_shop": ("activity_and_family", 4, "B"),
        "vehicle_model_or_partial_plate": ("activity_and_family", 4, "A〜B"),
        "partner_status_and_attributes": ("activity_and_family", 4, "B"),
        "children_age_and_school": ("activity_and_family", 4, "B"),
    }
    actual = {
        attribute.value: (
            metadata.category.value,
            int(metadata.personal_level),
            metadata.guessability.value,
        )
        for attribute, metadata in PROFILE_ATTRIBUTE_CATALOG.items()
    }

    assert actual == expected


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
    }


def test_profile_item_accepts_existing_evidence_shape() -> None:
    item = ProfileItem(
        attribute=ProfileAttribute.WORKPLACE,
        value="サンプル会社",
        confidence=0.6,
        status=ProfileStatus.WEAK,
        evidence=[ProfileEvidence(post_id=POST_ID, clue_index=2, required=True)],
    )

    assert item.evidence[0].post_id == POST_ID
    assert item.evidence[0].clue_index == 2
    assert item.evidence[0].required is True


@pytest.mark.parametrize(
    "data",
    [
        {"attribute": "not_a_profile_attribute"},
        {
            "attribute": "workplace",
            "value": None,
            "confidence": 1.01,
            "status": "found",
            "evidence": [],
        },
        {
            "attribute": "workplace",
            "value": None,
            "confidence": 0.5,
            "status": "missing",
            "evidence": [],
        },
        {
            "attribute": "workplace",
            "value": None,
            "confidence": 0.5,
            "status": "found",
            "evidence": [],
        },
        {
            "attribute": "workplace",
            "value": "会社",
            "confidence": 0.5,
            "status": "unknown",
            "evidence": [],
        },
        {
            "attribute": "workplace",
            "value": "  ",
            "confidence": 0.5,
            "status": "weak",
            "evidence": [],
        },
        {
            "attribute": "workplace",
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
