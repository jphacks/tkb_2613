import asyncio

import httpx
import respx
from pydantic import SecretStr

from tkb_api.public_web_identity import (
    BRAVE_SEARCH_ENDPOINT,
    ExternalLookupResult,
    mark_owner_linked,
    search_external_profiles,
)
from tkb_common.schemas import (
    ExternalLookupStatus,
    ExternalOwnerEvidenceKind,
    ExternalProfileResult,
    ExternalProfileStatus,
    Post,
)


def _result(url: str, *, identifier: str = "candidate") -> ExternalProfileResult:
    from urllib.parse import urlsplit

    return ExternalProfileResult(
        id=identifier,
        url=url,
        domain=urlsplit(url).hostname or "",
        title="架空のページ",
        status=ExternalProfileStatus.CANDIDATE,
        owner_evidence=None,
    )


def _post(text: str, post_id: str = "at://did:plc:owner/app.bsky.feed.post/1") -> Post:
    return Post.model_validate(
        {
            "post_id": post_id,
            "text": text,
            "created_at": "2026-11-10T08:00:00+09:00",
            "images": [],
        }
    )


@respx.mock
def test_brave_search_sends_only_validated_public_handle_and_fixed_options() -> None:
    route = respx.get(BRAVE_SEARCH_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://example.net/blog/",
                            "title": "架空ブログ",
                            "description": "本文は採用しない",
                        }
                    ]
                },
            },
        )
    )

    result = asyncio.run(search_external_profiles("alice.bsky.social", SecretStr("test-token")))

    assert result.status is ExternalLookupStatus.SEARCHED
    assert len(result.results) == 1
    assert result.results[0].domain == "example.net"
    assert result.results[0].status is ExternalProfileStatus.CANDIDATE
    assert str(result.results[0].url) == "https://example.net/blog"
    assert route.called
    request = route.calls[0].request
    assert request.url.params["q"] == '"alice.bsky.social" NOT site:bsky.app NOT site:bsky.social'
    assert set(request.url.params) == {"q", "count", "offset", "spellcheck", "result_filter"}
    assert request.url.params["count"] == "10"
    assert request.url.params["offset"] == "0"
    assert request.url.params["spellcheck"] == "false"
    assert request.url.params["result_filter"] == "web"
    assert request.headers["x-subscription-token"] == "test-token"


@respx.mock
def test_search_excludes_bluesky_results_and_returns_at_most_five_other_domains() -> None:
    respx.get(BRAVE_SEARCH_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"url": "https://bsky.app/profile/alice", "title": "Bluesky profile"},
                        *[
                            {"url": f"https://site{index}.org/alice", "title": f"Site {index}"}
                            for index in range(7)
                        ],
                    ]
                },
            },
        )
    )

    result = asyncio.run(search_external_profiles("alice.bsky.social", SecretStr("test-token")))

    assert result.status is ExternalLookupStatus.SEARCHED
    assert len(result.results) == 5
    assert all(item.domain != "bsky.app" for item in result.results)


@respx.mock
def test_invalid_handle_is_not_sent_to_provider() -> None:
    for handle in ("https://alice.example/profile", "alice"):
        result = asyncio.run(search_external_profiles(handle, SecretStr("test-token")))
        assert result == ExternalLookupResult(ExternalLookupStatus.UNAVAILABLE)
    assert respx.calls.call_count == 0


@respx.mock
def test_provider_failure_is_generic() -> None:
    route = respx.get(BRAVE_SEARCH_ENDPOINT).mock(
        return_value=httpx.Response(503, text="private response")
    )
    result = asyncio.run(search_external_profiles("alice.bsky.social", SecretStr("test-token")))
    assert result.status is ExternalLookupStatus.UNAVAILABLE
    assert route.called


@respx.mock
def test_oversized_provider_payload_is_rejected() -> None:
    respx.get(BRAVE_SEARCH_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            content=b"x" * 256_001,
            headers={"content-type": "application/json"},
        )
    )
    result = asyncio.run(search_external_profiles("alice.bsky.social", SecretStr("test-token")))
    assert result.status is ExternalLookupStatus.UNAVAILABLE


def test_only_unambiguous_owner_published_urls_are_owner_linked() -> None:
    linked_url = "https://example.net/my-blog"
    candidates = [
        _result(linked_url, identifier="linked"),
        _result("https://sample.org/notes", identifier="candidate"),
    ]
    marked = mark_owner_linked([], f"ブログ: {linked_url}", candidates)
    assert marked[0].status is ExternalProfileStatus.OWNER_LINKED
    assert marked[0].owner_evidence is not None
    assert marked[0].owner_evidence.kind is ExternalOwnerEvidenceKind.PROFILE_TEXT
    assert marked[1].status is ExternalProfileStatus.CANDIDATE
    assert marked[1].owner_evidence is None

    quoted = mark_owner_linked(
        [_post(f"『私のブログはこちら』 {linked_url}")],
        "",
        candidates[:1],
    )
    assert quoted[0].status is ExternalProfileStatus.CANDIDATE

    multiple_urls = mark_owner_linked(
        [_post(f"私のブログはこちら {linked_url} https://other.example.org/")],
        "",
        candidates[:1],
    )
    assert multiple_urls[0].status is ExternalProfileStatus.CANDIDATE


def test_explicit_owner_post_link_is_linked_but_ambiguous_context_is_not() -> None:
    url = "https://example.net/my-blog"
    result = _result(url)
    linked = mark_owner_linked([_post(f"私のブログはこちら: {url}")], "", [result])[0]
    assert linked.status is ExternalProfileStatus.OWNER_LINKED
    assert linked.owner_evidence is not None
    assert linked.owner_evidence.kind is ExternalOwnerEvidenceKind.POST_TEXT
    assert linked.owner_evidence.post_id == "at://did:plc:owner/app.bsky.feed.post/1"

    quoted = mark_owner_linked([_post(f"友人の『私のブログはこちら』 {url}")], "", [result])[0]
    assert quoted.status is ExternalProfileStatus.CANDIDATE


def test_result_schema_rejects_local_single_label_and_ip_hosts() -> None:
    for url in (
        "https://localhost/profile",
        "https://internal/profile",
        "https://service.localhost/profile",
        "https://service.internal/profile",
        "https://127.0.0.1/profile",
    ):
        try:
            _result(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"local result URL should be rejected: {url}")
