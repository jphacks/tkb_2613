"""手がかりの形式。正は tkb_common.schemas で、ここは互換のために読み込み直すだけ。"""

from tkb_common.schemas import (
    PHOTO_ONLY_TYPES,
    PHOTO_SOURCES,
    TEXT_ONLY_TYPES,
    Clue,
    ClueSource,
    ClueType,
    DetectResponse,
    NonNegativeInt,
    Region,
)

__all__ = [
    "PHOTO_ONLY_TYPES",
    "PHOTO_SOURCES",
    "TEXT_ONLY_TYPES",
    "Clue",
    "ClueSource",
    "ClueType",
    "DetectResponse",
    "NonNegativeInt",
    "Region",
]
