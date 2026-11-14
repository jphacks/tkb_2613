"""Threads 専用の本人認証・読み取り専用テキスト診断。"""

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from tkb_api.config import Settings
from tkb_api.origin import check_origin
from tkb_api.pipeline import (
    Event,
    diagnose_events,
    plan_json,
    real_extractions,
    simulation_json,
)
from tkb_api.routes.diagnose import _cached_gazetteer
from tkb_api.schemas import SimulateRequest
from tkb_api.threads_poc import (
    THREADS_API,
    ThreadsPocError,
    _get,
    fetch_own_posts,
    fetch_threads_images,
    to_post,
)
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    Post,
    ProfileCandidateSet,
    ProfileEvidence,
    ProfileItem,
)
from tkb_detect.batch import PostExtraction, extract_posts
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor, build_extractor
from tkb_engine.cross_post import claims_after_deletion
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.planner import simulate as simulate_deletion
from tkb_engine.rules import infer

router = APIRouter(prefix="/api/threads", tags=["threads"])
SESSION_COOKIE = "threads_tkb_session"
START_COOKIE = "threads_oauth_start"
START_TTL_S = 300


class ThreadsCallbackAccessFilter(logging.Filter):
    """uvicorn のアクセスログから OAuth code と state のクエリを除く。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.startswith("/api/threads/callback?"):
                clean = list(args)
                clean[2] = "/api/threads/callback"
                record.args = tuple(clean)
        return True


@dataclass
class PendingAuth:
    verifier: str
    nonce: str
    expires_at: float


@dataclass
class ThreadsSession:
    token: str | None
    owner_id: str
    username: str
    expires_at: float
    snapshot: dict[str, Any] | None = None
    posts: list[Post] = field(default_factory=list)
    clues: list[Clue] = field(default_factory=list)
    profile_claims: list[ProfileItem] = field(default_factory=list)
    profile_claim_suggestions: list[str] = field(default_factory=list)
    busy: bool = False
    fetched: bool = False
    demo_backend: Literal["preset", "vlm"] = "preset"


class ThreadsSessionStore:
    """OAuth state、トークン、診断結果をプロセスメモリだけに置く。"""

    def __init__(self, ttl_s: int) -> None:
        self.ttl_s = ttl_s
        self.pending: dict[str, PendingAuth] = {}
        self.sessions: dict[str, ThreadsSession] = {}
        self.lock = RLock()

    def start(self, verifier: str, nonce: str) -> str:
        state = secrets.token_urlsafe(32)
        with self.lock:
            self.pending = {
                key: value
                for key, value in self.pending.items()
                if value.expires_at > time.monotonic()
            }
            self.pending[state] = PendingAuth(verifier, nonce, time.monotonic() + START_TTL_S)
        asyncio.get_running_loop().call_later(START_TTL_S, self._expire_pending, state)
        return state

    def _expire_pending(self, state: str) -> None:
        with self.lock:
            self.pending.pop(state, None)

    def consume(self, state: str, nonce: str | None) -> str | None:
        with self.lock:
            pending = self.pending.pop(state, None)
        if pending is None or nonce is None or not secrets.compare_digest(pending.nonce, nonce):
            return None
        return pending.verifier if pending.expires_at > time.monotonic() else None

    def create(
        self,
        token: str | None,
        owner_id: str,
        username: str,
        demo_backend: Literal["preset", "vlm"] = "preset",
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[session_id] = ThreadsSession(
                token,
                owner_id,
                username,
                time.monotonic() + self.ttl_s,
                demo_backend=demo_backend,
            )
        asyncio.get_running_loop().call_later(self.ttl_s, self.delete, session_id)
        return session_id

    def get(self, session_id: str | None) -> ThreadsSession | None:
        if not session_id:
            return None
        with self.lock:
            session = self.sessions.get(session_id)
            if session is not None and session.expires_at <= time.monotonic():
                self.sessions.pop(session_id, None)
                return None
            return session

    def delete(self, session_id: str | None) -> None:
        if session_id:
            with self.lock:
                self.sessions.pop(session_id, None)

    def delete_for_owner(self, owner_id: str) -> None:
        with self.lock:
            for session_id, session in list(self.sessions.items()):
                if session.owner_id == owner_id:
                    self.sessions.pop(session_id, None)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.threads_settings
    return settings


def _store(request: Request) -> ThreadsSessionStore:
    store: ThreadsSessionStore = request.app.state.threads_sessions
    return store


def _origin(request: Request) -> None:
    check_origin(request, [_settings(request).threads_public_origin])


def _live_ready(settings: Settings) -> bool:
    return bool(
        settings.threads_enabled
        and settings.threads_app_id
        and settings.threads_app_secret.get_secret_value()
        and settings.threads_query_logs_redacted
        and settings.cookie_secure
    )


def _require_live(settings: Settings) -> None:
    if not _live_ready(settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Threads の実投稿診断は現在利用できません")


def _session(request: Request) -> ThreadsSession:
    session = _store(request).get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Threads にログインしてください")
    return session


def _cookie(response: Response, settings: Settings, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=min(settings.session_ttl_minutes * 60, 1800),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/threads",
    )


@router.get("/config")
async def config(request: Request) -> dict[str, bool | int]:
    settings = _settings(request)
    return {
        "mock_enabled": settings.threads_mock_mode,
        "gpu_demo_enabled": settings.threads_mock_mode and settings.threads_gpu_demo_enabled,
        "live_enabled": _live_ready(settings),
        "max_posts": settings.threads_max_posts,
        "image_diagnosis_enabled": settings.threads_image_diagnosis,
    }


@router.post("/mock/session")
async def mock_session(
    body: StartRequest, request: Request, response: Response
) -> dict[str, str | bool]:
    _origin(request)
    settings = _settings(request)
    if not settings.threads_mock_mode or not body.consent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "同意またはモック設定がありません")
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(response, settings, _store(request).create(None, "0", "架空のThreadsアカウント"))
    return {"username": "架空のThreadsアカウント", "mock": True}


@router.post("/mock/gpu-session")
async def mock_gpu_session(
    body: StartRequest, request: Request, response: Response
) -> dict[str, str | bool]:
    """架空投稿だけを既存VLMに送る専用セッション。Threads APIには接続しない。"""
    _origin(request)
    settings = _settings(request)
    if not (settings.threads_mock_mode and settings.threads_gpu_demo_enabled and body.consent):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "GPU デモは利用できません")
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(
        response,
        settings,
        _store(request).create(None, "0", "架空のThreadsアカウント", demo_backend="vlm"),
    )
    return {"username": "架空のThreadsアカウント", "mock": True}


@router.post("/start")
async def start(body: StartRequest, request: Request, response: Response) -> dict[str, str]:
    _origin(request)
    settings = _settings(request)
    _require_live(settings)
    if not body.consent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "診断への同意が必要です")
    callback = urlparse(settings.threads_callback_url)
    public = urlparse(settings.threads_public_origin)
    if (
        callback.scheme != "https"
        or callback.scheme != public.scheme
        or callback.netloc != public.netloc
        or callback.path != "/api/threads/callback"
        or callback.query
        or callback.fragment
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Threads のコールバック設定が不正です"
        )
    verifier = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    state = _store(request).start(verifier, nonce)
    response.set_cookie(
        START_COOKIE,
        nonce,
        max_age=START_TTL_S,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/threads",
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.threads_app_id,
            "redirect_uri": settings.threads_callback_url,
            "scope": "threads_basic",
            "state": state,
        }
    )
    return {"authorize_url": f"https://threads.net/oauth/authorize?{query}"}


async def _exchange(code: str, verifier: str, settings: Settings) -> tuple[str, str]:
    del verifier
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                "https://graph.threads.net/oauth/access_token",
                data={
                    "client_id": settings.threads_app_id,
                    "client_secret": settings.threads_app_secret.get_secret_value(),
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.threads_callback_url,
                    "code": code,
                },
            )
            response.raise_for_status()
            payload = response.json()
        token, user_id = payload.get("access_token"), payload.get("user_id")
        if not isinstance(token, str) or not token or not str(user_id).isdigit():
            raise ValueError("invalid token response")
        return token, str(user_id)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Threads の認証に失敗しました") from None


async def _identity(token: str) -> tuple[str, str]:
    async with httpx.AsyncClient(
        base_url=THREADS_API,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        profile = await _get(client, "/me", {"fields": "id,username"})
    user_id, username = profile.get("id"), profile.get("username")
    if (
        not isinstance(user_id, str)
        or not user_id.isdecimal()
        or not isinstance(username, str)
        or not username
    ):
        raise ThreadsPocError("Threads の本人 ID を確認できませんでした")
    return user_id, username


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = "") -> Response:
    settings = _settings(request)
    result = RedirectResponse("/threads?auth_error=failed", status_code=303)
    result.delete_cookie(START_COOKIE, path="/api/threads")
    if not _live_ready(settings):
        return result
    verifier = _store(request).consume(state, request.cookies.get(START_COOKIE))
    if not verifier or error or not code:
        result.headers["location"] = (
            "/threads?auth_error=state" if not verifier else "/threads?auth_error=denied"
        )
        return result
    try:
        token, expected_id = await _exchange(code, verifier, settings)
        owner_id, username = await _identity(token)
        if owner_id != expected_id:
            raise ThreadsPocError("本人 ID が一致しません")
    except (ThreadsPocError, HTTPException):
        return result
    result.headers["location"] = "/threads"
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(result, settings, _store(request).create(token, owner_id, username))
    return result


def _threads_error(exc: ThreadsPocError) -> HTTPException:
    del exc
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Threads API に接続できませんでした")


async def _verified_meta_owner(request: Request) -> str:
    """Meta の signed_request を検証し、本文をログに出さず本人 ID を返す。"""
    secret = _settings(request).threads_app_secret.get_secret_value()
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Threads の設定がありません")
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "リクエストが大きすぎます")
    try:
        fields = parse_qs(body.decode("ascii"), strict_parsing=True)
        signed = fields["signed_request"]
        if len(signed) != 1:
            raise ValueError
        signature, payload = signed[0].split(".")
        if len(signature) > 128 or len(payload) > 8192:
            raise ValueError
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        expected = hmac.new(secret.encode(), payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(data, dict) or data.get("algorithm") != "HMAC-SHA256":
            raise ValueError
        owner_id = data.get("user_id")
        if not str(owner_id).isascii() or not str(owner_id).isdecimal():
            raise ValueError
        return str(owner_id)
    except (KeyError, ValueError, UnicodeError, TypeError, binascii.Error):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "署名を確認できません") from None


@router.post("/deauthorize", status_code=204)
async def deauthorize(request: Request) -> None:
    _store(request).delete_for_owner(await _verified_meta_owner(request))


@router.post("/data-deletion")
async def data_deletion(request: Request) -> dict[str, str]:
    _store(request).delete_for_owner(await _verified_meta_owner(request))
    return {
        "url": f"{_settings(request).threads_public_origin}/threads/data-deletion-status",
        "confirmation_code": secrets.token_hex(16),
    }


@router.get("/session")
async def session(request: Request) -> dict[str, str | bool]:
    current = _session(request)
    return {"username": current.username, "mock": current.token is None}


@router.get("/diagnosis")
async def diagnosis(request: Request) -> dict[str, Any]:
    current = _session(request)
    if current.snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "診断結果がありません")
    return current.snapshot


async def _own_posts(current: ThreadsSession, settings: Settings) -> list[Post]:
    if current.token is not None:
        _require_live(settings)
    if current.fetched:
        return current.posts
    if current.token is None:
        posts, _ = _mock_data()
    else:
        try:
            if settings.threads_image_diagnosis:
                owner_id, posts = await fetch_own_posts(
                    current.token, settings.threads_max_posts, include_images=True
                )
            else:
                owner_id, posts = await fetch_own_posts(current.token, settings.threads_max_posts)
            if owner_id != current.owner_id:
                raise ThreadsPocError("本人 ID が一致しません")
        except ThreadsPocError as exc:
            raise _threads_error(exc) from None
    current.posts = posts
    current.fetched = True
    return posts


@router.get("/posts")
async def posts(request: Request) -> dict[str, Any]:
    """ログイン本人の本文投稿を取得する。モデルが未稼働でも確認できる。"""
    settings = _settings(request)
    current = _session(request)
    if current.token is None and not settings.threads_mock_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "モック投稿は無効です")
    with _store(request).lock:
        if current.busy:
            raise HTTPException(status.HTTP_409_CONFLICT, "処理中です")
        current.busy = True
    try:
        own_posts = await _own_posts(current, settings)
        return {
            "posts": [post.model_dump(mode="json") for post in own_posts],
            "mock": current.token is None,
        }
    finally:
        with _store(request).lock:
            current.busy = False


@router.delete("/session", status_code=204)
async def logout(request: Request, response: Response) -> None:
    _origin(request)
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/api/threads")


# 架空の Threads 投稿（本文だけ）と、モデルを使わない診断で返す手がかり。
# 9003〜9005 は子どものいる保護者の架空投稿で、別々の投稿の「娘の小学校のあおぞらフェスタ」と
# 「あおぞらフェスタは林町小学校の行事」から子どもの学校と、その学区の居住地域を推定できる
# （eval/fixtures/demo_layered.json と同じ作り。人物・行事名は架空、学校名は公開データの表のもの）
MOCK_POSTS: tuple[tuple[str, str, str], ...] = (
    ("9001", "毎週火曜はジムに行く", "2026-11-03T18:00:00+09:00"),
    ("9002", "今週も火曜のジムを終えた", "2026-11-10T18:00:00+09:00"),
    ("9003", "燃えるゴミ出し忘れた。朝はお弁当作りでバタバタ。", "2026-11-04T07:50:00+09:00"),
    ("9004", "娘の小学校のあおぞらフェスタ、今年は輪投げ係になった。", "2026-11-05T21:05:00+09:00"),
    (
        "9005",
        "あおぞらフェスタは林町小学校の秋の行事で、地域の人も来られるらしい。",
        "2026-11-06T12:10:00+09:00",
    ),
)
MOCK_CLUES: tuple[tuple[str, ClueType, str], ...] = (
    ("9001", ClueType.ROUTINE_TEXT, "毎週火曜はジム"),
    ("9002", ClueType.ROUTINE_TEXT, "火曜のジム"),
    ("9003", ClueType.ROUTINE_TEXT, "燃えるゴミ出し忘れた"),
    ("9004", ClueType.RELATION_TEXT, "娘"),
    ("9005", ClueType.ORG_TEXT, "林町小学校"),
)


def _mock_data() -> tuple[list[Post], list[Clue]]:
    posts = [
        to_post({"id": id_, "text": text, "timestamp": when}) for id_, text, when in MOCK_POSTS
    ]
    valid_posts = [post for post in posts if post is not None]
    clues = [
        Clue(
            post_id=f"threads:{id_}",
            image_index=None,
            type=clue_type,
            value=quote,
            region=None,
            confidence=0.9,
            source=ClueSource.TEXT,
            quote=quote,
        )
        for id_, clue_type, quote in MOCK_CLUES
    ]
    return valid_posts, clues


def _preset_extractions(posts: list[Post], clues: list[Clue]) -> list[PostExtraction]:
    return [
        PostExtraction(post_id=post.post_id, clues=[c for c in clues if c.post_id == post.post_id])
        for post in posts
    ]


async def _replayed(extractions: Sequence[PostExtraction]) -> AsyncIterator[PostExtraction]:
    for extraction in extractions:
        yield extraction


POST_ERROR_MESSAGE = "この投稿は読み取れませんでした"


def _infer_events(
    posts: list[Post], extractions: list[PostExtraction], gazetteer: Gazetteer
) -> list[Event]:
    """推理（infer・プロフィールの推定・plan）を、Bluesky と同じ diagnose_events でまとめて行う。

    手がかりの取り出しは済んでいるので、ここはモデルにも Threads API にも接続しない CPU の計算だけ。
    呼び出し側が asyncio.to_thread で別のスレッドに出し、ほかの人の応答を止めない。
    """

    async def collect() -> list[Event]:
        return [event async for event in diagnose_events(posts, _replayed(extractions), gazetteer)]

    return asyncio.run(collect())


def _text_extractor(settings: Settings) -> Extractor:
    """Threads の本文と、有効時だけ写真を読む部品（OCRは使わない）。

    既定は Bluesky と同じ vLLM（VLM_*）で、送り先は MODEL_ALLOWED_HOST_SUFFIXES の許可リストで
    確かめる。THREADS_TEXT_BACKEND=ollama のときだけ Ollama で読む。
    """
    try:
        return build_extractor(
            mock_mode=False,
            vlm_base_url=settings.vlm_base_url,
            vlm_api_key=settings.vlm_api_key.get_secret_value(),
            vlm_model=settings.vlm_model,
            ocr_base_url="",
            allowed_hosts=settings.model_allowed_host_suffixes.split(","),
            text_backend=settings.threads_text_backend,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
        )
    except DetectError:
        # 接続先の URL などは応答に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "本文を読むモデルの設定を確認してください"
        ) from None


async def _reachable_text_extractor(settings: Settings) -> Extractor:
    """診断の前に、Bluesky と同じくモデルの応答を確かめる。"""
    extractor = _text_extractor(settings)
    if not await extractor.model_reachable(settings.model_probe_timeout_seconds):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "本文を読むモデルを利用できません")
    return extractor


@router.post("/diagnose")
async def diagnose(request: Request) -> dict[str, Any]:
    _origin(request)
    settings = _settings(request)
    current = _session(request)
    if current.snapshot is not None:
        return current.snapshot
    with _store(request).lock:
        if current.busy:
            raise HTTPException(status.HTTP_409_CONFLICT, "診断中です")
        current.busy = True
    try:
        if current.token is None:
            if not settings.threads_mock_mode:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "モック診断は無効です")
            posts, preset_clues = _mock_data()
            if current.demo_backend == "vlm":
                extractor = await _reachable_text_extractor(settings)
                extractions = real_extractions(extractor, posts)
            else:
                extractions = _replayed(_preset_extractions(posts, preset_clues))
        else:
            _require_live(settings)
            extractor = await _reachable_text_extractor(settings)
            posts = await _own_posts(current, settings)
            extractions = (
                extract_posts(
                    extractor,
                    posts,
                    fetch_threads_images,
                    image_fetch_fallback_to_text=True,
                )
                if settings.threads_image_diagnosis
                else real_extractions(extractor, posts)
            )
        gazetteer = _cached_gazetteer(settings.gazetteer_dir)
        started = time.monotonic()
        extracted = [extraction async for extraction in extractions]
        # 読み取りに失敗した投稿は全体を止めずに外し、post_errors で知らせる（X と同じ形）。
        # 理由は固定の文言で、本文や例外の中身は入れない
        failed = {e.post_id for e in extracted if e.error is not None}
        post_errors = [
            {"post_id": post.post_id, "error": POST_ERROR_MESSAGE}
            for post in posts
            if post.post_id in failed
        ]
        if posts and len(failed) == len(posts):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "投稿を読み取れませんでした")
        posts = [post for post in posts if post.post_id not in failed]
        events = await asyncio.to_thread(
            _infer_events, posts, [e for e in extracted if e.post_id not in failed], gazetteer
        )
        results = {name: data for name, data in events if name in {"conclusions", "plan"}}
        conclusion = results["conclusions"]
        current.posts = posts
        current.clues = [Clue.model_validate(item) for item in conclusion["clues"]]
        current.profile_claims = _threads_profile_items(conclusion["profile_claims"])
        current.profile_claim_suggestions = list(conclusion["profile_claim_suggestions"])
        current.snapshot = {
            "posts": [post.model_dump(mode="json") for post in posts],
            "clues": conclusion["clues"],
            "conclusions": conclusion["conclusions"],
            "plan": results["plan"],
            "profile_claims": [claim.model_dump(mode="json") for claim in current.profile_claims],
            "profile_claim_suggestions": current.profile_claim_suggestions,
            "post_errors": post_errors,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "mock": current.token is None,
        }
        return current.snapshot
    finally:
        with _store(request).lock:
            current.busy = False


def _selected(body: SimulateRequest, current: ThreadsSession) -> None:
    if current.snapshot is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "先に診断してください")
    known = {post.post_id for post in current.posts}
    if any(post_id not in known for post_id in body.delete):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "診断した投稿から選んでください")


@router.post("/simulate")
async def simulate(body: SimulateRequest, request: Request) -> dict[str, Any]:
    _origin(request)
    current = _session(request)
    _selected(body, current)
    gazetteer = _cached_gazetteer(_settings(request).gazetteer_dir)

    def run() -> dict[str, Any]:
        return simulation_json(
            simulate_deletion(current.clues, current.posts, gazetteer, body.delete), current.clues
        )

    return await asyncio.to_thread(run)


@router.post("/rediagnose")
async def rediagnose(body: SimulateRequest, request: Request) -> dict[str, Any]:
    """仮除外後の投稿・手がかりだけから推論し直す。Threads API とモデルは再呼出ししない。"""
    _origin(request)
    current = _session(request)
    _selected(body, current)
    gazetteer = _cached_gazetteer(_settings(request).gazetteer_dir)
    return await asyncio.to_thread(_rediagnosed, current, set(body.delete), gazetteer)


def _rediagnosed(current: ThreadsSession, gone: set[str], gazetteer: Gazetteer) -> dict[str, Any]:
    posts = [post for post in current.posts if post.post_id not in gone]
    clues = [clue for clue in current.clues if clue.post_id not in gone]
    return {
        "posts": [post.model_dump(mode="json") for post in posts],
        "clues": [clue.model_dump(mode="json") for clue in clues],
        "conclusions": [asdict(c) for c in infer(clues, posts, gazetteer)],
        "plan": plan_json(clues, posts, gazetteer),
        **_claims_without(current, gone),
        "mock": current.token is None,
    }


def _threads_profile_items(raw_sets: list[dict[str, Any]]) -> list[ProfileItem]:
    """Keep the existing Threads response shape at the shared pipeline boundary."""
    items: list[ProfileItem] = []
    for raw_set in raw_sets:
        candidate_set = ProfileCandidateSet.model_validate(raw_set)
        for candidate in candidate_set.candidates:
            items.append(
                ProfileItem(
                    attribute=candidate_set.attribute,
                    value=candidate.value,
                    confidence=candidate.confidence,
                    status=candidate.status,
                    evidence=candidate.evidence,
                    evidence_paths=candidate.evidence_paths,
                    assessment=candidate.assessment,
                )
            )
    return items


def _claims_without(current: ThreadsSession, gone: set[str]) -> dict[str, Any]:
    """仮除外した投稿を根拠から除いたプロフィール推定と、削除候補。

    推定は Bluesky の GET /api/diagnosis と同じ規則（claims_after_deletion）で除く。
    再診断の clues は除いた投稿の分を詰めて返すので、根拠の clue_index もその並びに直す。
    残った推定の根拠は除いた投稿を含まない（claims_after_deletion がその経路を落とす）。
    削除候補は、残った推定の根拠経路に出てくる投稿だけにする（画面の検証と同じ条件）。
    """
    claims = claims_after_deletion(current.profile_claims, gone)
    still_evidence = {
        evidence.post_id
        for claim in claims
        for path in claim.evidence_paths
        for evidence in path.evidence
    }
    return {
        "profile_claims": _renumbered_claims(claims, current.clues, gone),
        "profile_claim_suggestions": [
            post_id
            for post_id in current.profile_claim_suggestions
            if post_id not in gone and post_id in still_evidence
        ],
    }


def _renumbered_claims(
    claims: list[ProfileItem], clues: list[Clue], gone: set[str]
) -> list[dict[str, Any]]:
    kept = [i for i, clue in enumerate(clues) if clue.post_id not in gone]
    renumber = {old: new for new, old in enumerate(kept)}

    def ref(evidence: ProfileEvidence) -> ProfileEvidence:
        if evidence.clue_index is None:
            return evidence
        return evidence.model_copy(update={"clue_index": renumber[evidence.clue_index]})

    return [
        claim.model_copy(
            update={
                "evidence": [ref(e) for e in claim.evidence],
                "evidence_paths": [
                    path.model_copy(update={"evidence": [ref(e) for e in path.evidence]})
                    for path in claim.evidence_paths
                ],
            }
        ).model_dump(mode="json")
        for claim in claims
    ]
