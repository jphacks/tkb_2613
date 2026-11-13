from datetime import datetime

from tkb_api.x_public_info import extract_public_information
from tkb_common.schemas import Post


def _post(post_id: str, text: str) -> Post:
    return Post(
        post_id=f"x:{post_id}",
        text=text,
        created_at=datetime.fromisoformat("2026-11-12T12:00:00+09:00"),
        images=[],
    )


def test_extracts_only_literal_limited_categories_and_groups_posts() -> None:
    items = extract_public_information(
        [
            _post("1", "渋谷駅、火曜10時、青空大学へ"),
            _post("2", "渋谷駅 火曜日10時、東京都渋谷区"),
        ]
    )
    by_key = {(item.category, item.value): item for item in items}

    assert by_key[("station", "渋谷駅")].count == 2
    assert by_key[("weekday", "火曜日")].count == 2
    assert by_key[("time", "10時")].count == 2
    assert by_key[("school", "青空大学")].count == 1
    assert by_key[("place", "東京都渋谷区")].count == 1
    assert all(
        evidence.quote
        in next(
            post.text
            for post in [
                _post("1", "渋谷駅、火曜10時、青空大学へ"),
                _post("2", "渋谷駅 火曜日10時、東京都渋谷区"),
            ]
            if post.post_id == evidence.post_id
        )
        for item in items
        for evidence in item.evidence
    )


def test_does_not_infer_private_or_sensitive_attributes() -> None:
    items = extract_public_information(
        [_post("1", "会社帰り。体調のことや支持政党、住んでいる場所は書いていない")]
    )
    assert items == []


def test_counts_a_value_once_per_post() -> None:
    items = extract_public_information([_post("1", "金曜、金曜、19時から19時")])
    by_key = {(item.category, item.value): item for item in items}
    assert by_key[("weekday", "金曜日")].count == 1
    assert by_key[("time", "19時")].count == 1
