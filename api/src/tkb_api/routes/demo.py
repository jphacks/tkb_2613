"""ログインなしの体験デモ。架空アカウントの投稿と手がかりで、診断と「消したらどうなる」を見せる。

使うのは eval/fixtures/demo_observations.json（DEMO_FIXTURE_PATH）の架空アカウントだけ。
モデル・Bluesky・セッションには接続せず、Cookie も読まない（MOCK_MODE=0 でも同じ）。
削除の API はない。

  GET  /api/demo/diagnosis  → {"demo": true, "posts", "clues", "conclusions",
                              "profile_claims", "profile_relations",
                              "profile_claim_suggestions", "plan"}
  POST /api/demo/simulate   {"delete": [投稿ID]} → {"delete", "broken", "after"}

GET /api/demo/diagnosis の応答は、表（DEMO_FIXTURE_PATH）と地名の表（Gazetteer）が同じなら
毎回同じなので、一度だけ計算して JSON のバイト列のまま使い回す。起動時（lifespan）に
warm_diagnosis_cache で計算しておき、要求ごとには推理も計画も計算しない。
バイト列は変更できないので、要求の間で中身が書き換わることはない。
"""

import json
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from tkb_api.config import Settings, get_settings
from tkb_api.pipeline import (
    conclusions_json,
    plan_claims_json,
    simulate_claims_json,
)
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.schemas import SimulateRequest
from tkb_common.schemas import Clue, Post, ProfileCandidateSet
from tkb_engine.cross_post import (
    infer_owner_candidate_sets_with_web,
    infer_owner_profile_relations,
)
from tkb_engine.gazetteer import Gazetteer

router = APIRouter(prefix="/api/demo")


@lru_cache(maxsize=2)
def _load(path: Path) -> tuple[tuple[Post, ...], tuple[Clue, ...]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    posts = tuple(Post.model_validate(p) for p in doc["posts"])
    clues = tuple(Clue.model_validate(c) for c in doc["clues"])
    return posts, clues


def get_demo_data(
    settings: Annotated[Settings, Depends(get_settings)],
) -> tuple[tuple[Post, ...], tuple[Clue, ...]]:
    try:
        return _load(settings.demo_fixture_path)
    except (OSError, ValueError, KeyError, TypeError):
        # pydantic の ValidationError は ValueError の仲間。パスや中身はエラーの文言に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "体験デモのデータを読み込めませんでした"
        ) from None


DemoData = Annotated[tuple[tuple[Post, ...], tuple[Clue, ...]], Depends(get_demo_data)]


@dataclass(frozen=True)
class _CachedDiagnosis:
    fixture_path: Path
    gazetteer: Gazetteer
    profile_claims: tuple[ProfileCandidateSet, ...]
    body: bytes


_cache_lock = threading.Lock()
_cached: _CachedDiagnosis | None = None


def _render_diagnosis(
    posts: tuple[Post, ...], clues: tuple[Clue, ...], gazetteer: Gazetteer
) -> tuple[tuple[ProfileCandidateSet, ...], bytes]:
    profile_claims = tuple(
        infer_owner_candidate_sets_with_web(list(posts), list(clues), [], gazetteer=gazetteer)
    )
    profile_relations = infer_owner_profile_relations(
        list(posts), profile_claims, clues=list(clues), gazetteer=gazetteer
    )
    plan = plan_claims_json(profile_claims, clues, posts)
    doc = {
        "demo": True,
        "posts": [post.model_dump(mode="json") for post in posts],
        "clues": [clue.model_dump(mode="json") for clue in clues],
        "conclusions": conclusions_json(clues, posts, gazetteer),
        "profile_claims": [item.model_dump(mode="json") for item in profile_claims],
        "profile_relations": [item.model_dump(mode="json") for item in profile_relations],
        "profile_claim_suggestions": list(plan["delete"]),
        "plan": plan,
    }
    # FastAPI の JSONResponse と同じ書き出し方
    body = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return profile_claims, body


def _diagnosis_entry(
    fixture_path: Path, data: tuple[tuple[Post, ...], tuple[Clue, ...]], gazetteer: Gazetteer
) -> _CachedDiagnosis:
    """表のパスと Gazetteer（同じオブジェクトか）が前回と同じなら、前回の応答を返す。

    テストで設定や Gazetteer を差し替えたときは、古い応答を返さずに計算し直す。
    同時に来た最初の要求で何度も計算しないよう、計算はロックの中で1回だけにする。
    """
    global _cached

    def hit(entry: _CachedDiagnosis | None) -> _CachedDiagnosis | None:
        if entry is None or entry.fixture_path != fixture_path or entry.gazetteer is not gazetteer:
            return None
        return entry

    entry = hit(_cached)
    if entry is not None:
        return entry
    with _cache_lock:
        entry = hit(_cached)
        if entry is None:
            posts, clues = data
            profile_claims, body = _render_diagnosis(posts, clues, gazetteer)
            entry = _CachedDiagnosis(fixture_path, gazetteer, profile_claims, body)
            _cached = entry
        return entry


def warm_diagnosis_cache(settings: Settings) -> None:
    """起動時に体験デモの診断を計算しておく。表が読めなくても起動は止めない（要求には503）。"""
    try:
        data = get_demo_data(settings)
    except HTTPException:
        logging.getLogger(__name__).warning("体験デモのデータを読み込めませんでした")
        return
    _diagnosis_entry(settings.demo_fixture_path, data, get_gazetteer(settings))


@router.get("/diagnosis")
def diagnosis(
    data: DemoData,
    settings: Annotated[Settings, Depends(get_settings)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> Response:
    body = _diagnosis_entry(settings.demo_fixture_path, data, gazetteer).body
    return Response(content=body, media_type="application/json")


@router.post("/simulate")
def simulate(
    body: SimulateRequest,
    data: DemoData,
    settings: Annotated[Settings, Depends(get_settings)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> dict[str, Any]:
    posts, clues = data
    known = {post.post_id for post in posts}
    if any(post_id not in known for post_id in body.delete):
        # 送られた ID は文言に入れない
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "デモの投稿の中から選んでください"
        )
    profile_claims = _diagnosis_entry(settings.demo_fixture_path, data, gazetteer).profile_claims
    return simulate_claims_json(profile_claims, clues, posts, body.delete)
