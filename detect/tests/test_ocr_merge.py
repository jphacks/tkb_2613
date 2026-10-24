from tkb_common.schemas import Clue, ClueSource, ClueType
from tkb_detect.ocr_client import OcrLine
from tkb_detect.ocr_merge import merge_ocr

POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx"


def _vlm(type_: ClueType, value: str, region: tuple[int, int, int, int] | None) -> Clue:
    return Clue(
        post_id=POST_ID,
        image_index=0,
        type=type_,
        value=value,
        region=region,
        confidence=0.7,
        source=ClueSource.VLM,
    )


def test_uses_ocr_box_when_text_matches_and_boxes_overlap() -> None:
    clue = _vlm(ClueType.SHOP, "麺屋そらまめ", (300, 40, 900, 160))
    lines = [OcrLine(text="麺屋 そらまめ", score=0.95, box=(310, 45, 880, 150))]

    merged = merge_ocr(POST_ID, 0, [clue], lines)

    assert merged[0].region == (310, 45, 880, 150)
    assert merged[0].source is ClueSource.VLM


def test_fills_missing_region_from_ocr() -> None:
    clue = _vlm(ClueType.STATION_SIGN, "西船橋", None)
    lines = [OcrLine(text="西船橋", score=0.9, box=(10, 10, 200, 60))]

    assert merge_ocr(POST_ID, 0, [clue], lines)[0].region == (10, 10, 200, 60)


def test_keeps_vlm_region_when_ocr_box_is_elsewhere() -> None:
    clue = _vlm(ClueType.SHOP, "そらまめ", (0, 0, 100, 100))
    lines = [OcrLine(text="そらまめ", score=0.9, box=(500, 500, 600, 600))]

    assert merge_ocr(POST_ID, 0, [clue], lines)[0].region == (0, 0, 100, 100)


def test_adds_postal_code_and_phone_found_only_by_ocr() -> None:
    lines = [
        OcrLine(text="〒273－0031 船橋市", score=0.88, box=(10, 10, 300, 40)),
        OcrLine(text="TEL 047-000-0000", score=0.8, box=(10, 50, 300, 80)),
    ]

    merged = merge_ocr(POST_ID, 0, [], lines)

    assert [(c.type, c.value, c.source) for c in merged] == [
        (ClueType.POSTAL_CODE, "273-0031", ClueSource.OCR),
        (ClueType.PHONE, "047-000-0000", ClueSource.OCR),
    ]
    assert merged[0].region == (10, 10, 300, 40)


def test_does_not_duplicate_numbers_the_vlm_already_found() -> None:
    clue = _vlm(ClueType.POSTAL_CODE, "273-0031", (10, 10, 300, 40))
    lines = [OcrLine(text="273-0031", score=0.88, box=(10, 10, 300, 40))]

    merged = merge_ocr(POST_ID, 0, [clue], lines)

    assert len(merged) == 1


def test_ignores_ocr_lines_without_area() -> None:
    lines = [OcrLine(text="273-0031", score=0.88, box=(10, 10, 10, 40))]

    assert merge_ocr(POST_ID, 0, [], lines) == []
