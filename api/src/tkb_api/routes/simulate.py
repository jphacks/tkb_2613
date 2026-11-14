"""消したらどうなるか。選んだ投稿を消したとして推理し直し、崩れる項目を返す。

実際には消さない（Bluesky の削除 API は呼ばない）。モデルも呼ばない。
使うのは、そのセッションで最後に終わった診断の投稿と手がかり（メモリにだけある）。
選べるのはその診断の投稿だけで、ほかの ID と、もう消した投稿の ID は 422 で断る。
計算は、もう消した投稿を除いた状態から行う（routes/delete.py と同じ）。

  POST /api/simulate  {"delete": [投稿ID]}
  → {"delete": [投稿ID], "broken": [項目], "after": [結論]}
    after の clue_indices は、診断の conclusions イベントの clues での番号
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from tkb_api.bluesky import SessionStore
from tkb_api.pipeline import simulate_claims_json
from tkb_api.routes.session import current_session_id, get_session_store
from tkb_api.schemas import SimulateRequest

router = APIRouter(prefix="/api")


@router.post("/simulate")
def simulate(
    body: SimulateRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
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
    return simulate_claims_json(
        diagnosis.profile_claims,
        diagnosis.clues,
        diagnosis.posts,
        body.delete,
        diagnosis.deleted,
        diagnosis_at=diagnosis.diagnosis_at,
    )
