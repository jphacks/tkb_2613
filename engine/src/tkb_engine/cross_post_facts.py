"""投稿を横断する推定の材料（事実）の型。cross_post と open_data で共有する。"""

from dataclasses import dataclass
from enum import StrEnum

from tkb_common.schemas import ProfileEvidence


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
