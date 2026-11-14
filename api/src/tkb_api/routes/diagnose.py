"""診断。ログインした本人の投稿を読み、結果を Server-Sent Events で 1 件ずつ流す。

イベントの形は web/src/types/diagnose.ts と同時に変更すること。
  event: post         data: {"post": 投稿}                          投稿ごと
  event: clues        data: {"post_id", "clues": [手がかり], "error"} 手がかりの取り出しが終わった順
  event: conclusions  data: {"clues": [全手がかり], "conclusions": [{"rule", "attribute",
                             "value", "clue_indices", "note"}]}      最後に1回。番号は clues の並び
  event: plan         data: {"delete": [投稿ID], "broken": [項目], "after": [結論],
                             "posts": [{"post_id", "broken"}]}       危ない投稿。番号は clues の並び
  event: done         data: {"posts_seen": 件数}

推理まで終わったら、投稿と手がかりをセッションのメモリに置く（POST /api/simulate で使う）。
ディスクやログには残さない。診断を始めたときに、前の診断の分は消す。

MOCK_MODE=1 のときは、架空のデモ用アカウントの投稿と手がかりを流す
（Bluesky にもモデルにも接続しない）。
MOCK_MODE=0 のときは、セッションの DID 本人の投稿を Bluesky から直近 MAX_POSTS 件取り、
写真を cdn.bsky.app から取って手がかりを取り出し、推理する。

始める前に、公開時間帯・同じセッションでの診断中・1日の回数・同時実行の枠・モデルの応答を
確かめ、だめならストリームを始めずに理由のコードつきで断る（tkb_api.errors、tkb_api.limits）。
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from atproto import AsyncClient
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.background import BackgroundTask

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, Diagnosis, PostsFetcher, SessionStore
from tkb_api.commons_reference import search_commons_references
from tkb_api.config import Settings, get_settings
from tkb_api.errors import BLUESKY_BUSY_MESSAGE, refusal
from tkb_api.limits import (
    JST,
    AlreadyRunningError,
    BusyError,
    DailyLimitError,
    DiagnoseLimiter,
    Lease,
    availability,
    next_jst_midnight,
)
from tkb_api.photo_place_web import (
    mark_photo_place_lookup_unavailable,
    search_photo_places,
)
from tkb_api.pipeline import (
    conclusions_json,
    diagnose_events,
    fetch_single_image,
    load_gazetteer,
    mock_extractions,
    plan_claims_json,
    real_extractions,
)
from tkb_api.public_web_identity import (
    ExternalLookupResult,
    mark_owner_linked,
    search_external_profiles,
)
from tkb_api.routes.session import current_session, current_session_id, get_session_store
from tkb_common.schemas import (
    Clue,
    ExternalLookupStatus,
    ExternalProfileResult,
    PhotoPlaceResult,
    Post,
    WebFact,
)
from tkb_detect.batch import PostExtraction
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor, build_extractor
from tkb_engine.cross_post import (
    profile_relations_after_deletion,
    recalculate_profile_candidate_sets,
)
from tkb_engine.gazetteer import Gazetteer

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_demo_posts(settings: Settings) -> list[Post]:
    try:
        doc = json.loads(settings.demo_fixture_path.read_text(encoding="utf-8"))
        posts: list[Post] = []
        for raw_post in doc["posts"]:
            post = dict(raw_post)
            images = []
            for raw_image in post.get("images", []):
                image = dict(raw_image)
                local_file = image.pop("local_file", None)
                if local_file is not None:
                    if not isinstance(local_file, str) or Path(local_file).name != local_file:
                        raise ValueError("invalid local fixture image")
                    image["mock_asset"] = local_file
                images.append(image)
            post["images"] = images
            posts.append(Post.model_validate(post))
        return posts
    except (OSError, ValueError, KeyError, TypeError):
        # pydantic の ValidationError は ValueError の仲間。パスや中身はエラーの文言に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用のデータを読み込めませんでした"
        ) from None


@router.get("/mock-assets/{asset_name}")
def mock_asset(asset_name: str, request: Request) -> FileResponse:
    """Serve fixture images from the fixture's sibling images directory in mock mode only."""
    settings = request.app.state.settings
    if (
        not settings.mock_mode
        or not settings.mock_local_assets_enabled
        or Path(asset_name).name != asset_name
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "画像が見つかりません")
    referenced_assets = {
        image.mock_asset
        for post in _load_demo_posts(settings)
        for image in post.images
        if image.mock_asset is not None
    }
    if asset_name not in referenced_assets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "画像が見つかりません")
    image_root = (settings.demo_fixture_path.parent / "images").resolve()
    image_path = (image_root / asset_name).resolve()
    if image_path.parent != image_root or not image_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "画像が見つかりません")
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(image_path.suffix.lower())
    if media_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "画像が見つかりません")
    return FileResponse(
        image_path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


async def _stream(events: AsyncIterator[tuple[str, dict[str, Any]]]) -> AsyncIterator[str]:
    async for event, data in events:
        yield _sse(event, data)


async def _with_keep_alive(source: AsyncIterator[str], interval: float) -> AsyncIterator[str]:
    """source の間が interval 秒より空いたら、SSE のコメント（: keep-alive）を送る。

    途中の中継（Vercel、Tailscale、Cloudflare）に、止まった接続だと思われて切られないようにする。
    画面はコメント行を読み飛ばす。
    """
    pending = asyncio.ensure_future(anext(source))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk
            pending = asyncio.ensure_future(anext(source))
    finally:
        pending.cancel()


async def _release_when_closed(source: AsyncIterator[str], lease: Lease) -> AsyncGenerator[str]:
    """source を流し終えたとき・途中で切れたとき・失敗したときのどれでも、診断の枠を返す。

    送るたびに（keep-alive も）枠の期限を延ばすので、長い診断でも途中で枠を失わない。
    """
    try:
        async for chunk in source:
            lease.touch()
            yield chunk
    finally:
        lease.release()


def _sse_response(source: AsyncIterator[str], lease: Lease) -> StreamingResponse:
    """診断の SSE の応答。枠は generator の finally と、応答のあとの後始末の両方で返す。

    本文を読み始める前に接続が切れると generator が始まらず、finally が走らない。
    そのときも後始末（BackgroundTask）で返す。release は何度呼んでもよい。
    """
    return StreamingResponse(
        _release_when_closed(source, lease),
        media_type="text/event-stream",
        # 途中の中継（プロキシ）にためこまれず、1 件ずつ届くようにする
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(lease.release),
    )


Clock = Callable[[], datetime]


def get_clock() -> Clock:
    return lambda: datetime.now(JST)


def get_diagnose_limiter(request: Request) -> DiagnoseLimiter:
    limiter: DiagnoseLimiter = request.app.state.diagnose_limiter
    return limiter


def get_fetch_posts() -> PostsFetcher:
    return bluesky.fetch_own_posts


ProfileTextFetcher = Callable[[Any, str], Awaitable[str]]
ExternalProfileSearcher = Callable[[str], Awaitable[ExternalLookupResult]]
PhotoPlaceSearcher = Callable[
    [Sequence[PhotoPlaceResult], Sequence[Clue]], Awaitable[list[PhotoPlaceResult]]
]
PhotoPlaceReferenceSearcher = Callable[
    [Sequence[PhotoPlaceResult], Sequence[Clue], Sequence[Post]], Awaitable[list[PhotoPlaceResult]]
]


class DiagnoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_web_lookup_consent: StrictBool = False
    photo_place_web_lookup_consent: StrictBool = False
    photo_place_reference_consent: StrictBool = False


def get_fetch_profile_text() -> ProfileTextFetcher:
    return bluesky.fetch_own_profile_text


def get_external_profile_searcher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExternalProfileSearcher:
    async def search(handle: str) -> ExternalLookupResult:
        return await search_external_profiles(handle, settings.brave_search_api_key)

    return search


def get_photo_place_searcher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PhotoPlaceSearcher:
    async def search(
        results: Sequence[PhotoPlaceResult], clues: Sequence[Clue]
    ) -> list[PhotoPlaceResult]:
        return await search_photo_places(results, clues, settings.brave_search_api_key)

    return search


def _load_demo_web_facts(settings: Settings) -> list[WebFact]:
    try:
        doc = json.loads(settings.demo_fixture_path.read_text(encoding="utf-8"))
        return [WebFact.model_validate(fact) for fact in doc.get("web_facts", [])]
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用の公開Web情報を読み込めませんでした"
        ) from None


