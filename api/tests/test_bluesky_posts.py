import asyncio
from typing import Any, cast

import pytest
from atproto import AsyncClient, models
from atproto_client.exceptions import NetworkError

from tkb_api import bluesky
from tkb_api.bluesky import fetch_own_posts, to_post

ME = "did:plc:me00000000000000000000"
OTHER = "did:plc:other000000000000000000"
CDN = "https://cdn.bsky.app/img/feed_fullsize/plain"


def _image(name: str, ratio: tuple[int, int] | None = (1200, 900)) -> Any:
    return models.AppBskyEmbedImages.ViewImage(
        alt=f"{name} の写真",
        fullsize=f"{CDN}/{name}@jpeg",
        thumb=f"https://cdn.bsky.app/img/feed_thumbnail/plain/{name}@jpeg",
        aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(width=ratio[0], height=ratio[1])
        if ratio
        else None,
    )


def _item(
    rkey: str,
    *,
    author: str = ME,
    text: str = "夜勤明けのラーメン",
    embed: Any = None,
    repost_by: str | None = None,
) -> models.AppBskyFeedDefs.FeedViewPost:
    post = models.AppBskyFeedDefs.PostView(
        uri=f"at://{author}/app.bsky.feed.post/{rkey}",
        cid="bafyreidemo",
        author=models.AppBskyActorDefs.ProfileViewBasic(did=author, handle="someone.bsky.social"),
        record=models.AppBskyFeedPost.Record(text=text, created_at="2026-10-20T08:31:00+09:00"),
        indexed_at="2026-10-20T08:31:01+09:00",
        embed=embed,
    )
    reason = (
        models.AppBskyFeedDefs.ReasonRepost(
            by=models.AppBskyActorDefs.ProfileViewBasic(did=repost_by, handle="me.bsky.social"),
            indexed_at="2026-10-21T00:00:00+09:00",
        )
        if repost_by
        else None
    )
    return models.AppBskyFeedDefs.FeedViewPost(post=post, reason=reason)


def test_to_post_converts_own_post_with_images() -> None:
    embed = models.AppBskyEmbedImages.View(images=[_image("a"), _image("b", (900, 1600))])

    post = to_post(_item("3kaaa", embed=embed), ME)

    assert post is not None
    assert post.post_id == f"at://{ME}/app.bsky.feed.post/3kaaa"
    assert post.text == "夜勤明けのラーメン"
    assert post.created_at.isoformat() == "2026-10-20T08:31:00+09:00"
    assert [(i.index, i.url, i.alt, i.width, i.height) for i in post.images] == [
        (0, f"{CDN}/a@jpeg", "a の写真", 1200, 900),
        (1, f"{CDN}/b@jpeg", "b の写真", 900, 1600),
    ]


def test_to_post_reads_images_next_to_a_quote() -> None:
    embed = models.AppBskyEmbedRecordWithMedia.View(
        media=models.AppBskyEmbedImages.View(images=[_image("a")]),
        record=models.AppBskyEmbedRecord.View(
            record=models.AppBskyEmbedRecord.ViewNotFound(
                uri=f"at://{OTHER}/app.bsky.feed.post/3kzzz", not_found=True
            )
        ),
    )

    post = to_post(_item("3kaaa", embed=embed), ME)

    assert post is not None
    assert [i.url for i in post.images] == [f"{CDN}/a@jpeg"]


def test_to_post_skips_reposts_and_other_peoples_posts() -> None:
    assert to_post(_item("3kaaa", author=OTHER, repost_by=ME), ME) is None
    assert to_post(_item("3kaaa", author=OTHER), ME) is None


def test_to_post_drops_images_without_size_and_renumbers_the_rest() -> None:
    embed = models.AppBskyEmbedImages.View(images=[_image("a", None), _image("b")])

    post = to_post(_item("3kaaa", embed=embed), ME)

    assert post is not None
    assert [(i.index, i.url) for i in post.images] == [(0, f"{CDN}/b@jpeg")]


class _FakeClient:
    """get_author_feed だけを持つ偽物。呼ばれた引数を覚えておく。"""

    def __init__(self, pages: list[tuple[list[Any], str | None]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, Any]] = []

    async def get_author_feed(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        feed, cursor = self._pages[len(self.calls) - 1]
        return models.AppBskyFeedGetAuthorFeed.Response(feed=feed, cursor=cursor)


def _fetch(client: _FakeClient, limit: int) -> list[Any]:
    return asyncio.run(fetch_own_posts(cast(AsyncClient, client), ME, limit))


def test_fetch_own_posts_asks_only_for_the_session_did_and_follows_the_cursor() -> None:
    client = _FakeClient(
        [
            ([_item("3k001"), _item("3k002", author=OTHER, repost_by=ME)], "next"),
            ([_item("3k003"), _item("3k004")], None),
        ]
    )

    posts = _fetch(client, limit=3)

    assert [p.post_id.rsplit("/", 1)[1] for p in posts] == ["3k001", "3k003", "3k004"]
    assert [c["actor"] for c in client.calls] == [ME, ME]
    assert [c["cursor"] for c in client.calls] == [None, "next"]


def test_fetch_own_posts_stops_at_the_limit() -> None:
    client = _FakeClient([([_item("3k001"), _item("3k002"), _item("3k003")], "next")])

    posts = _fetch(client, limit=2)

    assert len(posts) == 2
    assert len(client.calls) == 1


def test_fetch_own_posts_turns_network_errors_into_unavailable() -> None:
    class _Broken:
        async def get_author_feed(self, **_: Any) -> Any:
            raise NetworkError

    with pytest.raises(bluesky.BlueskyUnavailableError):
        asyncio.run(fetch_own_posts(cast(AsyncClient, _Broken()), ME, 30))
