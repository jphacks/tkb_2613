import pytest
from pydantic import ValidationError

from tkb_api.schemas import Clue, ClueSource, ClueType, DetectResponse

VALID = {
    "type": "station_sign",
    "value": "新宿",
    "region": [120, 80, 340, 150],
    "confidence": 0.92,
    "source": "vlm",
}


def test_parses_clue_in_documented_format() -> None:
    clue = Clue.model_validate(VALID)

    assert clue.type is ClueType.STATION_SIGN
    assert clue.region == (120, 80, 340, 150)
    assert clue.source is ClueSource.VLM


def test_serializes_back_to_documented_json_shape() -> None:
    response = DetectResponse(clues=[Clue.model_validate(VALID)])

    assert response.model_dump(mode="json") == {"clues": [VALID]}


def test_covers_all_documented_types_and_sources() -> None:
    assert {t.value for t in ClueType} == {
        "station_sign", "address_text", "postal_code", "phone", "shop", "plate",
        "landmark", "exif_gps", "face", "iris", "key", "code",
    }  # fmt: skip
    assert {s.value for s in ClueSource} == {"ocr", "vlm", "browser"}


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_rejects_confidence_outside_unit_range(confidence: float) -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**VALID, "confidence": confidence})


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
        Clue.model_validate({**VALID, "region": region})


def test_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**VALID, "type": "unknown"})


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Clue.model_validate({**VALID, "extra": 1})