def _load_demo_external_lookup(settings: Settings) -> tuple[str, list[ExternalProfileResult]]:
    try:
        doc = json.loads(settings.demo_fixture_path.read_text(encoding="utf-8"))
        fixture = doc.get("external_lookup_fixture", {})
        profile_text = fixture.get("owner_profile_text", "")
        results = [
            ExternalProfileResult(
                id=f"mock-{index}",
                url=item["url"],
                domain=item["domain"],
                title=item["title"],
                status="candidate",
                owner_evidence=None,
            )
            for index, item in enumerate(fixture.get("results", []))
        ]
        return profile_text if isinstance(profile_text, str) else "", results
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用の公開Web候補を読み込めませんでした"
        ) from None


@lru_cache(maxsize=4)
def _cached_gazetteer(data_dir: Path) -> Gazetteer:
    return load_gazetteer(data_dir)


def get_gazetteer(settings: Annotated[Settings, Depends(get_settings)]) -> Gazetteer:
    return _cached_gazetteer(settings.gazetteer_dir)


ExtractorFactory = Callable[[], Extractor]


def get_extractor_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> ExtractorFactory:
    """手がかりを取り出す部品は、本番の診断で使うときに作る。

    接続先の確認（第三者の AI サービスを拒否するなど）は作るときに行うので、
    ログインの確認やモックの診断より先に失敗しないようにする。
    """

    def build() -> Extractor:
        return build_extractor(
            mock_mode=settings.mock_mode,
            vlm_base_url=settings.vlm_base_url,
            vlm_api_key=settings.vlm_api_key.get_secret_value(),
            vlm_model=settings.vlm_model,
            ocr_base_url=settings.ocr_base_url,
            allowed_hosts=settings.model_allowed_host_suffixes.split(","),
            text_backend=settings.text_backend,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            station_names={row["station_name"] for row in gazetteer.stations},
        )

    return build


