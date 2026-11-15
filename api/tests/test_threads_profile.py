"""Threads の診断結果に出すプロフィール推定。架空投稿と小さな学区の表だけで確かめる。"""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import threads
from tkb_common.schemas import (
    EvidenceSource,
    ProfileAttribute,
    ProfileCandidate,
    ProfileCandidateSet,
    ProfileCandidateSetStatus,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileStatus,
)
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.scoring.sample import build_tables

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}
# 林町小学校の学区は文京区（公開データの表と同じ1行だけ）
GAZETTEER = Gazetteer(
    school_districts=[
        {
            "kind": "小学校",
            "name": "林町小学校",
            "city": "文京区",
            "terms": "オープンデータ公開",
            "note": "",
        }
    ],
    scoring=build_tables(),
)


@pytest.fixture(autouse=True)
def _small_gazetteer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threads, "_cached_gazetteer", lambda data_dir: GAZETTEER)


def _client() -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,
        threads_public_origin=ORIGIN,
        gazetteer_dir=Path("/missing-threads-gazetteer"),
        share_enabled=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url=ORIGIN
    )


def _claims(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {claim["attribute"]: claim for claim in body["profile_claims"]}


async def _diagnosed(client: httpx.AsyncClient) -> dict[str, Any]:
    login = await client.post("/api/threads/mock/session", json={"consent": True}, headers=HEADERS)
    assert login.status_code == 200
    result = await client.post("/api/threads/diagnose", headers=HEADERS)
    assert result.status_code == 200
    body: dict[str, Any] = result.json()
    return body


@pytest.mark.anyio
async def test_text_only_posts_infer_the_child_school_and_its_district() -> None:
    async with _client() as client:
        snapshot = await _diagnosed(client)
        restored = (await client.get("/api/threads/diagnosis")).json()

    claims = _claims(snapshot)
    assert claims["child_school"]["value"] == "林町小学校"
    assert claims["residential_area"]["value"] == "文京区"
    assert claims["routine"]["value"].startswith("毎週火曜（")
    evidence_posts = {e["post_id"] for e in claims["child_school"]["evidence"]}
    assert evidence_posts == {"threads:9004", "threads:9005"}
    assert set(snapshot["profile_claim_suggestions"]) <= {
        "threads:9001",
        "threads:9002",
        "threads:9004",
        "threads:9005",
    }
    assert snapshot["profile_claim_suggestions"]
    assert restored == snapshot


@pytest.mark.anyio
async def test_rediagnosis_keeps_claims_and_renumbers_their_clues() -> None:
    async with _client() as client:
        await _diagnosed(client)
        after = await client.post(
            "/api/threads/rediagnose", json={"delete": ["threads:9001"]}, headers=HEADERS
        )

    body = after.json()
    claims = _claims(body)
    assert claims["child_school"]["value"] == "林町小学校"
    # 根拠の手がかりの番号は、再診断の clues（9001 の分を詰めた並び）を指す
    for claim in claims.values():
        for evidence in claim["evidence"]:
            if evidence["clue_index"] is not None:
                clue = body["clues"][evidence["clue_index"]]
                assert clue["post_id"] == evidence["post_id"]
    assert all(
        body["clues"][e["clue_index"]]["value"] == "林町小学校"
        for e in claims["child_school"]["evidence"]
        if e["clue_index"] is not None
    )


@pytest.mark.anyio
async def test_excluding_the_school_post_drops_the_claims_built_on_it() -> None:
    async with _client() as client:
        snapshot = await _diagnosed(client)
        after = await client.post(
            "/api/threads/rediagnose", json={"delete": ["threads:9005"]}, headers=HEADERS
        )
        after_all = await client.post(
            "/api/threads/rediagnose",
            json={"delete": ["threads:9001", "threads:9002", "threads:9005"]},
            headers=HEADERS,
        )
        restored = (await client.get("/api/threads/diagnosis")).json()

    body = after.json()
    assert "child_school" not in _claims(body)
    assert "residential_area" not in _claims(body)
    # 推定が残らなければ、その根拠だった投稿（9004）も削除候補に残さない
    assert not ({"threads:9004", "threads:9005"} & set(body["profile_claim_suggestions"]))
    assert after_all.json()["profile_claim_suggestions"] == []
    # 仮除外はメモリ上の計算だけで、診断結果そのものは変えない
    assert restored == snapshot


@pytest.mark.anyio
async def test_candidate_format_is_additive_cached_and_keeps_original_clue_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_infer_events = threads._infer_events
    captured: dict[str, Any] = {}

    def record_shared_input(
        posts: list[Any],
        extractions: list[Any],
        gazetteer: Gazetteer,
        diagnosis_at: Any = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        captured.update(
            posts=posts,
            extractions=extractions,
            gazetteer=gazetteer,
            diagnosis_at=diagnosis_at,
        )
        return original_infer_events(posts, extractions, gazetteer, diagnosis_at)

    monkeypatch.setattr(threads, "_infer_events", record_shared_input)
    async with _client() as client:
        legacy = await _diagnosed(client)
        candidate_response = await client.post(
            "/api/threads/diagnose?format=candidates", headers=HEADERS
        )
        restored = await client.get("/api/threads/diagnosis?format=candidates")
        legacy_restored = await client.get("/api/threads/diagnosis")
        simulated = await client.post(
            "/api/threads/simulate?format=candidates",
            json={"delete": ["threads:9005"]},
            headers=HEADERS,
        )
        after = await client.post(
            "/api/threads/rediagnose?format=candidates",
            json={"delete": ["threads:9005"]},
            headers=HEADERS,
        )
        after_legacy = await client.post(
            "/api/threads/rediagnose",
            json={"delete": ["threads:9005"]},
            headers=HEADERS,
        )

    assert candidate_response.status_code == restored.status_code == 200
    candidate = candidate_response.json()
    # Re-run only the shared, local inference over the exact captured posts/clues and timestamp.
    shared_events = await asyncio.to_thread(
        original_infer_events,
        captured["posts"],
        captured["extractions"],
        captured["gazetteer"],
        captured["diagnosis_at"],
    )
    shared = {name: value for name, value in shared_events}
    assert candidate["profile_claims"] == shared["conclusions"]["profile_claims"]
    assert candidate["plan"] == shared["plan"]
    assert candidate["narrowing"] == shared["conclusions"]["narrowing"]
    assert candidate["residence"] == shared["residence"]["residence"]
    assert restored.json() == candidate
    assert legacy_restored.json() == legacy
    assert "conclusions" in legacy and "conclusions" not in candidate
    assert {
        "deleted",
        "profile_claims",
        "profile_relations",
        "profile_claim_suggestions",
        "narrowing",
        "residence",
        "photo_place_results",
    } <= set(candidate)
    assert candidate["elapsed_ms"] == legacy["elapsed_ms"]

    simulation = simulated.json()
    assert "after" in simulation and "conclusions" not in simulation
    assert "threads:9005" not in str(simulation["after"])
    rediagnosed = after.json()
    assert "conclusions" not in rediagnosed
    assert [post["post_id"] for post in rediagnosed["posts"]] == [
        post["post_id"] for post in candidate["posts"]
    ]
    assert [clue["post_id"] for clue in rediagnosed["clues"]] == [
        clue["post_id"] for clue in candidate["clues"]
    ]
    assert rediagnosed["deleted"] == ["threads:9005"]
    assert rediagnosed["elapsed_ms"] == candidate["elapsed_ms"]
    assert not any(
        claim["attribute"] == "child_school" and claim["candidates"]
        for claim in rediagnosed["profile_claims"]
    )
    assert all(
        evidence["post_id"] != "threads:9005"
        for claim in rediagnosed["profile_claims"]
        for candidate in [*claim["candidates"], *claim["candidate_pool"]]
        for evidence in [
            *candidate["evidence"],
            *(item for path in candidate["evidence_paths"] for item in path["evidence"]),
        ]
    )
    for claim in rediagnosed["profile_claims"]:
        for candidate in [*claim["candidates"], *claim["candidate_pool"]]:
            for evidence in candidate["evidence"]:
                if evidence["clue_index"] is not None:
                    assert (
                        rediagnosed["clues"][evidence["clue_index"]]["post_id"]
                        == evidence["post_id"]
                    )
    # The legacy endpoint still exposes the compacted legacy clue numbering and shape.
    assert [post["post_id"] for post in after_legacy.json()["posts"]] == [
        f"threads:{n}" for n in range(9001, 9005)
    ]
    assert "conclusions" in after_legacy.json()


@pytest.mark.anyio
async def test_candidate_api_suppresses_map_when_a_required_home_post_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def shared_result(
        posts: list[Any], extractions: list[Any], gazetteer: Gazetteer, diagnosis_at: Any = None
    ) -> list[tuple[str, dict[str, Any]]]:
        # A town-fragment signal keeps the broad estimate alive after home support disappears.
        posts[2] = posts[2].model_copy(update={"text": "近所の法被に『弥生』"})
        evidence = [
            ProfileEvidence(
                post_id=post.post_id,
                required=True,
                source=EvidenceSource.POST_TEXT,
                excerpt="本人の自宅最寄り駅の投稿",
            )
            for post in posts[:2]
        ]
        candidate = ProfileCandidate(
            rank=1,
            value="東大前駅",
            confidence=0.9,
            status=ProfileStatus.FOUND,
            evidence=evidence,
            evidence_paths=[ProfileEvidencePath(evidence=evidence, confidence=0.9)],
        )
        candidate_set = ProfileCandidateSet(
            attribute=ProfileAttribute.HOME_NEAREST_STATION,
            status=ProfileCandidateSetStatus.CANDIDATE,
            candidates=[candidate],
            candidate_pool=[candidate],
        )
        claim_values = [candidate_set.model_dump(mode="json")]
        from tkb_api.pipeline import residence_json

        return [
            (
                "conclusions",
                {
                    "clues": [],
                    "conclusions": [],
                    "profile_claims": claim_values,
                    "profile_relations": [],
                    "profile_claim_suggestions": [],
                    "photo_place_results": [],
                    "narrowing": None,
                },
            ),
            ("plan", {"delete": [], "broken": [], "after": claim_values, "posts": []}),
            (
                "residence",
                {"residence": residence_json([], posts, gazetteer, profile_claims=[candidate_set])},
            ),
        ]

    monkeypatch.setattr(threads, "_infer_events", shared_result)
    async with _client() as client:
        login = await client.post(
            "/api/threads/mock/session", json={"consent": True}, headers=HEADERS
        )
        assert login.status_code == 200
        initial = await client.post("/api/threads/diagnose?format=candidates", headers=HEADERS)
        assert initial.status_code == 200
        before = initial.json()
        assert before["residence"]["localization_status"] == "supported"
        assert before["residence"]["map"]["cells"]

        simulate = await client.post(
            "/api/threads/simulate?format=candidates",
            json={"delete": ["threads:9001"]},
            headers=HEADERS,
        )
        after = await client.post(
            "/api/threads/rediagnose?format=candidates",
            json={"delete": ["threads:9001"]},
            headers=HEADERS,
        )
        restored = await client.get("/api/threads/diagnosis?format=candidates")

    simulated = simulate.json()
    assert simulated["residence"]["localization_status"] == "insufficient"
    assert simulated["residence"]["map"]["cells"] == []
    rediagnosed = after.json()
    assert rediagnosed["deleted"] == ["threads:9001"]
    assert rediagnosed["residence"]["localization_status"] == "insufficient"
    assert rediagnosed["residence"]["map"]["cells"] == []
    assert [post["post_id"] for post in rediagnosed["posts"]] == [
        post["post_id"] for post in before["posts"]
    ]
    assert restored.json() == before
