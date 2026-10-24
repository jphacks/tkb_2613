import io
from typing import Any

from PIL import Image

from tkb_common.schemas import Clue, ClueSource, ClueType
from tkb_detect.image import ZOOM_MIN_LONG_SIDE, crop_and_enlarge
from tkb_detect.zoom import (
    MAX_ZOOMS_PER_IMAGE,
    SMALL_REGION_MAX_CONFIDENCE,
    clean_value,
    normalize_reading,
    resolve_zoom,
    select_zoom_targets,
)

POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx"


def _clue(
    type_: ClueType,
    value: str,
    region: tuple[int, int, int, int] | None,
    confidence: float = 0.9,
) -> Clue:
    return Clue(
        post_id=POST_ID,
        image_index=0,
        type=type_,
        value=value,
        region=region,
        confidence=confidence,
        source=ClueSource.VLM,
    )


def _item(type_: str, value: str, confidence: float = 0.9) -> dict[str, Any]:
    return {"type": type_, "value": value, "confidence": confidence}


# 短い辺が 25px の縦書きの看板
SMALL_SIGN = _clue(ClueType.ORG_TEXT, "サロンロコ厚生", (900, 400, 925, 500))


class TestSelectZoomTargets:
    def test_picks_small_text_and_reflections_smallest_first(self) -> None:
        big_sign = _clue(ClueType.STATION_SIGN, "根津", (500, 400, 1300, 700))
        plate = _clue(ClueType.PLATE, "160", (900, 600, 960, 619))
        reflection = _clue(ClueType.REFLECTION, "瞳に何か映っている", (600, 200, 700, 300))
        face = _clue(ClueType.FACE, "1人", (10, 10, 30, 30))
        no_region = _clue(ClueType.SHOP, "店", None)

        targets = select_zoom_targets([big_sign, SMALL_SIGN, face, reflection, plate, no_region])

        # 大きい駅名標、顔、位置のないものは選ばない。映り込みは大きくても選ぶ
        assert targets == [plate, SMALL_SIGN, reflection]

    def test_limits_the_number_per_image(self) -> None:
        many = [_clue(ClueType.SHOP, f"店{i}", (0, 0, 10 + i, 10 + i)) for i in range(6)]

        assert len(select_zoom_targets(many)) == MAX_ZOOMS_PER_IMAGE


class TestResolveZoom:
    def test_same_reading_lifts_the_small_region_cap(self) -> None:
        resolved = resolve_zoom(SMALL_SIGN, [_item("org_text", "サロン ロコ 厚生", 0.8)])

        assert [(c.value, c.confidence) for c in resolved] == [("サロンロコ厚生", 0.8)]

    def test_different_reading_uses_the_zoomed_one_but_caps_confidence(self) -> None:
        resolved = resolve_zoom(SMALL_SIGN, [_item("org_text", "サロンロコ弥生", 0.95)])

        assert [(c.value, c.confidence) for c in resolved] == [
            ("サロンロコ弥生", SMALL_REGION_MAX_CONFIDENCE)
        ]
        assert resolved[0].region == SMALL_SIGN.region

    def test_falls_back_to_another_reading_type_when_type_differs(self) -> None:
        resolved = resolve_zoom(SMALL_SIGN, [_item("shop", "サロンロコ弥生", 0.9)])

        assert resolved[0].type is ClueType.ORG_TEXT
        assert resolved[0].value == "サロンロコ弥生"

    def test_nothing_readable_keeps_the_first_reading_capped(self) -> None:
        resolved = resolve_zoom(SMALL_SIGN, [_item("face", "1人"), {"type": "nope"}])

        assert [(c.value, c.confidence) for c in resolved] == [
            ("サロンロコ厚生", SMALL_REGION_MAX_CONFIDENCE)
        ]

    def test_reflection_adds_what_can_be_read_inside(self) -> None:
        reflection = _clue(ClueType.REFLECTION, "瞳に看板が映っている", (600, 200, 640, 230))

        resolved = resolve_zoom(
            reflection,
            [_item("shop", "Akafudado", 0.9), _item("reflection", "看板", 0.9)],
        )

        assert [(c.type, c.value, c.confidence, c.region) for c in resolved] == [
            (ClueType.REFLECTION, "瞳に看板が映っている", 0.5, (600, 200, 640, 230)),
            (ClueType.SHOP, "Akafudado", 0.5, (600, 200, 640, 230)),
        ]

    def test_ignores_malformed_items(self) -> None:
        items: list[dict[str, Any]] = [
            {"type": "org_text", "value": "", "confidence": 0.9},
            {"type": "org_text", "value": "a", "confidence": True},
            {"type": 1, "value": "a", "confidence": 0.9},
        ]

        assert resolve_zoom(SMALL_SIGN, items)[0].value == "サロンロコ厚生"


def test_normalize_reading_absorbs_spelling_variants() -> None:
    assert normalize_reading("向ヶ岡 弥生町会") == normalize_reading("向ケ岡弥生町会")
    assert normalize_reading("ＡＫＡＦＵＤＡＤＯ") == normalize_reading("Akafudado")


def test_crop_and_enlarge_cuts_around_the_region_and_scales_up() -> None:
    image = Image.new("RGB", (1477, 1108), "white")
    buf = io.BytesIO()
    image.save(buf, "JPEG")

    crop = crop_and_enlarge(buf.getvalue(), (900, 400, 925, 500))

    with Image.open(io.BytesIO(crop)) as out:
        assert out.format == "JPEG"
        assert max(out.size) >= ZOOM_MIN_LONG_SIDE
        # 縦長の看板は縦長のまま
        assert out.height > out.width


def test_clean_value_joins_lines_and_spaces() -> None:
    assert clean_value(" xx 302\nxx・160 ") == "xx 302 xx・160"
