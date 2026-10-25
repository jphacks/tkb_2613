"""本人が明示的に作る閲覧専用リンク。トークンは URL の # に置き、アクセスログに残さない。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from tkb_api.bluesky import BlueskySession, SessionStore
from tkb_api.routes.diagnose import get_gazetteer, read_diagnosis
from tkb_api.routes.session import current_session, current_session_id, get_session_store
from tkb_api.shares import ShareStore
from tkb_engine.gazetteer import Gazetteer

router = APIRouter(prefix="/api")


class SharedResultRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


def get_share_store(request: Request) -> ShareStore:
    store: ShareStore = request.app.state.shares
    return store


@router.post("/result-link")
def create_result_link(
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
    shares: Annotated[ShareStore, Depends(get_share_store)],
    session: Annotated[BlueskySession, Depends(current_session)],
) -> dict[str, str]:
    payload = read_diagnosis(sessions, session_id, gazetteer)
    try:
        token = shares.create(payload, session.did)
    except ValueError:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "共有する結果が大きすぎます"
        ) from None
    return {"token": token}


@router.delete("/result-link", status_code=status.HTTP_204_NO_CONTENT)
def revoke_result_link(
    body: SharedResultRequest,
    session: Annotated[BlueskySession, Depends(current_session)],
    shares: Annotated[ShareStore, Depends(get_share_store)],
) -> None:
    shares.revoke(body.token, session.did)


@router.post("/shared-result")
def read_shared_result(
    body: SharedResultRequest,
    shares: Annotated[ShareStore, Depends(get_share_store)],
) -> dict[str, Any]:
    payload = shares.get(body.token)
    if payload is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "共有リンクが見つからないか、期限が切れました"
        )
    return payload
