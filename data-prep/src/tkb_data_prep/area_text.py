"""「市外局番の一覧」の対象地域の文章を、都道府県・名前・但し書きに分ける。

例：「埼玉県川越市、富士見市（水谷東二丁目及び三丁目を除く。）、比企郡（川島町及び鳩山町に限る。）」
  → (埼玉県, 川越市, なし), (埼玉県, 富士見市, 水谷東二丁目及び三丁目を除く), ...
都道府県名は、次に別の都道府県名が出てくるまで引き継ぐ。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

OPEN, CLOSE = "（", "）"
PREFECTURE = re.compile(r"^(東京都|北海道|京都府|大阪府|.{2,3}?県)")
LIST_SEPARATORS = ("、", "及び", "並びに")


@dataclass(frozen=True)
class Item:
    pref: str
    name: str
    # 括弧の中の但し書き（末尾の「。」は除く）。なければ空
    qualifier: str


class Scope(Enum):
    LIMIT = "に限る"
    EXCLUDE = "を除く"


@dataclass(frozen=True)
class Qualified:
    """「A、B（…）及びCに限る」のような、市区町村を並べた但し書き。"""

    scope: Scope
    # (名前, その名前の括弧の中の但し書き)
    names: tuple[tuple[str, str], ...]


def split_top(text: str, separators: Sequence[str]) -> list[str]:
    """括弧の外にある区切りだけで分ける。"""
    parts: list[str] = []
    depth, start, i = 0, 0, 0
    while i < len(text):
        char = text[i]
        depth += (char == OPEN) - (char == CLOSE)
        sep = next((s for s in separators if depth == 0 and text.startswith(s, i)), None)
        if sep is None:
            i += 1
            continue
        parts.append(text[start:i])
        i += len(sep)
        start = i
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def split_name(text: str) -> tuple[str, str]:
    """「富士見市（水谷東二丁目を除く。）」→ (富士見市, 水谷東二丁目を除く)。"""
    if OPEN not in text or not text.endswith(CLOSE):
        return text, ""
    at = text.index(OPEN)
    return text[:at], text[at + 1 : -1].rstrip("。")


def parse_items(text: str) -> list[Item]:
    items: list[Item] = []
    pref = ""
    for part in split_top(text, ("、",)):
        match = PREFECTURE.match(part)
        if match:
            pref, part = match.group(1), part[match.end() :]
        name, qualifier = split_name(part)
        items.append(Item(pref=pref, name=name, qualifier=qualifier))
    return items


def parse_qualified(qualifier: str) -> Qualified | None:
    """市区町村を並べた但し書きでなければ None。"""
    scope = next((s for s in Scope if qualifier.endswith(s.value)), None)
    if scope is None:
        return None
    body = qualifier.removesuffix(scope.value)
    names = tuple(split_name(part) for part in split_top(body, LIST_SEPARATORS))
    return Qualified(scope=scope, names=names)
