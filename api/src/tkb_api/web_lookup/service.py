"""診断の結論から検索語を作り、検索 → 照合 → ページの要約までをつなぐ。"""

import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from tkb_api.web_lookup.fetch import (
    FetchError,
    PageSummary,
    Resolver,
    UnsafeUrlError,
    fetch_page,
    resolve_host,
)
from tkb_api.web_lookup.judge import Profile, candidates, choose
from tkb_api.web_lookup.search import SearchResult, search
from tkb_detect.vlm_client import VlmClient
from tkb_engine.rules import Conclusion

logger = logging.getLogger(__name__)

# 名前だけが一致した結果のうち、ページを開いて学校・年齢を確かめる件数
MAX_PAGES_TO_CHECK = 3


@dataclass(frozen=True)
class LookupResult:
    """見つかった本人らしいページ。image は og:image の URL（2段目の写真で使う）。"""

    query: str
    url: str
    site: str
    title: str
    description: str
    matched: tuple[str, ...]
    image: str | None


def profile_from(conclusions: Sequence[Conclusion]) -> Profile | None:
    """フルネームがなければ None（名前なしでは検索しない）。"""
    by_attribute = {c.attribute: c.value for c in conclusions}
    full_name = by_attribute.get("full_name")
    if not full_name:
        return None
    age = re.match(r"(\d{1,3})歳", by_attribute.get("age", ""))
    return Profile(
        full_name=full_name, school=by_attribute.get("school"), age=int(age[1]) if age else None
    )


def build_query(profile: Profile) -> str:
    return " ".join(part for part in (f'"{profile.full_name}"', profile.school) if part)


async def lookup(
    client: httpx.AsyncClient,
    vlm: VlmClient,
    search_base_url: str,
    profile: Profile,
    resolve: Resolver = resolve_host,
) -> tuple[str, LookupResult | None]:
    """(検索語, 見つかったページ)。見つからなければページは None。"""
    started = time.monotonic()
    query = build_query(profile)
    results = await search(client, search_base_url, query)
    texts = [f"{r.title} {r.snippet}" for r in results]
    pages: dict[int, PageSummary] = {}

    found = candidates(profile, texts)
    if not found:
        # 検索結果の短い説明に学校・年齢がなければ、名前が一致したページを開いて確かめる
        pages = await _open_name_matches(client, profile, results, texts, resolve)
        texts = [
            f"{t} {pages[i].title} {pages[i].description}" if i in pages else t
            for i, t in enumerate(texts)
        ]
        found = candidates(profile, texts)

    chosen = await choose(vlm, profile, texts, found)
    logger.info(
        "照合の時間：%.1f 秒（検索 %d 件、候補 %d 件、見つかった %s）",
        time.monotonic() - started,
        len(results),
        len(found),
        "はい" if chosen else "いいえ",
    )
    if chosen is None:
        return query, None

    hit = results[chosen.index]
    page = pages.get(chosen.index) or await _try_fetch(client, hit.url, resolve)
    return query, LookupResult(
        query=query,
        url=page.url if page else hit.url,
        site=urlparse(page.url if page else hit.url).hostname or "",
        title=(page.title if page and page.title else hit.title),
        description=(page.description if page and page.description else hit.snippet),
        matched=chosen.matched,
        image=page.image if page else None,
    )


async def _open_name_matches(
    client: httpx.AsyncClient,
    profile: Profile,
    results: Sequence[SearchResult],
    texts: Sequence[str],
    resolve: Resolver,
) -> dict[int, PageSummary]:
    name = "".join(profile.full_name.split())
    pages: dict[int, PageSummary] = {}
    for i, text in enumerate(texts):
        if len(pages) == MAX_PAGES_TO_CHECK:
            break
        if name in "".join(text.split()) and (
            page := await _try_fetch(client, results[i].url, resolve)
        ):
            pages[i] = page
    return pages


async def _try_fetch(client: httpx.AsyncClient, url: str, resolve: Resolver) -> PageSummary | None:
    try:
        return await fetch_page(client, url, resolve)
    except (UnsafeUrlError, FetchError):
        return None