def _build_extractor(factory: ExtractorFactory) -> Extractor:
    try:
        return factory()
    except DetectError:
        # 接続先の URL などは応答に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "画像を読むモデルの接続先が設定されていません"
        ) from None


async def _fetch_own_posts(
    session: BlueskySession, settings: Settings, fetch_posts: PostsFetcher
) -> list[Post]:
    client = session.client
    if session.auth_method == "oauth" and settings.auth_mode == "oauth":
        client = AsyncClient(base_url="https://public.api.bsky.app/xrpc")
    if client is None:
        # モックでログインしたあとに MOCK_MODE=0 で起動し直した場合など
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインし直してください")
    try:
        return await fetch_posts(client, session.did, settings.max_posts)
    except bluesky.BlueskyRateLimitedError:
        raise refusal(
            status.HTTP_503_SERVICE_UNAVAILABLE, "bluesky_busy", BLUESKY_BUSY_MESSAGE
        ) from None
    except bluesky.BlueskyUnavailableError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Bluesky から投稿を取得できませんでした"
        ) from None


@router.get("/diagnosis")
def read_diagnosis(
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> dict[str, Any]:
    """同じログインセッションで画面を開き直したとき、直近の完了結果を返す。"""
    diagnosis = store.get_diagnosis(session_id)
    if diagnosis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "復元できる診断結果はありません")
    posts, clues, deleted = diagnosis.posts, diagnosis.clues, diagnosis.deleted
    deleted_ids = set(deleted)
    remaining_posts = [post for post in posts if post.post_id not in deleted_ids]
    remaining_clues = [clue for clue in clues if clue.post_id not in deleted_ids]
    profile_claims = recalculate_profile_candidate_sets(
        diagnosis.profile_claims,
        deleted_ids,
        remaining_posts,
        clues=remaining_clues,
        diagnosis_at=diagnosis.diagnosis_at,
    )
    profile_relations = profile_relations_after_deletion(
        diagnosis.profile_relations, deleted, profile_claims
    )
    return {
        "posts": [post.model_dump(mode="json") for post in posts],
        "clues": [clue.model_dump(mode="json") for clue in clues],
        "photo_place_results": [
            item.model_dump(mode="json")
            for item in diagnosis.photo_place_results
            if item.post_id not in deleted_ids
        ],
        "deleted": list(deleted),
        "conclusions": conclusions_json(clues, posts, gazetteer, deleted),
        "plan": plan_claims_json(
            profile_claims,
            remaining_clues,
            remaining_posts,
            diagnosis_at=diagnosis.diagnosis_at,
        ),
        "profile_claims": [claim.model_dump(mode="json") for claim in profile_claims],
        "profile_relations": [relation.model_dump(mode="json") for relation in profile_relations],
        "profile_claim_suggestions": [
            post_id for post_id in diagnosis.profile_claim_suggestions if post_id not in deleted
        ],
        "web_facts": [fact.model_dump(mode="json") for fact in diagnosis.web_facts],
        "web_lookup_status": diagnosis.web_lookup_status,
        "external_profile_results": [
            result.model_dump(mode="json") for result in diagnosis.external_profile_results
        ],
        "external_lookup_status": diagnosis.external_lookup_status.value,
        "owner_profile_text": diagnosis.owner_profile_text,
        "self_report_clues": [clue.model_dump(mode="json") for clue in diagnosis.self_report_clues],
    }


