from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from tkb_common.schemas import Post

IMAGE: dict[str, Any] = {
    "index": 0,
    "url": "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx/abc@jpeg",
    "alt": "",
    "width": 1200,
    "height": 900,
}

POST: dict[str, Any] = {
    "post_id": "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
    "text": "夜勤明けのラーメン",
    "created_at": "2026-10-20T08:31:00+09:00",
    "images": [IMAGE],
}


def test_parses_post_in_documented_format() -> None:
    post = Post.model_validate(POST)

    assert post.created_at.utcoffset() == timedelta(hours=9)
    assert post.images[0].width == 1200


def test_serializes_back_to_documented_json_shape() -> None:
    assert Post.model_validate(POST).model_dump(mode="json") == POST


def test_accepts_post_without_images() -> None:
    assert Post.model_validate({**POST, "images": []}).images == []


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("CDN 以外の画像", {**POST, "images": [{**IMAGE, "url": "https://example.com/a.jpg"}]}),
        ("http の CDN", {**POST, "images": [{**IMAGE, "url": "http://cdn.bsky.app/img/a"}]}),
        (
            "CDN に見せかけたホスト",
            {**POST, "images": [{**IMAGE, "url": "https://cdn.bsky.app.evil.test/a"}]},
        ),
        ("index が順でない", {**POST, "images": [{**IMAGE, "index": 1}]}),
        ("写真が5枚", {**POST, "images": [{**IMAGE, "index": i} for i in range(5)]}),
        ("幅が0", {**POST, "images": [{**IMAGE, "width": 0}]}),
        ("時差のない日時", {**POST, "created_at": "2026-10-20T08:31:00"}),
        ("post_id が空", {**POST, "post_id": ""}),
    ],
)
def test_rejects_invalid_post(label: str, data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Post.model_validate(data)
