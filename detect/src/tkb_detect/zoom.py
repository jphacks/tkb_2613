"""2段階の読み取り。1回目で見つけた小さい文字や映り込みを、拡大してもう一度読ませる。

- 対象：文字の手がかりで枠の短い辺が ZOOM_MAX_SIDE_PX 未満のものと、reflection。
  小さい順に、写真1枚あたり MAX_ZOOMS_PER_IMAGE 件まで
- 読みが一致した：小さくても confidence の上限（SMALL_REGION_MAX_CONFIDENCE）を外す
- 読みが食い違った：拡大したほうの読みを使い、confidence は上限まで
- 映り込み：中に読める看板などがあれば、その type の手がかりを足す（confidence は上限まで）
"""

import re
import unicodedata
from typing import Any

from tkb_common.schemas import Clue, ClueType

# 拡大して読み直す対象の、枠の短い辺（元の画像のピクセル）
ZOOM_MAX_SIDE_PX = 64
MAX_ZOOMS_PER_IMAGE = 3
SMALL_REGION_MIN_SIDE_PX = 32
SMALL_REGION_MAX_CONFIDENCE = 0.5

READING_TYPES = frozenset(
    {
        ClueType.STATION_SIGN,
        ClueType.SHOP,
        ClueType.ADDRESS_TEXT,
        ClueType.POSTAL_CODE,
        ClueType.PHONE,
        ClueType.PLATE,
        ClueType.ORG_TEXT,
        ClueType.NAME_TEXT,
        ClueType.PLACE_TEXT,
        ClueType.HANDLE_TEXT,
    }
)


def _short_side(clue: Clue) -> int | None:
    if clue.region is None:
        return None
    x1, y1, x2, y2 = clue.region
    return min(x2 - x1, y2 - y1)


def select_zoom_targets(clues: list[Clue]) -> list[Clue]:
    """拡大して読み直す手がかりを、小さい順に選ぶ。"""
    targets = []
    for clue in clues:
        side = _short_side(clue)
        if side is None:
            continue
        if clue.type is ClueType.REFLECTION or (
            clue.type in READING_TYPES and side < ZOOM_MAX_SIDE_PX
        ):
            targets.append((side, clue))
    targets.sort(key=lambda t: t[0])
    return [clue for _, clue in targets[:MAX_ZOOMS_PER_IMAGE]]


def cap_small_region(clue: Clue) -> Clue:
    """小さく写った手がかりの confidence を上限までにする。"""
    side = _short_side(clue)
    if side is None or side >= SMALL_REGION_MIN_SIDE_PX:
        return clue
    return clue.model_copy(update={"confidence": min(clue.confidence, SMALL_REGION_MAX_CONFIDENCE)})


def clean_value(text: str) -> str:
    """値の中の改行や続いた空白を、空白1つにまとめる（「xx 302\nxx・160」など）。"""
    return " ".join(text.split())


def normalize_reading(text: str) -> str:
    """表記ゆれ（全角・半角、空白、ヶ/ケ、大文字・小文字）をそろえて比べる。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("ヶ", "ケ").replace("ヵ", "カ")
    return re.sub(r"[\s・･]", "", text)


def _readings(items: list[dict[str, Any]]) -> list[tuple[ClueType, str, float]]:
    readings = []
    for item in items:
        raw_type = item.get("type")
        if not isinstance(raw_type, str) or raw_type not in ClueType:
            continue
        clue_type = ClueType(raw_type)
        value, confidence = item.get("value"), item.get("confidence")
        if not isinstance(value, str) or not value.strip():
            continue
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            continue
        readings.append((clue_type, clean_value(value), min(max(float(confidence), 0.0), 1.0)))
    return readings


def resolve_zoom(target: Clue, items: list[dict[str, Any]]) -> list[Clue]:
    """拡大して読んだ結果（VLM の clues の項目）で、target を置き換える手がかりを返す。"""
    readings = _readings(items)

    if target.type is ClueType.REFLECTION:
        found = [
            target.model_copy(
                update={
                    "type": clue_type,
                    "value": value,
                    "confidence": min(confidence, SMALL_REGION_MAX_CONFIDENCE),
                }
            )
            for clue_type, value, confidence in readings
            if clue_type in READING_TYPES
        ]
        return [cap_small_region(target), *found]

    same_type = [r for r in readings if r[0] is target.type]
    candidates = same_type or [r for r in readings if r[0] in READING_TYPES]
    if not candidates:
        return [cap_small_region(target)]

    wanted = normalize_reading(target.value)
    for _, value, confidence in candidates:
        if normalize_reading(value) == wanted:
            # 2回とも同じに読めた。小さくても上限はかけない
            return [target.model_copy(update={"confidence": min(target.confidence, confidence)})]

    # 食い違った。拡大したほうの読みを使うが、強くは信じない
    _, value, confidence = max(candidates, key=lambda r: r[2])
    return [
        target.model_copy(
            update={"value": value, "confidence": min(confidence, SMALL_REGION_MAX_CONFIDENCE)}
        )
    ]
