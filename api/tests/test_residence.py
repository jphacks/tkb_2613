"""住まいの推定（点数の地図）を API の形で返す（tkb_api.pipeline.residence_json）。

表は engine の小さな架空の地図（tkb_engine.scoring.sample）を使う。
"""

from dataclasses import replace

from tkb_api.pipeline import residence_json, simulate_claims_json
from tkb_common.residence import ResidenceEstimate
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    EvidenceSource,
    Post,
    ProfileAttribute,
    ProfileCandidate,
    ProfileCandidateSet,
    ProfileCandidateSetStatus,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileStatus,
)
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


def station_claim(required_posts: tuple[Post, Post]) -> ProfileCandidateSet:
    evidence = [
        ProfileEvidence(
            post_id=item.post_id,
            required=True,
            source=EvidenceSource.POST_TEXT,
            excerpt="本人の投稿による根拠",
        )
        for item in required_posts
    ]
    candidate = ProfileCandidate(
        rank=1,
        value="東大前駅",
        confidence=0.9,
        status=ProfileStatus.FOUND,
        evidence=evidence,
        evidence_paths=[ProfileEvidencePath(evidence=evidence, confidence=0.9)],
    )
    return ProfileCandidateSet(
        attribute=ProfileAttribute.HOME_NEAREST_STATION,
        status=ProfileCandidateSetStatus.CANDIDATE,
        candidates=[candidate],
        candidate_pool=[candidate],
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
    assert estimate.localization_status == "insufficient"
    assert estimate.region.same_birthday is not None
    assert estimate.region.city is None and estimate.region.town is None
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
    # A near-home town fragment alone does not authorize a localized map.
    assert estimate.map.cells == [] and estimate.map.labels == []
    assert estimate.geoprofile is None
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
    assert without_photo["localization_status"] == "insufficient"
    assert without_photo["map"]["cells"] == []


def test_simulate_recomputes_the_residence_without_the_chosen_posts() -> None:
    simulated = simulate_claims_json([], CLUES, POSTS, [POSTS[2].post_id], gazetteer=GAZETTEER)

    assert {"delete", "broken", "after", "narrowing", "residence"} <= set(simulated)
    assert all(e["post_id"] != POSTS[2].post_id for e in simulated["residence"]["evidence"])
    without_tables = simulate_claims_json(
        [], CLUES, POSTS, [POSTS[2].post_id], gazetteer=Gazetteer()
    )
    assert without_tables["residence"] is None
    assert "residence" not in simulate_claims_json([], CLUES, POSTS, [POSTS[2].post_id])


def test_simulate_drops_map_localization_when_a_required_home_post_is_removed() -> None:
    base_scoring = GAZETTEER.scoring
    assert base_scoring is not None
    scoring = replace(
        base_scoring,
        stations=replace(base_scoring.stations, group=["8号線京王線", "1号線京王線"]),
    )
    gazetteer = replace(GAZETTEER, scoring=scoring)
    home_one, home_two = post(11, "自宅の最寄り駅の写真"), post(12, "自宅から駅まで毎朝歩いている")
    line_post = post(13, "京王線、また止まってる…")
    posts = [home_one, home_two, line_post]
    claim = station_claim((home_one, home_two))

    before = residence_json([], posts, gazetteer, profile_claims=[claim])
    assert before is not None
    assert before["localization_status"] == "supported"
    assert before["map"]["cells"]

    simulated = simulate_claims_json([claim], [], posts, [home_one.post_id], gazetteer=gazetteer)
    after = ResidenceEstimate.model_validate(simulated["residence"])
    assert after.localization_status == "insufficient"
    assert after.map.cells == [] and after.map.labels == []
    assert after.region.station is None and after.region.town is None
