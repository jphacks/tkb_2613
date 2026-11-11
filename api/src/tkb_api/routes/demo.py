"""ログインなしの体験デモ。架空アカウントの投稿と手がかりで、診断と「消したらどうなる」を見せる。

使うのは eval/fixtures/demo_observations.json（DEMO_FIXTURE_PATH）の架空アカウントだけ。
モデル・Bluesky・セッションには接続せず、Cookie も読まない（MOCK_MODE=0 でも同じ）。
削除の API はない。

  GET  /api/demo/diagnosis  → {"demo": true, "posts", "clues", "conclusions", "plan"}
  POST /api/demo/simulate   {"delete": [投稿ID]} → {"delete", "broken", "after"}
    after の clue_indices は、GET /api/demo/diagnosis の clues での番号
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from tkb_api.config import Settings, get_settings
from tkb_api.pipeline import conclusions_json, plan_json, simulate_json
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.schemas import SimulateRequest
from tkb_common.schemas import Clue, Post
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


@router.get("/diagnosis")
def diagnosis(
    data: DemoData, gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)]
) -> dict[str, Any]:
    posts, clues = data
    return {
        "demo": True,
        "posts": [post.model_dump(mode="json") for post in posts],
        "clues": [clue.model_dump(mode="json") for clue in clues],
        "conclusions": conclusions_json(clues, posts, gazetteer),
        "plan": plan_json(clues, posts, gazetteer),
    }


@router.post("/simulate")
def simulate(
    body: SimulateRequest,
    data: DemoData,
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> dict[str, Any]:
    posts, clues = data
    known = {post.post_id for post in posts}
    if any(post_id not in known for post_id in body.delete):
        # 送られた ID は文言に入れない
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "デモの投稿の中から選んでください"
        )
    return simulate_json(clues, posts, gazetteer, body.delete)
