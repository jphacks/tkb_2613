from typing import Any

import pytest
from pydantic import ValidationError

from tkb_common.schemas import Clue, ClueSource, ClueType, DetectResponse

POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx"

PHOTO_CLUE: dict[str, Any] = {
    "post_id": POST_ID,
    "image_index": 0,
    "type": "station_sign",
    "value": "新宿",
    "region": [120, 80, 340, 150],
    "confidence": 0.92,
    "source": "vlm",
}

TEXT_CLUE: dict[str, Any] = {
    "post_id": POST_ID,
    "image_index": None,
    "type": "routine_text",
    "value": "夜勤明け",
    "region": None,
    "confidence": 0.9,
    "source": "text",
}


def test_parses_photo_clue_in_documented_format() -> None:
    clue = Clue.model_validate(PHOTO_CLUE)

    assert clue.type is ClueType.STATION_SIGN
    assert clue.image_index == 0
    assert clue.region == (120, 80, 340, 150)
    assert clue.source is ClueSource.VLM


def test_parses_text_clue_without_image_or_region() -> None:
    clue = Clue.model_validate(TEXT_CLUE)

    assert clue.image_index is None
    assert clue.region is None
    assert clue.source is ClueSource.TEXT


def test_photo_clue_may_have_no_region() -> None:
    clue = Clue.model_validate({**PHOTO_CLUE, "type": "uniform", "region": None})

    assert clue.region is None


def test_both_sources_clue_types_accept_photo_and_text() -> None:
    Clue.model_validate({**PHOTO_CLUE, "type": "name_text", "value": "ゆうき"})
    Clue.model_validate({**TEXT_CLUE, "type": "name_text", "value": "ゆうき"})


@pytest.mark.parametrize("data", [PHOTO_CLUE, TEXT_CLUE])
def test_serializes_back_to_documented_json_shape(data: dict[str, Any]) -> None:
    response = DetectResponse(clues=[Clue.model_validate(data)])

    assert response.model_dump(mode="json") == {"clues": [data]}


def test_covers_all_documented_types_and_sources() -> None:
    assert {t.value for t in ClueType} == {
        "station_sign", "rail_view", "reflection", "shop", "landmark", "address_text",
        "postal_code", "phone", "plate", "uniform", "face", "key", "code",
        "name_text", "org_text", "handle_text", "place_text",
        "age_text", "routine_text", "relation_text",
    }  # fmt: skip
    assert {s.value for s in ClueSource} == {"ocr", "vlm", "text", "meta"}


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_rejects_confidence_outside_unit_range(confidence: float) -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**PHOTO_CLUE, "confidence": confidence})


@pytest.mark.parametrize(
    "region",
    [
        [340, 80, 120, 150],  # 右下が左上より左
        [120, 150, 340, 80],  # 右下が左上より上
        [-1, 80, 340, 150],  # 負の座標
        [120, 80, 340],  # 要素数不足
    ],
)
def test_rejects_invalid_region(region: list[int]) -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**PHOTO_CLUE, "region": region})


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("本文の手がかりに region", {**TEXT_CLUE, "region": [0, 0, 10, 10]}),
        ("本文の手がかりに image_index", {**TEXT_CLUE, "image_index": 0}),
        ("写真の手がかりに image_index がない", {**PHOTO_CLUE, "image_index": None}),
        ("source が text なのに写真", {**PHOTO_CLUE, "type": "name_text", "source": "text"}),
        ("写真だけの type を本文から", {**TEXT_CLUE, "type": "station_sign"}),
        ("本文だけの type を写真から", {**PHOTO_CLUE, "type": "age_text", "region": None}),
        ("負の image_index", {**PHOTO_CLUE, "image_index": -1}),
        ("post_id が空", {**PHOTO_CLUE, "post_id": ""}),
        ("post_id がない", {k: v for k, v in PHOTO_CLUE.items() if k != "post_id"}),
    ],
)
def test_rejects_inconsistent_clue(label: str, data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate(data)


@pytest.mark.parametrize(("field", "value"), [("type", "unknown"), ("source", "browser")])
def test_rejects_unknown_enum_value(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**PHOTO_CLUE, field: value})


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**PHOTO_CLUE, "extra": 1})
