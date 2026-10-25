"""eval/fixtures/demo_observations.json が手がかりの形式に合っているか。

役割C（推理ルール）と役割A（画面のモック）が使うので、形が崩れていたら落とす。
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tkb_common.schemas import Clue, Post

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_every_clue_matches_the_clue_format(doc: dict[str, Any]) -> None:
    clues = [Clue.model_validate(c) for c in doc["clues"]]

    assert len(clues) > 0


def test_every_post_matches_the_post_format(doc: dict[str, Any]) -> None:
    posts = [Post.model_validate(p) for p in doc["posts"]]

    assert len(posts) == 10


def test_clues_point_to_existing_posts_images_and_regions(doc: dict[str, Any]) -> None:
    posts = {p["post_id"]: p for p in doc["posts"]}
    assert len(posts) == 10

    for raw in doc["clues"]:
        clue = Clue.model_validate(raw)
        post = posts[clue.post_id]
        if clue.image_index is None:
            continue
        image = post["images"][clue.image_index]
        if clue.region is not None:
            _, _, x2, y2 = clue.region
            assert x2 <= image["width"]
            assert y2 <= image["height"]


def test_expected_inferences_refer_to_existing_clues(doc: dict[str, Any]) -> None:
    attributes = {e["attribute"] for e in doc["expected"]}

    assert attributes == {"station", "occupation", "given_name_or_nickname", "age", "routine"}
    for e in doc["expected"]:
        assert all(0 <= i < len(doc["clues"]) for i in e["clue_indices"])


def test_images_are_only_on_the_bluesky_cdn(doc: dict[str, Any]) -> None:
    for post in doc["posts"]:
        for image in post["images"]:
            assert image["url"].startswith("https://cdn.bsky.app/")
