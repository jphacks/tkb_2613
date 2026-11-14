"""投稿を横断する推定の材料（事実）の型。cross_post と open_data で共有する。"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from tkb_common.schemas import Clue, ClueSource, ClueType, ProfileEvidence


class FactRole(StrEnum):
    OWNER_RELATION = "owner_relation"
    SPECIFIC_VALUE = "specific_value"
    BRIDGE = "bridge"


@dataclass(frozen=True)
class CrossPostFact:
    post_id: str | None
    clue_index: int | None
    role: FactRole
    value: str
    confidence: float
    # An explicit phrase, identifier, or other observed bridge connecting this fact to the
    # same owner-related entity. Do not use a mere visit, logo, or location coincidence.
    bridge_id: str | None
    owner_relation_explicit: bool = False
    context: str = ""
    excerpt: str = ""
    related_evidence: tuple[ProfileEvidence, ...] = ()
    source: str = "post_text"


def forbidden_context(context: str) -> bool:
    """訪問・見学・取引先など、本人の住まいや勤め先を示さない文脈。"""
    value = context.casefold()
    return any(
        token in value
        for token in (
            "visitor",
            "logo-only",
            "visit-only",
            "guest",
            "訪問",
            "見学",
            "遊びに",
            "客として",
            "来場",
            "参加者として",
            "取引先",
            "委託",
            "外注",
            "派遣先",
        )
    )


def normalize_bridge(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def is_distinctive_bridge(value: str) -> bool:
    """Require a named bridge, rejecting generic nouns such as 研修 or 商店街."""
    bridge = normalize_bridge(value)
    generic_suffixes = (
        "商店街",
        "ショッピングモール",
        "モール",
        "研修",
        "研修会",
        "駅",
        "商店",
        "店",
        "会社",
        "ビル",
        "オフィス",
        "病院",
        "学校",
        "公園",
        "通り",
        "施設",
    )
    for suffix in generic_suffixes:
        if bridge.endswith(suffix):
            name = bridge[: -len(suffix)]
            return len(name) >= 2 and any(ch.isalnum() or "\u3040" <= ch <= "\u9fff" for ch in name)
    return len(bridge) >= 3 and any(ch.isalpha() for ch in bridge)


def matching_text_clue(
    clues: Sequence[Clue], post_id: str, value: str, clue_type: ClueType
) -> tuple[int, Clue] | None:
    for index, clue in enumerate(clues):
        if (
            clue.post_id == post_id
            and clue.source is ClueSource.TEXT
            and clue.type is clue_type
            and normalize_bridge(clue.value) == normalize_bridge(value)
        ):
            return index, clue
    return None
