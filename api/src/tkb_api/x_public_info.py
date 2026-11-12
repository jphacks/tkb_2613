"""X 投稿に明記された公開情報だけを、推定せずに整理する。"""

import logging
import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tkb_common.schemas import Post

logger = logging.getLogger(__name__)
# 失敗した投稿に付ける理由。投稿本文や例外の文言は入れない。
POST_ERROR_MESSAGE = "この投稿は読み取れませんでした"

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


def _post_matches(post: Post) -> list[tuple[PublicInfoCategory, str, str]]:
    """1件の投稿から (カテゴリ, 正規化した値, 本文中の引用) を重複なしで返す。"""
    found: list[tuple[PublicInfoCategory, str, str]] = []
    seen: set[tuple[PublicInfoCategory, str]] = set()
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(post.text):
            quote = match.group("value")
            value = _normalized(category, quote)
            if (category, value) in seen:
                continue
            seen.add((category, value))
            found.append((category, value, quote))
    return found


def extract_public_information_with_errors(
    posts: Iterable[Post],
) -> tuple[list[PublicInfoItem], list[dict[str, str]]]:
    """本文に実際に現れる限定カテゴリだけを正規表現で抽出・集計する。

    住所、勤務先、居住地域などを導出する知識表や推論エンジンは呼ばない。
    1件の投稿で失敗しても全体は止めず、その投稿を post_errors として返す。
    """
    grouped: dict[tuple[PublicInfoCategory, str], list[PublicInfoEvidence]] = {}
    post_errors: list[dict[str, str]] = []
    for post in posts:
        try:
            matches = _post_matches(post)
        except Exception as exc:  # 投稿単位で隔離し、全体は成功にする
            # 本文を含みうる例外メッセージは出さず、型名だけ残す
            logger.warning("X post extraction failed: %s", type(exc).__name__)
            post_errors.append({"post_id": post.post_id, "error": POST_ERROR_MESSAGE})
            continue
        for category, value, quote in matches:
            grouped.setdefault((category, value), []).append(
                PublicInfoEvidence(post_id=post.post_id, quote=quote)
            )
    items = [
        PublicInfoItem(category=category, value=value, count=len(evidence), evidence=evidence)
        for (category, value), evidence in grouped.items()
    ]
    return items, post_errors


def extract_public_information(posts: Iterable[Post]) -> list[PublicInfoItem]:
    return extract_public_information_with_errors(posts)[0]


def public_information_json(posts: Iterable[Post]) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in extract_public_information(posts)]


def public_information_report(
    posts: Iterable[Post],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    items, post_errors = extract_public_information_with_errors(posts)
    return [item.model_dump(mode="json") for item in items], post_errors