def _ensure_open(settings: Settings, now: datetime) -> None:
    """公開時間外なら、次の公開の開始時刻（なければ null）をつけて断る。"""
    avail = availability(settings.public_windows, now)
    if avail.is_open:
        return
    next_open = avail.next_open.isoformat() if avail.next_open else None
    message = "公開時間外です" if next_open else "公開は終了しました"
    raise refusal(status.HTTP_503_SERVICE_UNAVAILABLE, "closed", message, next_open=next_open)


def _acquire(
    limiter: DiagnoseLimiter,
    settings: Settings,
    session_id: str,
    did: str,
    now: datetime,
    *,
    check_daily: bool = True,
) -> Lease:
    try:
        return limiter.acquire(session_id, did, check_daily=check_daily)
    except AlreadyRunningError:
        raise refusal(
            status.HTTP_409_CONFLICT, "already_running", "このアカウントの別の診断が進んでいます"
        ) from None
    except DailyLimitError:
        resets_at = next_jst_midnight(now)
        raise refusal(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "daily_limit",
            "今日の診断回数の上限に達しました",
            headers={"Retry-After": str(max(1, int((resets_at - now).total_seconds())))},
            limit=settings.diagnose_daily_limit,
            resets_at=resets_at.isoformat(),
        ) from None
    except BusyError:
        retry_after = settings.diagnose_busy_retry_after_seconds
        raise refusal(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "busy",
            "混雑しています",
            headers={"Retry-After": str(retry_after)},
            retry_after=retry_after,
        ) from None


async def _ensure_model_reachable(extractor: Extractor, settings: Settings) -> None:
    if not await extractor.model_reachable(settings.model_probe_timeout_seconds):
        raise refusal(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "model_unavailable",
            "診断モデルの準備ができていません",
        )


