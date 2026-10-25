"""SearXNG（チームのサーバーで動かすメタ検索）で検索する。送るのは検索語だけ。"""

from dataclasses import dataclass
from typing import Any

import httpx

from tkb_detect.errors import ForbiddenEndpointError
from tkb_detect.guard import ensure_team_endpoint

MAX_RESULTS = 10
SEARCH_TIMEOUT_S = 15.0


class SearchUnavailableError(Exception):
    """検索できなかった。検索語や URL は文言に入れない。"""


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


async def search(client: httpx.AsyncClient, base_url: str, query: str) -> list[SearchResult]:
    """上位 MAX_RESULTS 件の結果。形のおかしい結果は飛ばす。"""
    try:
        endpoint = ensure_team_endpoint(base_url)
    except ForbiddenEndpointError:
        raise SearchUnavailableError("検索の接続先が設定されていません") from None
    try:
        res = await client.get(
            f"{endpoint}/search",
            params={"q": query, "format": "json", "language": "ja"},
            timeout=SEARCH_TIMEOUT_S,
        )
        res.raise_for_status()
        data: Any = res.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SearchUnavailableError(type(e).__name__) from None

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise SearchUnavailableError("検索の応答の形が違います")
    found: list[SearchResult] = []
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        found.append(
            SearchResult(
                url=item["url"],
                title=str(item.get("title") or ""),
                snippet=str(item.get("content") or ""),
            )
        )
        if len(found) == MAX_RESULTS:
            break
    return found
