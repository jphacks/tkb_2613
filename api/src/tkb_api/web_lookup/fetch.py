"""照合で選んだページと、その og:image を安全に取ってくる。

- http(s) だけ。名前解決した IP がプライベート・ループバック・リンクローカルなどなら拒否する
- リダイレクトは自分でたどり、行き先ごとに確かめ直す（MAX_REDIRECTS 回まで）
- 大きさと時間に上限を置く。ページは <title> と og:* だけを読む
- 画像は SVG を受け取らない（スクリプトを含められるため）
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 3
MAX_PAGE_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_S = 15.0
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")

Resolver = Callable[[str], Awaitable[list[str]]]


class UnsafeUrlError(Exception):
    """取りに行ってはいけない URL。URL は文言に入れない。"""


class FetchError(Exception):
    """取ってこられなかった。URL は文言に入れない。"""


@dataclass(frozen=True)
class PageSummary:
    url: str
    title: str
    description: str
    image: str | None


async def resolve_host(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def ensure_public(url: str, resolve: Resolver = resolve_host) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError("http(s) の URL ではありません")
    try:
        addresses = await resolve(parsed.hostname)
    except OSError:
        raise UnsafeUrlError("名前解決できません") from None
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise UnsafeUrlError("公開されていない宛先です")


async def fetch_page(
    client: httpx.AsyncClient, url: str, resolve: Resolver = resolve_host
) -> PageSummary:
    final_url, body, _ = await _get(client, url, MAX_PAGE_BYTES, resolve)
    head = _HeadParser()
    head.feed(body.decode("utf-8", errors="replace"))
    image = head.meta.get("og:image")
    return PageSummary(
        url=final_url,
        title=head.meta.get("og:title") or head.title.strip(),
        description=head.meta.get("og:description") or head.meta.get("description", ""),
        image=urljoin(final_url, image) if image else None,
    )


async def fetch_image(
    client: httpx.AsyncClient, url: str, resolve: Resolver = resolve_host
) -> tuple[bytes, str]:
    _, body, content_type = await _get(client, url, MAX_IMAGE_BYTES, resolve)
    if content_type not in IMAGE_TYPES:
        raise FetchError("画像ではありません")
    return body, content_type


async def _get(
    client: httpx.AsyncClient, url: str, limit: int, resolve: Resolver
) -> tuple[str, bytes, str]:
    """(たどり着いた URL, 本文, Content-Type) を返す。"""
    for _ in range(MAX_REDIRECTS + 1):
        await ensure_public(url, resolve)
        try:
            async with client.stream(
                "GET", url, follow_redirects=False, timeout=FETCH_TIMEOUT_S
            ) as res:
                if res.is_redirect and "location" in res.headers:
                    url = urljoin(url, res.headers["location"])
                    continue
                res.raise_for_status()
                content_type = res.headers.get("content-type", "").split(";")[0].strip().lower()
                chunks, size = [], 0
                async for chunk in res.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise FetchError("大きすぎます")
                    chunks.append(chunk)
                return url, b"".join(chunks), content_type
        except httpx.HTTPError as e:
            raise FetchError(type(e).__name__) from None
    raise FetchError("リダイレクトが多すぎます")


class _HeadParser(HTMLParser):
    """<title> と <meta>（og:* と description）だけを集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:description", "og:image", "description") and a.get(
                "content"
            ):
                self.meta.setdefault(key, (a["content"] or "").strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
