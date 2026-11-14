"""住まいの推定（点数の地図）を API の形で返す（tkb_api.pipeline.residence_json）。

表は engine の小さな架空の地図（tkb_engine.scoring.sample）を使う。
"""

from tkb_api.pipeline import residence_json, simulate_claims_json
from tkb_common.residence import ResidenceEstimate
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine.gazetteer import CollectionArea, Gazetteer, Knowledge
from tkb_engine.scoring.sample import build_tables


def post(n: int, text: str, images: int = 0) -> Post:
    return Post.model_validate(
        {
            "post_id": f"at://did:plc:x/app.bsky.feed.post/{n}",
            "text": text,
            "created_at": f"2026-11-{n:02d}T21:00:00+09:00",
            "images": [
                {
                    "index": 0,
                    "url": f"https://cdn.bsky.app/img/feed_fullsize/plain/x/{n}",
                    "alt": "",
                    "width": 10,
                    "height": 10,
                }
            ]
            * images,
        }
    )


def photo(n: int, source: ClueSource) -> Clue:
    return Clue(
        post_id=f"at://did:plc:x/app.bsky.feed.post/{n}",
        image_index=0,
        type=ClueType.ADDRESS_TEXT,
        value="弥生",
        region=None,
        confidence=0.9,
        source=source,
    )


GAZETTEER = Gazetteer(
    knowledge=Knowledge(
        collection_areas=[CollectionArea("文京区", "弥生1・2丁目", "月木", ["弥生1・2丁目"])]
    ),
    scoring=build_tables(),
)
POSTS = [
    post(1, "千代田線、また止まってる…"),
    post(2, "今日は一日なにもしなかった"),
    post(3, "近所の猫、今日もいた", images=1),
    post(4, "22歳、いまだに自炊がうまくならない"),
    post(5, "誕生日が4月14日だと、毎年誰にも祝われない"),
]
# 写真の手がかりの前に、ほかの投稿の手がかりを1つ置く（番号の振り直しを確かめる）
CLUES = [
    Clue(
        post_id=POSTS[1].post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value="一日なにもしなかった",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    ),
    photo(3, ClueSource.OCR),
    photo(3, ClueSource.VLM),
]


def test_residence_is_null_without_the_tables() -> None:
    assert residence_json(CLUES, POSTS, Gazetteer()) is None
    assert residence_json([], [POSTS[1]], GAZETTEER) is None


def test_residence_returns_the_map_steps_influence_and_evidence() -> None:
    body = residence_json(CLUES, POSTS, GAZETTEER)

    assert body is not None
    estimate = ResidenceEstimate.model_validate(body)
    assert estimate.age_class == "20〜24歳"
    assert estimate.region.same_birthday is not None
    assert estimate.region.city in {"文京区", "中野区"}
    assert estimate.steps[0].post_id is None
    assert [s.post_id for s in estimate.steps[1:]] == [
        POSTS[0].post_id,
        POSTS[2].post_id,
        POSTS[3].post_id,
        POSTS[4].post_id,
    ]
    deltas = [i.delta for i in estimate.influence]
    assert deltas == sorted(deltas, reverse=True)
    town = next(e for e in estimate.evidence if e.layer == 5)
    assert town.post_id == POSTS[2].post_id
    assert town.clue_indices == [1, 2]  # 診断の clues での番号
    assert len(estimate.map.cells) == 100
    assert sum(c.in_region for c in estimate.map.cells) == estimate.region.cells
    assert {label.kind for label in estimate.map.labels} == {"station", "town"}
    assert estimate.assumptions and any("OpenStreetMap" in s for s in estimate.sources)


def test_residence_leaves_out_excluded_posts_and_keeps_clue_numbers() -> None:
    body = residence_json(CLUES, POSTS, GAZETTEER, [POSTS[1].post_id])

    assert body is not None
    town = next(e for e in body["evidence"] if e["layer"] == 5)
    assert town["clue_indices"] == [1, 2]
    without_photo = residence_json(CLUES, POSTS, GAZETTEER, [POSTS[2].post_id])
    assert without_photo is not None
    assert all(e["layer"] != 5 for e in without_photo["evidence"])
    assert without_photo["region"]["people"] >= body["region"]["people"]


def test_simulate_recomputes_the_residence_without_the_chosen_posts() -> None:
    simulated = simulate_claims_json([], CLUES, POSTS, [POSTS[2].post_id], gazetteer=GAZETTEER)

    assert {"delete", "broken", "after", "narrowing", "residence"} <= set(simulated)
    assert all(e["post_id"] != POSTS[2].post_id for e in simulated["residence"]["evidence"])
    without_tables = simulate_claims_json(
        [], CLUES, POSTS, [POSTS[2].post_id], gazetteer=Gazetteer()
    )
    assert without_tables["residence"] is None
    assert "residence" not in simulate_claims_json([], CLUES, POSTS, [POSTS[2].post_id])
