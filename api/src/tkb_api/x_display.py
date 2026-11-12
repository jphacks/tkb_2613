"""X の表示要件（Display requirements: Posts）に必要な情報だけを、X の応答から取り出す。

https://docs.x.com/developer-terms/display-requirements
- 投稿者：アイコン・表示名・@ユーザー名を出し、X のプロフィールへリンクする
- 本文：改変しない。@メンションはプロフィール、ハッシュタグは X の検索、URL は display_url を
  出して t.co へリンクする
- 日時：permalink へリンクする。編集された投稿はそう表記する

合成デモの架空投稿は X に存在しないので、permalink やリンクを作らない（synthetic=True）。
"""

import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_HASHTAG = re.compile(r"^\w{1,139}$")
# X のプロフィール画像の配信元
_AVATAR_HOSTS = frozenset({"pbs.twimg.com", "abs.twimg.com"})


class XAuthor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    name: str
    profile_image_url: str | None
    profile_url: str | None


class XEntity(BaseModel):
    """本文中のリンクの範囲。start・end は Unicode のコードポイント単位（X の仕様と同じ）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["mention", "hashtag", "url"]
    start: int
    end: int
    href: str
    # URL は本文の t.co ではなく display_url を出す。ほかは本文の文字をそのまま出す（None）
    display: str | None = None


class XPostDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    permalink: str | None
    edited: bool
    entities: list[XEntity]


def _https_url(value: object, hosts: frozenset[str] | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if hosts is not None and parsed.hostname not in hosts:
        return None
    return value


def author_from_profile(profile: dict[str, Any]) -> XAuthor:
    username = str(profile["username"])
    name = profile.get("name")
    safe_username = _USERNAME.fullmatch(username) is not None
    return XAuthor(
        username=username,
        name=name if isinstance(name, str) and name.strip() else username,
        profile_image_url=_https_url(profile.get("profile_image_url"), _AVATAR_HOSTS),
        profile_url=f"https://x.com/{username}" if safe_username else None,
    )


def synthetic_author(username: str) -> XAuthor:
    return XAuthor(username=username, name=username, profile_image_url=None, profile_url=None)


def _span(raw: dict[str, Any], length: int) -> tuple[int, int] | None:
    start, end = raw.get("start"), raw.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= length:
        return None
    return start, end


def _entity(kind: str, raw: object, length: int) -> XEntity | None:
    if not isinstance(raw, dict):
        return None
    span = _span(raw, length)
    if span is None:
        return None
    if kind == "mentions":
        username = raw.get("username")
        if isinstance(username, str) and _USERNAME.fullmatch(username):
            return XEntity(
                kind="mention", start=span[0], end=span[1], href=f"https://x.com/{username}"
            )
    elif kind == "hashtags":
        tag = raw.get("tag")
        if isinstance(tag, str) and _HASHTAG.fullmatch(tag):
            href = f"https://x.com/search?q=%23{tag}"
            return XEntity(kind="hashtag", start=span[0], end=span[1], href=href)
    elif kind == "urls":
        url = _https_url(raw.get("url"))
        display = raw.get("display_url")
        if url is not None and isinstance(display, str) and display:
            return XEntity(kind="url", start=span[0], end=span[1], href=url, display=display)
    return None


def post_display(item: dict[str, Any], author: XAuthor) -> XPostDisplay:
    """投稿1件の表示情報。範囲が本文に収まらない・重なるエンティティは捨てる（本文は変えない）。"""
    text = item.get("text")
    length = len(text) if isinstance(text, str) else 0
    raw_entities = item.get("entities")
    found: list[XEntity] = []
    if isinstance(raw_entities, dict):
        for kind in ("mentions", "hashtags", "urls"):
            values = raw_entities.get(kind)
            if isinstance(values, list):
                found.extend(e for e in (_entity(kind, v, length) for v in values) if e)
    entities: list[XEntity] = []
    for entity in sorted(found, key=lambda e: e.start):
        if not entities or entities[-1].end <= entity.start:
            entities.append(entity)
    history = item.get("edit_history_tweet_ids")
    post_id = str(item.get("id", ""))
    permalink = (
        f"https://x.com/{author.username}/status/{post_id}"
        if author.profile_url is not None and post_id.isdecimal()
        else None
    )
    return XPostDisplay(
        permalink=permalink,
        edited=isinstance(history, list) and len(history) > 1,
        entities=entities,
    )


def synthetic_display() -> XPostDisplay:
    return XPostDisplay(permalink=None, edited=False, entities=[])