@router.post("/diagnose")
async def diagnose(
    session: Annotated[BlueskySession, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    fetch_posts: Annotated[PostsFetcher, Depends(get_fetch_posts)],
    fetch_profile_text: Annotated[ProfileTextFetcher, Depends(get_fetch_profile_text)],
    extractor_factory: Annotated[ExtractorFactory, Depends(get_extractor_factory)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
    external_searcher: Annotated[ExternalProfileSearcher, Depends(get_external_profile_searcher)],
    photo_place_searcher: Annotated[PhotoPlaceSearcher, Depends(get_photo_place_searcher)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    session_id: Annotated[str, Depends(current_session_id)],
    limiter: Annotated[DiagnoseLimiter, Depends(get_diagnose_limiter)],
    clock: Annotated[Clock, Depends(get_clock)],
    payload: Annotated[DiagnoseRequest | None, Body()] = None,
) -> StreamingResponse:
    public_web_lookup_consent = payload.public_web_lookup_consent if payload is not None else False
    photo_place_web_lookup_consent = (
        payload.photo_place_web_lookup_consent if payload is not None else False
    )
    photo_place_reference_consent = (
        payload.photo_place_reference_consent if payload is not None else False
    )
    now = clock()
    _ensure_open(settings, now)
    lease = _acquire(limiter, settings, session_id, session.did, now)
    try:
        events = await _prepare_events(settings, session, fetch_posts, extractor_factory)
    except BaseException:
        lease.release()
        raise

    # ここで診断を本当に始める。今日の回数はここで数える（混雑やモデル・Bluesky の不調で
    # 始められなかった分は数えない）
    lease.count()
    store.set_diagnosis(session_id, None)
    posts, extractions, interval = events

    web_facts: list[WebFact] = []
    web_lookup_status = "not_run"
    owner_profile_text = ""
    owner_profile_analyzer: Callable[[str], Awaitable[list[Clue]]] | None = None
    external_profile_results: list[ExternalProfileResult] = []
    external_lookup_status = ExternalLookupStatus.NOT_REQUESTED
    external_lookup: Callable[[], Awaitable[ExternalLookupResult]] | None = None
    if settings.mock_mode:
        web_facts = _load_demo_web_facts(settings)
        web_lookup_status = "fixture" if web_facts else "not_run"
        if public_web_lookup_consent:
            owner_profile_text, demo_results = _load_demo_external_lookup(settings)
            external_profile_results = list(
                mark_owner_linked(posts, owner_profile_text, demo_results)
            )
            external_lookup_status = ExternalLookupStatus.FIXTURE
    else:
        try:
            if session.client is not None:
                owner_profile_text = await fetch_profile_text(session.client, session.did)
            elif session.auth_method == "oauth" and settings.auth_mode == "oauth":
                profile_client = AsyncClient(base_url="https://public.api.bsky.app/xrpc")
                try:
                    owner_profile_text = await fetch_profile_text(profile_client, session.did)
                finally:
                    await profile_client.request.close()
        except bluesky.BlueskyUnavailableError:
            # 投稿の診断は続ける。プロフィール文は補助的な根拠にすぎない。
            owner_profile_text = ""
        if owner_profile_text:
            try:
                profile_extractor = _build_extractor(extractor_factory)
            except BaseException:
                lease.release()
                raise

            def analyze_profile(text: str) -> Awaitable[list[Clue]]:
                return profile_extractor.extract_profile_text(session.did, text)

            owner_profile_analyzer = analyze_profile
        if public_web_lookup_consent and settings.public_web_lookup_available:

            async def lookup_external() -> ExternalLookupResult:
                lookup = await external_searcher(session.handle)
                return ExternalLookupResult(
                    lookup.status, mark_owner_linked(posts, owner_profile_text, lookup.results)
                )

            external_lookup = lookup_external
        elif public_web_lookup_consent:
            external_lookup_status = ExternalLookupStatus.UNAVAILABLE

    photo_place_lookup: PhotoPlaceSearcher | None = None
    if photo_place_web_lookup_consent:
        if settings.photo_place_web_lookup_available:
            photo_place_lookup = photo_place_searcher
        else:
            reason = (
                "mock_external_lookup_disabled" if settings.mock_mode else "missing_brave_api_key"
            )
            if not settings.mock_mode and settings.diagnose_daily_limit <= 0:
                reason = "photo_place_daily_limit_disabled"

            async def unavailable_photo_place_lookup(
                results: Sequence[PhotoPlaceResult], clues: Sequence[Clue]
            ) -> list[PhotoPlaceResult]:
                return mark_photo_place_lookup_unavailable(results, clues, reason)

            photo_place_lookup = unavailable_photo_place_lookup

    photo_place_reference_lookup: PhotoPlaceReferenceSearcher | None = None
    if photo_place_reference_consent and settings.commons_reference_lookup_available:

        async def lookup_commons_references(
            results: Sequence[PhotoPlaceResult], clues: Sequence[Clue], posts: Sequence[Post]
        ) -> list[PhotoPlaceResult]:
            return await search_commons_references(
                results,
                clues,
                posts,
                gazetteer,
                fetch_single_image,
            )

        photo_place_reference_lookup = lookup_commons_references

    profile_result: dict[str, Any] = {}
    diagnosis_at = datetime.now(UTC)

    def save_profile_result(result: dict[str, Any]) -> None:
        profile_result.update(result)

    def save(clues: list[Clue]) -> None:
        store.set_diagnosis(
            session_id,
            Diagnosis(
                posts=tuple(posts),
                clues=tuple(clues),
                photo_place_results=tuple(profile_result.get("photo_place_results", ())),
                profile_claims=tuple(profile_result.get("profile_claims", ())),
                profile_relations=tuple(profile_result.get("profile_relations", ())),
                profile_claim_suggestions=tuple(
                    profile_result.get("profile_claim_suggestions", ())
                ),
                web_facts=tuple(profile_result.get("web_facts", ())),
                web_lookup_status=profile_result.get("web_lookup_status", "not_run"),
                external_profile_results=tuple(profile_result.get("external_profile_results", ())),
                external_lookup_status=profile_result.get(
                    "external_lookup_status", ExternalLookupStatus.NOT_REQUESTED
                ),
                owner_profile_text=profile_result.get("owner_profile_text", ""),
                self_report_clues=tuple(profile_result.get("self_report_clues", ())),
                diagnosis_at=diagnosis_at,
            ),
        )

    stream = diagnose_events(
        posts,
        extractions,
        gazetteer,
        interval,
        on_finished=save,
        on_result=save_profile_result,
        diagnosis_at=diagnosis_at,
        owner_profile_text=owner_profile_text,
        owner_profile_analyzer=owner_profile_analyzer,
        web_facts=web_facts,
        web_lookup_status=web_lookup_status,
        external_profile_results=external_profile_results,
        external_lookup_status=external_lookup_status,
        external_lookup=external_lookup,
        photo_place_lookup=photo_place_lookup,
        photo_place_reference_lookup=photo_place_reference_lookup,
    )
    return _sse_response(_with_keep_alive(_stream(stream), settings.sse_keepalive_seconds), lease)


async def _prepare_events(
    settings: Settings,
    session: BlueskySession,
    fetch_posts: PostsFetcher,
    extractor_factory: ExtractorFactory,
) -> tuple[list[Post], AsyncIterator[PostExtraction], float]:
    """診断に流す投稿と、手がかりを取り出す処理を用意する（モデルの確認と投稿の取得）。"""
    if settings.mock_mode:
        posts = _load_demo_posts(settings)
        interval = settings.mock_event_interval_seconds
        return posts, mock_extractions(settings.demo_fixture_path, posts, interval), interval

    if session.client is None and not (
        session.auth_method == "oauth" and settings.auth_mode == "oauth"
    ):
        # OAuth は次の _fetch_own_posts で公開 AppView を使う。旧方式の無効なセッションだけ拒否する
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインし直してください")
    extractor = _build_extractor(extractor_factory)
    await _ensure_model_reachable(extractor, settings)
    started = time.monotonic()
    posts = await _fetch_own_posts(session, settings, fetch_posts)
    fetched = time.monotonic() - started
    logger.info("診断の時間：投稿の取得 %.1f 秒（%d 件）", fetched, len(posts))
    return posts, real_extractions(extractor, posts), 0
