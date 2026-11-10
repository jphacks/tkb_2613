import pytest

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


def test_emits_high_confidence_literal_company_bridge_with_original_region() -> None:
    line = OcrLine(text="株式会社青空の青空物流センター", score=0.93, box=(20, 30, 420, 75))

    clues = merge_ocr(POST_ID, 2, [], [line])

    assert len(clues) == 1
    clue = clues[0]
    assert (clue.type, clue.value, clue.source) == (ClueType.ORG_TEXT, line.text, ClueSource.OCR)
    assert clue.image_index == 2
    assert clue.region == line.box


@pytest.mark.parametrize("text,score", [
    ("株式会社青空の青空物流センター", 0.79),
    ("ロゴ 株式会社青空の青空物流センター", 0.99),
    ("青空の青空物流センター", 0.99),
    ("合同会社青空の青空物流センター", 0.99),
])
def test_rejects_weak_or_nonliteral_company_bridge_lines(text: str, score: float) -> None:
    assert merge_ocr(POST_ID, 0, [], [OcrLine(text, score, (10, 10, 300, 50))]) == []


def test_ocr_station_text_requires_same_name_vlm_sign_context() -> None:
    lines = [
        OcrLine(text="根津", score=0.94, box=(20, 30, 180, 70)),
        OcrLine(text="湯島", score=0.92, box=(20, 80, 180, 120)),
        OcrLine(text="未登録", score=0.99, box=(20, 130, 180, 170)),
        OcrLine(text="根x", score=0.99, box=(20, 180, 180, 220)),
        OcrLine(text="千駄木", score=0.79, box=(20, 230, 180, 270)),
    ]

    # A Gazetteer match alone cannot distinguish a station sign from a map or ad.
    assert merge_ocr(POST_ID, 1, [], lines, station_names={"根津", "湯島", "千駄木"}) == []

    vlm = [
        Clue(post_id=POST_ID, image_index=1, type=ClueType.STATION_SIGN, value="根津",
             region=(25, 35, 175, 65), confidence=0.9, source=ClueSource.VLM),
        Clue(post_id=POST_ID, image_index=1, type=ClueType.STATION_SIGN, value="湯島",
             region=(25, 85, 175, 115), confidence=0.9, source=ClueSource.VLM),
    ]
    clues = merge_ocr(POST_ID, 1, vlm, lines, station_names={"根津", "湯島", "千駄木"})

    station_clues = [clue for clue in clues if clue.type is ClueType.STATION_SIGN]
    assert [(clue.value, clue.source, clue.image_index, clue.region) for clue in station_clues] == [
        ("根津", ClueSource.OCR, 1, (20, 30, 180, 70)),
        ("湯島", ClueSource.OCR, 1, (20, 80, 180, 120)),
    ]


def test_station_name_suffix_is_removed_before_exact_match_with_vlm_context() -> None:
    vlm = Clue(post_id=POST_ID, image_index=0, type=ClueType.STATION_SIGN,
               value="根津駅", region=(1, 2, 80, 30), confidence=0.9, source=ClueSource.VLM)
    clue = merge_ocr(
        POST_ID, 0, [vlm], [OcrLine(text="根津駅", score=0.9, box=(1, 2, 80, 30))],
        station_names={"根津"},
    )

    clue = next(clue for clue in clue if clue.source is ClueSource.OCR)
    assert clue.value == "根津"
    assert clue.region == (1, 2, 80, 30)


def test_station_ocr_rejects_mismatched_or_nonoverlapping_vlm_context() -> None:
    line = [OcrLine("根津", 0.95, (1, 2, 80, 30))]
    for value, region in (("湯島", (1, 2, 80, 30)), ("根津", (100, 100, 180, 140)),
                          ("根津", None)):
        vlm = Clue(post_id=POST_ID, image_index=0, type=ClueType.STATION_SIGN,
                   value=value, region=region, confidence=0.9, source=ClueSource.VLM)
        merged = merge_ocr(POST_ID, 0, [vlm], line, station_names={"根津", "湯島"})
        assert all(clue.source is not ClueSource.OCR for clue in merged)




def test_station_ocr_clue_survives_same_value_vlm_clue() -> None:
    vlm = Clue(post_id=POST_ID, image_index=0, type=ClueType.STATION_SIGN,
               value="根津", region=(1, 2, 80, 30), confidence=0.9, source=ClueSource.VLM)
    merged = merge_ocr(
        POST_ID, 0, [vlm], [OcrLine("根津", 0.95, (1, 2, 80, 30))], station_names={"根津"},
    )

    assert {clue.source for clue in merged if clue.type is ClueType.STATION_SIGN} == {
        ClueSource.VLM, ClueSource.OCR,
    }
