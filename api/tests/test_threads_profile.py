"""Threads の診断結果に出すプロフィール推定。架空投稿と小さな学区の表だけで確かめる。"""

from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import threads
from tkb_engine.gazetteer import Gazetteer

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
    ]
)


@pytest.fixture(autouse=True)
def _small_gazetteer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threads, "load_gazetteer", lambda data_dir: GAZETTEER)


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
    evidence_posts = {e["post_id"] for e in claims["child_school"]["evidence"]}
    assert evidence_posts == {"threads:9004", "threads:9005"}
    assert set(snapshot["profile_claim_suggestions"]) <= evidence_posts
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
                assert clue["value"] == "林町小学校"


@pytest.mark.anyio
async def test_excluding_the_school_post_drops_the_claims_built_on_it() -> None:
    async with _client() as client:
        snapshot = await _diagnosed(client)
        after = await client.post(
            "/api/threads/rediagnose", json={"delete": ["threads:9005"]}, headers=HEADERS
        )
        restored = (await client.get("/api/threads/diagnosis")).json()

    body = after.json()
    assert "child_school" not in _claims(body)
    assert "residential_area" not in _claims(body)
    # 推定が残らなければ、その根拠だった投稿（9004）も削除候補に残さない
    assert body["profile_claim_suggestions"] == []
    # 仮除外はメモリ上の計算だけで、診断結果そのものは変えない
    assert restored == snapshot
