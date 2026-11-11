"""選んだ投稿を Bluesky から実際に消し、残った投稿で推理し直す（もういいよ）。

消すのは、画面でユーザーが投稿を選び、確認ダイアログで OK したときだけ。モデルは呼ばない。
選べるのはそのセッションで最後に診断した投稿だけで、ほかの ID は 422 で断る。
消すのはセッションの DID 本人の投稿だけ（bluesky.delete_own_posts）。
MOCK_MODE=1 のときは Bluesky に接続せず、全部消せたことにする。

  POST /api/delete  {"delete": [投稿ID]}
  → {"delete": [消せた投稿ID], "failed": [消せなかった投稿ID], "broken": [項目], "after": [結論]}
    broken・after は、それまでに消した投稿を除いた状態から、今回消せた投稿を除いて推理し直した結果。
    after の clue_indices は、診断の conclusions イベントの clues での番号（simulate と同じ）

セッションの診断の投稿と手がかりはそのまま残し（画面の手がかりの番号とずれないように）、
消せた投稿の ID だけを記録する（GET /api/diagnosis が消した投稿を除いて返すため）。
もう消した投稿をまた選んだら 422 で断る。
消したあとの投稿で最初から調べ直すには、もう一度診断する。
"""

import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, PostsDeleter, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.pipeline import simulate_json
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.session import current_session, current_session_id, get_session_store
from tkb_api.schemas import DeleteRequest
from tkb_engine.gazetteer import Gazetteer

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def get_delete_posts() -> PostsDeleter:
    return bluesky.delete_own_posts


def _deleted(reply: httpx.Response) -> bool:
    """内部経路の応答が「消せた」か。JSON でない・形が違う応答は、消せなかったとして扱う。"""
    if reply.status_code != 200:
        return False
    try:
        body = reply.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("deleted") is True


async def _delete(
    session: BlueskySession, settings: Settings, delete_posts: PostsDeleter, post_ids: list[str]
) -> list[str]:
    if settings.mock_mode:
        return list(post_ids)
    if session.auth_method == "oauth" and settings.auth_mode == "oauth":
        secret = settings.internal_auth_secret.get_secret_value()
        if not secret:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "削除の設定がありません")
        done: list[str] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for post_id in post_ids:
                if not bluesky.is_own_post_uri(post_id, session.did):
                    continue
                try:
                    reply = await client.post(
                        f"{settings.oauth_web_origin.rstrip('/')}/__internal/oauth/delete",
                        json={"did": session.did, "post_id": post_id},
                        headers={"X-Internal-Auth": secret},
                    )
                except httpx.HTTPError:
                    continue
                if _deleted(reply):
                    done.append(post_id)
                elif reply.status_code == 429:
                    raise bluesky.BlueskyRateLimitedError(done)
        return done
    if session.client is None:
        # モックでログインしたあとに MOCK_MODE=0 で起動し直した場合など
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインし直してください")
    return await delete_posts(session.client, session.did, post_ids)


@router.post("/delete")
async def delete(
    body: DeleteRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    session: Annotated[BlueskySession, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
    delete_posts: Annotated[PostsDeleter, Depends(get_delete_posts)],
) -> dict[str, Any]:
    diagnosis = store.get_diagnosis(session_id)
    if diagnosis is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "先に診断してください")
    known = {p.post_id for p in diagnosis.posts} - set(diagnosis.deleted)
    if any(post_id not in known for post_id in body.delete):
        # 送られた ID は文言に入れない
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "診断した投稿の中から選んでください"
        )

    requested = list(dict.fromkeys(body.delete))
    bluesky_busy = False
    try:
        deleted = set(await _delete(session, settings, delete_posts, requested))
    except bluesky.BlueskyRateLimitedError as e:
        # 途中で Bluesky に回数の制限で断られた。消せた分だけで推理し直し、残りは failed に入れる
        deleted, bluesky_busy = set(e.deleted), True
    done = [i for i in requested if i in deleted]
    failed = [i for i in requested if i not in deleted]
    # 投稿の ID は出さず、件数だけ
    logger.info("投稿の削除：%d 件を消し、%d 件は消せませんでした", len(done), len(failed))

    store.mark_deleted(session_id, done)

    sim = simulate_json(diagnosis.clues, diagnosis.posts, gazetteer, done, diagnosis.deleted)
    return {**sim, "failed": failed, "bluesky_busy": bluesky_busy}
