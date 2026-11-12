from datetime import timedelta

import httpx
import pytest
import respx

from tkb_api.x_poc import X_API, XPocError, fetch_own_posts, to_post

POST_FIELDS = "author_id,created_at,entities,edit_history_tweet_ids"


def test_to_post_keeps_text_and_time_without_images() -> None:
    post = to_post(
        {
            "id": "123",
            "author_id": "42",
            "text": "毎週火曜はジム",
            "created_at": "2026-11-10T08:31:00+09:00",
        },
        "42",
    )
    assert post is not None
    assert post.post_id == "x:123"
    assert post.text == "毎週火曜はジム"
    assert post.created_at.utcoffset() == timedelta(hours=9)
    assert post.images == []


def test_to_post_rejects_other_author_and_naive_time() -> None:
    item = {"id": "123", "author_id": "7", "text": "本文", "created_at": "2026-11-10T00:00:00Z"}
    with pytest.raises(XPocError, match="本人以外"):
        to_post(item, "42")
    item["author_id"] = "42"
    item["created_at"] = "2026-11-10T00:00:00"
    with pytest.raises(XPocError, match="日時"):
        to_post(item, "42")


@pytest.mark.anyio
async def test_fetches_only_me_with_fixed_host_and_pagination() -> None:
    with respx.mock(assert_all_called=True) as router:
        me = router.get(f"{X_API}/2/users/me").respond(json={"data": {"id": "42"}})
        pages = router.get(f"{X_API}/2/users/42/tweets").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "1",
                                "author_id": "42",
                                "text": "駅に着いた",
                                "created_at": "2026-11-10T00:00:00Z",
                            },
                            {
                                "id": "2",
                                "author_id": "42",
                                "text": "  ",
                                "created_at": "2026-11-09T00:00:00Z",
                            },
                        ],
                        "meta": {"next_token": "safe-cursor"},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "1",
                                "author_id": "42",
                                "text": "重複",
                                "created_at": "2026-11-10T00:00:00Z",
                            },
                            {
                                "id": "3",
                                "author_id": "42",
                                "text": "毎週通う",
                                "created_at": "2026-11-08T00:00:00Z",
                            },
                        ]
                    },
                ),
            ]
        )
        owner_id, posts = await fetch_own_posts("dummy-token", limit=7)
    assert owner_id == "42"
    assert [post.post_id for post in posts] == ["x:1", "x:3"]
    assert me.calls[0].request.headers["authorization"] == "Bearer dummy-token"
    assert pages.calls[0].request.url.params["max_results"] == "7"
    assert (
        pages.calls[0].request.url.params["post.fields"]
        == "author_id,created_at,entities,edit_history_tweet_ids"
    )
    cursor = "safe-cursor"
    assert pages.calls[1].request.url.params["pagination_token"] == cursor


@pytest.mark.anyio
async def test_http_failure_hides_token_and_response_body() -> None:
    with respx.mock as router:
        router.get(f"{X_API}/2/users/me").respond(401, json={"error": "secret-dummy-token"})
        with pytest.raises(XPocError) as exc:
            await fetch_own_posts("secret-dummy-token")
    assert "secret-dummy-token" not in str(exc.value)
    assert "401" in str(exc.value)
