"""X 専用の本人認証・テキスト診断。実 X 投稿の処理は用途と費用の承認で閉じる。"""

import base64
import hashlib
import logging
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from tkb_api.config import Settings
from tkb_api.errors import refusal
from tkb_api.limits import AlreadyRunningError, BusyError, DailyLimitError, DiagnoseLimiter, Lease
from tkb_api.pipeline import (
    diagnose_events,
    plan_json,
    real_extractions,
    simulation_json,
)
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.schemas import SimulateRequest
from tkb_api.x_poc import XPocError, fetch_posts_for_owner, get_my_user, to_post
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.batch import PostExtraction
from tkb_detect.errors import DetectError
from tkb_detect.extract import build_extractor
from tkb_engine.planner import simulate as simulate_deletion
from tkb_engine.rules import infer

router = APIRouter(prefix="/api/x", tags=["x"])
SESSION_COOKIE = "x_tkb_session"
START_COOKIE = "x_oauth_start"
START_TTL_S = 300
# 未認証の POST でも増えるので、件数に上限を付ける（超えたら古い順に捨てる）
MAX_PENDING = 500
MAX_SESSIONS = 500


class XCallbackAccessFilter(logging.Filter):
    """uvicorn のアクセスログから OAuth code と state のクエリを除く。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.startswith("/api/x/callback?"):
                clean = list(args)
                clean[2] = "/api/x/callback"
                record.args = tuple(clean)
        return True


@dataclass
class PendingAuth:
    verifier: str
    nonce: str
    expires_at: float


@dataclass
class XSession:
    token: str | None
    owner_id: str
    username: str
    expires_at: float
    snapshot: dict[str, Any] | None = None
    posts: list[Post] = field(default_factory=list)
    clues: list[Clue] = field(default_factory=list)
    busy: bool = False
    fetched: bool = False
    demo_backend: Literal["preset", "vlm"] = "preset"


class XSessionStore:
    """X の PKCE 情報、トークン、診断結果をプロセスメモリだけに置く。"""

    def __init__(
        self, ttl_s: int, max_pending: int = MAX_PENDING, max_sessions: int = MAX_SESSIONS
    ) -> None:
        self.ttl_s = ttl_s
        self.max_pending = max_pending
        self.max_sessions = max_sessions
        self.pending: dict[str, PendingAuth] = {}
        self.sessions: dict[str, XSession] = {}
        self.lock = RLock()

    def _purge(self) -> None:
        """期限切れを捨て、上限を超えた分を古い順（dict は入れた順）に捨てる。lock の中で呼ぶ。"""
        now = time.monotonic()
        for state in [k for k, v in self.pending.items() if v.expires_at <= now]:
            del self.pending[state]
        for session_id in [k for k, v in self.sessions.items() if v.expires_at <= now]:
            del self.sessions[session_id]
        while len(self.pending) > self.max_pending:
            del self.pending[next(iter(self.pending))]
        while len(self.sessions) > self.max_sessions:
            del self.sessions[next(iter(self.sessions))]

    def start(self, verifier: str, nonce: str) -> str:
        state = secrets.token_urlsafe(32)
        with self.lock:
            self.pending[state] = PendingAuth(verifier, nonce, time.monotonic() + START_TTL_S)
            self._purge()
        return state

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
            self.sessions[session_id] = XSession(
                token,
                owner_id,
                username,
                time.monotonic() + self.ttl_s,
                demo_backend=demo_backend,
            )
            self._purge()
        return session_id

    def get(self, session_id: str | None) -> XSession | None:
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


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.x_settings
    return settings


def _store(request: Request) -> XSessionStore:
    store: XSessionStore = request.app.state.x_sessions
    return store


def _acquire_model_slot(request: Request) -> Lease:
    """モデルを呼ぶ X 診断は、本体の診断と同じ同時実行の枠を取る（1日の回数は数えない）。

    架空アカウントはどのセッションも owner_id が同じなので、枠の鍵はセッション ID から作る。
    """
    limiter: DiagnoseLimiter = request.app.state.diagnose_limiter
    session_id = request.cookies.get(SESSION_COOKIE, "")
    try:
        return limiter.acquire(session_id, f"x-session:{session_id}")
    except AlreadyRunningError:
        raise HTTPException(status.HTTP_409_CONFLICT, "診断中です") from None
    except (BusyError, DailyLimitError):
        retry_after = _settings(request).diagnose_busy_retry_after_seconds
        raise refusal(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "busy",
            "混雑しています",
            headers={"Retry-After": str(retry_after)},
            retry_after=retry_after,
        ) from None


def _origin(request: Request) -> None:
    if request.headers.get("origin") != _settings(request).x_public_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "同じサイトから操作してください")


def _live_ready(settings: Settings) -> bool:
    return bool(
        settings.x_use_case_approved
        and settings.x_paid_reads_approved
        and settings.x_query_logs_redacted
        and settings.x_client_id
        and not settings.x_mock_mode
    )


def _require_live(settings: Settings) -> None:
    if not _live_ready(settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "X の実投稿診断は現在利用できません")


def _session(request: Request) -> XSession:
    session = _store(request).get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X にログインしてください")
    return session


def _cookie(response: Response, settings: Settings, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/x",
    )


@router.get("/config")
async def config(request: Request) -> dict[str, bool | int]:
    settings = _settings(request)
    return {
        "mock_enabled": settings.x_mock_mode,
        "gpu_demo_enabled": settings.x_mock_mode and settings.x_gpu_demo_enabled,
        "live_enabled": _live_ready(settings),
        "max_posts": settings.x_max_posts,
    }


@router.post("/mock/session")
async def mock_session(
    body: StartRequest, request: Request, response: Response
) -> dict[str, str | bool]:
    _origin(request)
    settings = _settings(request)
    if not settings.x_mock_mode or not body.consent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "同意またはモック設定がありません")
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(response, settings, _store(request).create(None, "0", "架空のXアカウント"))
    return {"username": "架空のXアカウント", "mock": True}


@router.post("/mock/gpu-session")
async def mock_gpu_session(
    body: StartRequest, request: Request, response: Response
) -> dict[str, str | bool]:
    """架空投稿だけを既存VLMに送る専用セッション。X APIには接続しない。"""
    _origin(request)
    settings = _settings(request)
    if not (settings.x_mock_mode and settings.x_gpu_demo_enabled and body.consent):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "GPU デモは利用できません")
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(
        response,
        settings,
        _store(request).create(None, "0", "架空のXアカウント", demo_backend="vlm"),
    )
    return {"username": "架空のXアカウント", "mock": True}


@router.post("/start")
async def start(body: StartRequest, request: Request, response: Response) -> dict[str, str]:
    _origin(request)
    settings = _settings(request)
    _require_live(settings)
    if not body.consent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "診断への同意が必要です")
    callback = urlparse(settings.x_callback_url)
    public = urlparse(settings.x_public_origin)
    if (
        callback.scheme != public.scheme
        or callback.netloc != public.netloc
        or callback.path != "/api/x/callback"
        or callback.query
        or callback.fragment
    ):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "X のコールバック設定が不正です")
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    nonce = secrets.token_urlsafe(24)
    state = _store(request).start(verifier, nonce)
    response.set_cookie(
        START_COOKIE,
        nonce,
        max_age=START_TTL_S,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/x",
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.x_client_id,
            "redirect_uri": settings.x_callback_url,
            "scope": "tweet.read users.read",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return {"authorize_url": f"https://x.com/i/oauth2/authorize?{query}"}


async def _exchange(code: str, verifier: str, settings: Settings) -> str:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.x_callback_url,
        "code_verifier": verifier,
    }
    secret = settings.x_client_secret.get_secret_value()
    if not secret:
        data["client_id"] = settings.x_client_id
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=False,
            trust_env=False,
            auth=httpx.BasicAuth(settings.x_client_id, secret) if secret else None,
        ) as client:
            response = await client.post(
                "https://api.x.com/2/oauth2/token",
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "X の認証に失敗しました") from None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    scopes = payload.get("scope", "") if isinstance(payload, dict) else ""
    token_type = payload.get("token_type") if isinstance(payload, dict) else None
    if (
        not isinstance(token, str)
        or not token
        or not isinstance(token_type, str)
        or token_type.lower() != "bearer"
        or not isinstance(scopes, str)
        or not {"tweet.read", "users.read"}.issubset(scopes.split())
    ):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "X の認証情報が不正です")
    return token


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "") -> Response:
    settings = _settings(request)
    _require_live(settings)
    verifier = _store(request).consume(state, request.cookies.get(START_COOKIE))
    if not verifier or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X の認証状態が一致しません")
    token = await _exchange(code, verifier, settings)
    try:
        owner_id, username = await get_my_user(token)
    except XPocError as exc:
        raise _x_error(exc) from None
    result = RedirectResponse("/x", status_code=303)
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    _cookie(result, settings, _store(request).create(token, owner_id, username))
    result.delete_cookie(START_COOKIE, path="/api/x")
    return result


def _x_error(exc: XPocError) -> HTTPException:
    if exc.status_code == 429:
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "X API の回数制限に達しました",
            headers={"Retry-After": "900"},
        )
    if exc.status_code == 401:
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "X にログインし直してください")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "X API に接続できませんでした")


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


@router.delete("/session", status_code=204)
async def logout(request: Request, response: Response) -> None:
    _origin(request)
    _store(request).delete(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/api/x")


def _mock_data() -> tuple[list[Post], list[Clue]]:
    raw = [
        ("9001", "毎週火曜はジムに行く", "2026-11-03T18:00:00+09:00"),
        ("9002", "今週も火曜のジムを終えた", "2026-11-10T18:00:00+09:00"),
    ]
    posts = [
        to_post({"id": id_, "author_id": "0", "text": text, "created_at": when}, "0")
        for id_, text, when in raw
    ]
    valid_posts = [post for post in posts if post is not None]
    clues = [
        Clue(
            post_id=post.post_id,
            image_index=None,
            type=ClueType.ROUTINE_TEXT,
            value=quote,
            region=None,
            confidence=0.9,
            source=ClueSource.TEXT,
            quote=quote,
        )
        for post, quote in zip(valid_posts, ("毎週火曜はジム", "火曜のジム"), strict=True)
    ]
    return valid_posts, clues


async def _preset_extractions(
    posts: list[Post], clues: list[Clue]
) -> AsyncIterator[PostExtraction]:
    for post in posts:
        yield PostExtraction(
            post_id=post.post_id, clues=[c for c in clues if c.post_id == post.post_id]
        )


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
    lease: Lease | None = None
    try:
        if current.token is not None or current.demo_backend == "vlm":
            lease = _acquire_model_slot(request)
        if current.token is None:
            if not settings.x_mock_mode:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "モック診断は無効です")
            posts, preset_clues = _mock_data()
            if current.demo_backend == "vlm":
                try:
                    extractor = build_extractor(
                        mock_mode=False,
                        vlm_base_url=settings.vlm_base_url,
                        vlm_api_key=settings.vlm_api_key.get_secret_value(),
                        vlm_model=settings.vlm_model,
                        ocr_base_url="",
                        allowed_hosts=settings.model_allowed_host_suffixes.split(","),
                        text_backend="vlm",
                    )
                except DetectError:
                    raise HTTPException(
                        status.HTTP_503_SERVICE_UNAVAILABLE, "GPU モデルの設定を確認してください"
                    ) from None
                if not await extractor.model_reachable(settings.model_probe_timeout_seconds):
                    raise HTTPException(
                        status.HTTP_503_SERVICE_UNAVAILABLE, "GPU モデルを利用できません"
                    )
                extractions = real_extractions(extractor, posts)
            else:
                extractions = _preset_extractions(posts, preset_clues)
        else:
            _require_live(settings)
            try:
                extractor = build_extractor(
                    mock_mode=False,
                    vlm_base_url="",
                    vlm_api_key="",
                    vlm_model="",
                    ocr_base_url="",
                    allowed_hosts=[],
                    text_backend="ollama",
                    ollama_base_url=settings.ollama_base_url,
                    ollama_model=settings.ollama_model,
                )
            except DetectError:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "ローカルモデルを利用できません"
                ) from None
            if not await extractor.model_reachable(settings.model_probe_timeout_seconds):
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "ローカルモデルを利用できません"
                )
            if current.fetched:
                posts = current.posts
            else:
                try:
                    posts = await fetch_posts_for_owner(
                        current.token, current.owner_id, settings.x_max_posts
                    )
                except XPocError as exc:
                    raise _x_error(exc) from None
                current.posts = posts
                current.fetched = True
            extractions = real_extractions(extractor, posts)
        gazetteer = get_gazetteer(settings)
        started = time.monotonic()
        events = [event async for event in diagnose_events(posts, extractions, gazetteer)]
        results = {name: data for name, data in events if name in {"conclusions", "plan"}}
        failures = sum(1 for name, data in events if name == "clues" and data["error"])
        if failures:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "一部の投稿の抽出に失敗しました"
            )
        conclusion = results["conclusions"]
        current.posts = posts
        current.clues = [Clue.model_validate(item) for item in conclusion["clues"]]
        current.snapshot = {
            "posts": [post.model_dump(mode="json") for post in posts],
            "clues": conclusion["clues"],
            "conclusions": conclusion["conclusions"],
            "plan": results["plan"],
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "mock": current.token is None,
        }
        return current.snapshot
    finally:
        if lease is not None:
            lease.release()
        with _store(request).lock:
            current.busy = False


def _selected(body: SimulateRequest, current: XSession) -> None:
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
    gazetteer = get_gazetteer(_settings(request))
    return simulation_json(
        simulate_deletion(current.clues, current.posts, gazetteer, body.delete), current.clues
    )


@router.post("/rediagnose")
async def rediagnose(body: SimulateRequest, request: Request) -> dict[str, Any]:
    """仮除外後の投稿・手がかりだけから推論し直す。X API とモデルは再呼出ししない。"""
    _origin(request)
    current = _session(request)
    _selected(body, current)
    gone = set(body.delete)
    posts = [post for post in current.posts if post.post_id not in gone]
    clues = [clue for clue in current.clues if clue.post_id not in gone]
    gazetteer = get_gazetteer(_settings(request))
    return {
        "posts": [post.model_dump(mode="json") for post in posts],
        "clues": [clue.model_dump(mode="json") for clue in clues],
        "conclusions": [asdict(c) for c in infer(clues, posts, gazetteer)],
        "plan": plan_json(clues, posts, gazetteer),
        "mock": current.token is None,
    }
