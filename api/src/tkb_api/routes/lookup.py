"""Web での照合（2段目）。診断で推定した名前・学校・年齢から、本人のページと写真を探す。

条件は CLAUDE.md の「Web での照合（2段目）」。
  POST /api/lookup        本文なし → {"found": true, "query", "url", "site", "title",
                                       "description", "matched": ["school", "age"]}
                                     見つからなければ {"found": false, "query"}
  POST /api/lookup/photo  本文なし → 見つけたページの og:image（画像そのもの）

名前・学校・URL はクライアントから受け取らない。使うのは、そのセッションの最後の診断の推定結果と、
/api/lookup で見つけてセッションのメモリに置いたページだけ。
WEB_LOOKUP_ENABLED=0 なら 404。MOCK_MODE=1 なら架空の固定結果を返し、外に接続しない。
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status

from tkb_api.bluesky import SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.session import current_session_id, get_session_store
from tkb_api.web_lookup.fetch import FetchError, Resolver, UnsafeUrlError, fetch_image, resolve_host
from tkb_api.web_lookup.search import SearchUnavailableError
from tkb_api.web_lookup.service import LookupResult, lookup, profile_from
from tkb_detect.errors import DetectError
from tkb_detect.vlm_client import VlmClient, VlmConfig
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import infer

router = APIRouter(prefix="/api")

# モックの写真。顔ではなく、身元カードと同じシルエット
MOCK_PHOTO_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
    b'<rect width="120" height="150" fill="#1d2440"/>'
    b'<circle cx="60" cy="55" r="28" fill="#3a4466"/>'
    b'<ellipse cx="60" cy="140" rx="48" ry="40" fill="#3a4466"/></svg>'
)
# 画像をこの API から直接開いても、中身が動かないようにする
PHOTO_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
}


def require_enabled(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.web_lookup_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return settings


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(headers={"User-Agent": "tkb_2613-lookup/1.0"}) as client:
        yield client


def get_resolver() -> Resolver:
    return resolve_host


def get_lookup_vlm(settings: Annotated[Settings, Depends(get_settings)]) -> VlmClient:
    try:
        return VlmClient(
            VlmConfig(
                base_url=settings.vlm_base_url,
                api_key=settings.vlm_api_key.get_secret_value(),
                model=settings.vlm_model,
                mock_mode=settings.mock_mode,
            )
        )
    except DetectError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "照合に使うモデルの接続先が設定されていません"
        ) from None


def _response(query: str, result: LookupResult | None) -> dict[str, Any]:
    if result is None:
        return {"found": False, "query": query}
    return {
        "found": True,
        "query": query,
        "url": result.url,
        "site": result.site,
        "title": result.title,
        "description": result.description,
        "matched": list(result.matched),
    }


def _mock_result(settings: Settings) -> LookupResult:
    try:
        doc = json.loads(settings.demo_lookup_path.read_text(encoding="utf-8"))
        return LookupResult(
            query=doc["query"],
            url=doc["url"],
            site=doc["site"],
            title=doc["title"],
            description=doc["description"],
            matched=tuple(doc["matched"]),
            image=None,
        )
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用のデータを読み込めませんでした"
        ) from None


@router.post("/lookup")
async def find_person(
    settings: Annotated[Settings, Depends(require_enabled)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    resolve: Annotated[Resolver, Depends(get_resolver)],
) -> dict[str, Any]:
    diagnosis = store.get_diagnosis(session_id)
    if diagnosis is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "先に診断してください")

    if settings.mock_mode:
        mock = _mock_result(settings)
        store.set_lookup(session_id, mock)
        return _response(mock.query, mock)

    profile = profile_from(infer(diagnosis.clues, diagnosis.posts, gazetteer))
    if profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "名前を推定できていません")
    try:
        query, result = await lookup(
            client, get_lookup_vlm(settings), settings.search_base_url, profile, resolve
        )
    except SearchUnavailableError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Web を検索できませんでした") from None
    store.set_lookup(session_id, result)
    return _response(query, result)


@router.post("/lookup/photo")
async def find_photo(
    settings: Annotated[Settings, Depends(require_enabled)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    resolve: Annotated[Resolver, Depends(get_resolver)],
) -> Response:
    result = store.get_lookup(session_id)
    if result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "先に Web で探してください")
    if settings.mock_mode:
        return Response(MOCK_PHOTO_SVG, media_type="image/svg+xml", headers=PHOTO_HEADERS)
    if result.image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "このページには写真がありません")
    try:
        body, content_type = await fetch_image(client, result.image, resolve)
    except (UnsafeUrlError, FetchError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "写真を取ってこられませんでした") from None
    return Response(body, media_type=content_type, headers=PHOTO_HEADERS)
