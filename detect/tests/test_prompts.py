from tkb_common.schemas import ClueType
from tkb_detect.prompts import PHOTO_SYSTEM_PROMPT, TEXT_SYSTEM_PROMPT, TYPE_DESCRIPTIONS


def test_vehicle_model_is_described_in_photo_and_text_prompt_types() -> None:
    assert ClueType.VEHICLE_MODEL in TYPE_DESCRIPTIONS
    description = TYPE_DESCRIPTIONS[ClueType.VEHICLE_MODEL]
    assert "車種" in description
    assert "形だけ" in description
    assert description in PHOTO_SYSTEM_PROMPT
    assert description in TEXT_SYSTEM_PROMPT
