"""Search public pages for external profiles without fetching arbitrary result URLs."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import SecretStr, ValidationError

from tkb_common.schemas import (
    ExternalLookupStatus,
    ExternalOwnerEvidence,
    ExternalOwnerEvidenceKind,
    ExternalProfileResult,
    ExternalProfileStatus,
    Post,
)

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5
MAX_PROVIDER_RESULTS = 10
MAX_RESPONSE_BYTES = 256_000
REQUEST_TIMEOUT_SECONDS = 5.0
_HANDLE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https://[^\s<>\"'「」『』（）]+", re.IGNORECASE)
_SELF_LINK_PATTERN = re.compile(
    r"(?:私の|僕の|わたしの|自分の|my\s+)(?:ブログ|ぶろぐ|記事|アカウント|SNS|サイト|ポートフォリオ|blog|article|account|profile|site|portfolio)"
    r"(?:は|はこちら|です|:|：)?[^\n]{0,120}$",
    re.IGNORECASE,
)
_AMBIGUOUS_SELF_LINK_CONTEXT = re.compile(
    r"(?:友人|知人|家族|同僚|他人|彼|彼女|さんの|氏の|ではない|じゃない|ではなく|じゃなく|not\s+my)",
    re.IGNORECASE,
)
_QUOTE_MARKS = "「」『』\"'`“”‘’"
_TRAILING_PUNCTUATION = ".,;:!?。、，；：！？)]}」』〉》"


@dataclass(frozen=True)
class ExternalLookupResult:
    status: ExternalLookupStatus
    results: tuple[ExternalProfileResult, ...] = ()


def _validated_handle(handle: str) -> str | None:
    normalized = handle.strip().lstrip("@").lower()
    if len(normalized) > 253 or not _HANDLE_PATTERN.fullmatch(normalized):
        return None
    labels = normalized.split(".")
    if len(labels) < 2 or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in labels
    ):
        return None
    return normalized


def _public_https_url(value: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme.lower() != "https" or not host or parts.username or parts.password:
            return None
        if parts.port not in {None, 443}:
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        labels = host.split(".")
        if (
            host in {"localhost", "localhost.localdomain"}
            or host.endswith(
                (
                    ".localhost",
                    ".local",
                    ".localdomain",
                    ".internal",
                    ".test",
                    ".invalid",
                    ".home",
                    ".lan",
                    ".home.arpa",
                )
            )
            or len(labels) < 2
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            return None
        canonical = urlunsplit(("https", host, parts.path.rstrip("/") or "/", parts.query, ""))
        return canonical, host
    except ValueError:
        return None


def _candidate_from_result(item: object) -> ExternalProfileResult | None:
    if not isinstance(item, dict):
        return None
    raw_url, raw_title = item.get("url"), item.get("title")
    if not isinstance(raw_url, str) or not isinstance(raw_title, str) or not raw_title.strip():
        return None
    parsed = _public_https_url(raw_url)
    if parsed is None:
        return None
    url, domain = parsed
    identifier = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    try:
        return ExternalProfileResult(
            id=identifier,
            url=url,
            domain=domain,
            title=raw_title.strip()[:300],
            status=ExternalProfileStatus.CANDIDATE,
            owner_evidence=None,
        )
    except ValidationError:
        return None


async def search_external_profiles(handle: str, api_key: SecretStr) -> ExternalLookupResult:
    """Call Brave with only the authenticated owner's public handle; never fetch result URLs."""
    query = _validated_handle(handle)
    key = api_key.get_secret_value().strip()
    if query is None or not key:
        return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)

    try:
        async with (
            httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(
                "GET",
                BRAVE_SEARCH_ENDPOINT,
                params={
                    "q": f'"{query}" NOT site:bsky.app NOT site:bsky.social',
                    "count": MAX_PROVIDER_RESULTS,
                    "offset": 0,
                    "spellcheck": "false",
                    "result_filter": "web",
                },
                headers={"x-subscription-token": key, "accept": "application/json"},
            ) as response,
        ):
            if response.status_code != 200:
                return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
            if (
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)

    web = payload.get("web") if isinstance(payload, dict) else None
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        return ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
    results: list[ExternalProfileResult] = []
    seen: set[str] = set()
    for item in items[:MAX_PROVIDER_RESULTS]:
        candidate = _candidate_from_result(item)
        if candidate is None or candidate.url in seen or _is_bluesky_domain(candidate.domain):
            continue
        seen.add(str(candidate.url))
        results.append(candidate)
        if len(results) == MAX_RESULTS:
            break
    status = ExternalLookupStatus.SEARCHED if results else ExternalLookupStatus.NO_RESULTS
    return ExternalLookupResult(status, tuple(results))


def _is_bluesky_domain(domain: str) -> bool:
    normalized = domain.casefold().rstrip(".")
    return normalized in {"bsky.app", "bsky.social"} or normalized.endswith(".bsky.social")


def _owner_links(posts: Sequence[Post], profile_text: str) -> dict[str, ExternalOwnerEvidence]:
    links: dict[str, ExternalOwnerEvidence] = {}
    profile_matches = list(_URL_PATTERN.finditer(profile_text))
    if len(profile_matches) == 1:
        match = profile_matches[0]
        raw_url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        parsed = _public_https_url(raw_url)
        if parsed is not None:
            links.setdefault(
                parsed[0],
                ExternalOwnerEvidence(
                    kind=ExternalOwnerEvidenceKind.PROFILE_TEXT,
                    post_id=None,
                    excerpt=profile_text[max(0, match.start() - 100) : match.end()][:500],
                ),
            )
    for post in posts:
        matches = list(_URL_PATTERN.finditer(post.text))
        # A post with multiple links is ambiguous for this limited ownership rule.
        if len(matches) != 1:
            continue
        for match in matches:
            before_url = post.text[max(0, match.start() - 160) : match.start()]
            sentence = re.split(r"[。！？\n]", before_url)[-1]
            if (
                any(mark in sentence for mark in _QUOTE_MARKS)
                or _AMBIGUOUS_SELF_LINK_CONTEXT.search(sentence)
                or not _SELF_LINK_PATTERN.search(sentence)
            ):
                continue
            raw_url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
            parsed = _public_https_url(raw_url)
            if parsed is not None:
                links.setdefault(
                    parsed[0],
                    ExternalOwnerEvidence(
                        kind=ExternalOwnerEvidenceKind.POST_TEXT,
                        post_id=post.post_id,
                        excerpt=post.text[max(0, match.start() - 100) : match.end()][:500],
                    ),
                )
    return links


def mark_owner_linked(
    posts: Sequence[Post],
    profile_text: str,
    results: Sequence[ExternalProfileResult],
) -> tuple[ExternalProfileResult, ...]:
    owner_links = _owner_links(posts, profile_text)
    marked: list[ExternalProfileResult] = []
    for result in results:
        parsed = _public_https_url(str(result.url))
        evidence = owner_links.get(parsed[0]) if parsed is not None else None
        if evidence is None:
            marked.append(result)
        else:
            marked.append(
                result.model_copy(
                    update={
                        "status": ExternalProfileStatus.OWNER_LINKED,
                        "owner_evidence": evidence,
                    }
                )
            )
    return tuple(marked)
