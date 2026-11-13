"""X の表示要件に使う情報の取り出し。"""

from tkb_api.x_display import (
    author_from_profile,
    post_display,
    synthetic_author,
    synthetic_display,
)

PROFILE = {
    "id": "1000000000000000001",
    "name": "架空のテスター",
    "username": "fictional_xtest",
    "profile_image_url": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
}
AUTHOR = author_from_profile(PROFILE)


def test_author_links_to_the_x_profile_and_keeps_only_x_avatars() -> None:
    assert AUTHOR.profile_url == "https://x.com/fictional_xtest"
    assert AUTHOR.name == "架空のテスター"
    assert AUTHOR.profile_image_url == PROFILE["profile_image_url"]
    other = author_from_profile({**PROFILE, "profile_image_url": "https://evil.example/a.jpg"})
    assert other.profile_image_url is None
    plain = author_from_profile({**PROFILE, "profile_image_url": "http://pbs.twimg.com/a.jpg"})
    assert plain.profile_image_url is None
    unnamed = author_from_profile({"id": "1", "username": "abc"})
    assert unnamed.name == "abc"


def test_post_display_links_entities_in_code_points_and_marks_edits() -> None:
    text = "🍜 @friend_1 と #新宿 https://t.co/abc"
    item = {
        "id": "1900000000000000099",
        "text": text,
        "edit_history_tweet_ids": ["1900000000000000098", "1900000000000000099"],
        "entities": {
            "mentions": [{"start": 2, "end": 11, "username": "friend_1"}],
            "hashtags": [{"start": 14, "end": 17, "tag": "新宿"}],
            "urls": [
                {
                    "start": 18,
                    "end": 41,
                    "url": "https://t.co/abc",
                    "display_url": "example.com/page",
                    "expanded_url": "https://example.com/page",
                }
            ],
        },
    }
    item["entities"]["urls"][0]["end"] = len(text)  # type: ignore[index]

    display = post_display(item, AUTHOR)

    assert display.permalink == "https://x.com/fictional_xtest/status/1900000000000000099"
    assert display.edited is True
    assert [(e.kind, e.href, e.display) for e in display.entities] == [
        ("mention", "https://x.com/friend_1", None),
        ("hashtag", "https://x.com/search?q=%23新宿", None),
        ("url", "https://t.co/abc", "example.com/page"),
    ]
    # コードポイント単位（絵文字は1文字）
    assert text[display.entities[0].start : display.entities[0].end] == "@friend_1"
    assert text[display.entities[1].start : display.entities[1].end] == "#新宿"


def test_post_display_drops_broken_or_overlapping_entities() -> None:
    item = {
        "id": "5",
        "text": "@a_b #tag",
        "edit_history_tweet_ids": ["5"],
        "entities": {
            "mentions": [
                {"start": 0, "end": 4, "username": "a_b"},
                {"start": 2, "end": 6, "username": "zz"},  # 重なる
                {"start": 0, "end": 99, "username": "c"},  # 本文の外
                {"start": 0, "end": 4, "username": "bad name"},
            ],
            "hashtags": [{"start": 5, "end": 9, "tag": "tag"}],
            "urls": [{"start": 0, "end": 3, "url": "javascript:alert(1)", "display_url": "x"}],
        },
    }
    display = post_display(item, AUTHOR)
    assert display.edited is False
    assert [(e.kind, e.start, e.end) for e in display.entities] == [
        ("mention", 0, 4),
        ("hashtag", 5, 9),
    ]


def test_synthetic_posts_have_no_links() -> None:
    author = synthetic_author("架空のXアカウント")
    assert author.profile_url is None and author.profile_image_url is None
    display = synthetic_display()
    assert display.permalink is None and display.entities == []
    assert post_display({"id": "1", "text": "a"}, author).permalink is None
