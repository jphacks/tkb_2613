"""X 投稿に明記された公開情報だけを、推定せずに整理する。"""

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tkb_common.schemas import Post

PublicInfoCategory = Literal["place", "station", "weekday", "time", "school"]


class PublicInfoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    post_id: str
    quote: str


class PublicInfoItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: PublicInfoCategory
    value: str
    count: int
    evidence: list[PublicInfoEvidence]


_WEEKDAY = re.compile(r"(?P<value>[月火水木金土日](?:曜日|曜))")
_TIME = re.compile(r"(?<!\d)(?P<value>(?:[01]?\d|2[0-3])(?::[0-5]\d|時(?:[0-5]?\d分)?))(?!\d)")
_STATION = re.compile(
    r"(?:^|[\s、。！？!?,「『（(])(?P<value>[一-龥ぁ-んァ-ヶA-Za-z0-9・ー]{1,12}駅)"
)
_SCHOOL = re.compile(
    r"(?:^|[\s、。！？!?,「『（(])"
    r"(?P<value>[一-龥ぁ-んァ-ヶA-Za-z0-9・ー]{1,20}(?:小学校|中学校|高校|大学))"
)
_PLACE = re.compile(
    r"(?:^|[\s、。！？!?,「『（(])"
    r"(?P<value>[一-龥ぁ-んァ-ヶA-Za-z0-9・ー]{1,12}(?:都|道|府|県|市|区|町|村))"
)

_PATTERNS: tuple[tuple[PublicInfoCategory, re.Pattern[str]], ...] = (
    ("station", _STATION),
    ("weekday", _WEEKDAY),
    ("time", _TIME),
    ("school", _SCHOOL),
    ("place", _PLACE),
)


def _normalized(category: PublicInfoCategory, value: str) -> str:
    if category == "weekday" and value.endswith("曜"):
        return f"{value}日"
    return value


def extract_public_information(posts: Iterable[Post]) -> list[PublicInfoItem]:
    """本文に実際に現れる限定カテゴリだけを正規表現で抽出・集計する。

    住所、勤務先、居住地域などを導出する知識表や推論エンジンは呼ばない。
    """
    grouped: dict[tuple[PublicInfoCategory, str], list[PublicInfoEvidence]] = {}
    for post in posts:
        seen_in_post: set[tuple[PublicInfoCategory, str]] = set()
        for category, pattern in _PATTERNS:
            for match in pattern.finditer(post.text):
                quote = match.group("value")
                value = _normalized(category, quote)
                key = (category, value)
                if key in seen_in_post:
                    continue
                seen_in_post.add(key)
                grouped.setdefault(key, []).append(
                    PublicInfoEvidence(post_id=post.post_id, quote=quote)
                )
    return [
        PublicInfoItem(category=category, value=value, count=len(evidence), evidence=evidence)
        for (category, value), evidence in grouped.items()
    ]


def public_information_json(posts: Iterable[Post]) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in extract_public_information(posts)]
